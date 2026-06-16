import asyncio
import aiohttp
import json
import uuid

from astrbot.api import logger


class ComfyUIService:
    def __init__(self, server_address="127.0.0.1:8188"):
        self.server_address = server_address
        self.http_url = f"http://{server_address}"
        self.ws_url = f"ws://{server_address}/ws"

        # 生成唯一客户端ID，防止与 ComfyUI 上其他任务的 WS 消息冲突
        self.client_id = str(uuid.uuid4())

        # 任务分拣字典：{ prompt_id: {queue, listen} }
        self.active_tasks = {}
        # 存储 WS 监听后台任务的句柄
        self._ws_task = None

        # 所有 HTTP/WS 调用的统一超时（30 秒）
        self._http_timeout = aiohttp.ClientTimeout(total=30)
        # 干净关闭信号：set 后重连循环退出
        self._stop_event = asyncio.Event()
        # 可观测的 WS 连接状态
        self._ws_connected = False
        # 立即重连信号：health_check 成功时 set，打断 backoff sleep
        self._reconnect_now = asyncio.Event()

    async def start_listening(self):
        """启动全局的 WebSocket 监听，若已死亡则自动重建"""
        if self._ws_task is None or self._ws_task.done():
            self._stop_event.clear()
            self._ws_task = asyncio.create_task(self._listen_ws())

    async def health_check(self) -> bool:
        """检测 ComfyUI 是否可达

        成功后发送 _reconnect_now 信号，让 backoff sleep 中的
        _listen_ws 立即醒来重连。
        """
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as session:
                async with session.get(f"{self.http_url}/") as resp:
                    if resp.status < 500:
                        self._reconnect_now.set()
                        return True
                    return False
        except Exception:
            return False

    async def _listen_ws(self):
        """后台持续接收 ComfyUI 的广播，支持断线重连与指数退避"""
        backoff = 1  # 初始重试间隔（秒）
        max_backoff = 60

        while not self._stop_event.is_set():
            try:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as session:
                    async with session.ws_connect(
                        f"{self.ws_url}?clientId={self.client_id}"
                    ) as ws:
                        # 连接成功，重置退避
                        backoff = 1
                        self._ws_connected = True
                        logger.info("[ComfyUI] WebSocket 连接成功")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                event_type = data.get("type")
                                event_data = data.get("data", {})
                                prompt_id = event_data.get("prompt_id")

                                if prompt_id not in self.active_tasks:
                                    continue

                                task_ctx = self.active_tasks[prompt_id]
                                queue = task_ctx["queue"]

                                if event_type == "executed":
                                    node_id = event_data.get("node")
                                    output = event_data.get("output")
                                    listen_nodes = task_ctx["listen"]
                                    if not listen_nodes or node_id in listen_nodes:
                                        queue.put_nowait({
                                            "type": "node_result",
                                            "node": node_id,
                                            "output": output,
                                        })

                                elif event_type == "executing":
                                    if event_data.get("node") is None:
                                        queue.put_nowait({"type": "done"})

                                elif event_type == "execution_error":
                                    queue.put_nowait({
                                        "type": "error",
                                        "message": event_data.get("exception_message"),
                                    })

            except asyncio.CancelledError:
                logger.info("[ComfyUI] WebSocket 监听任务被取消")
                break
            except Exception as e:
                self._ws_connected = False
                logger.warning(
                    f"[ComfyUI] WebSocket 连接断开: {e}，{backoff}s 后重试..."
                )

            # 退避等待，可被 stop_event 或 reconnect_now 打断
            if not self._stop_event.is_set():
                stop_task = asyncio.create_task(self._stop_event.wait())
                reconnect_task = asyncio.create_task(self._reconnect_now.wait())
                await asyncio.wait(
                    [stop_task, reconnect_task],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=backoff,
                )
                # 清理未完成的任务
                for t in [stop_task, reconnect_task]:
                    if not t.done():
                        t.cancel()
                self._reconnect_now.clear()

                if self._stop_event.is_set():
                    break

                backoff = min(backoff * 2, max_backoff)

        self._ws_connected = False
        logger.info("[ComfyUI] WebSocket 监听已退出")

    async def send(self, workflow_data: dict, listen: list):
        """提交任务，并逐个 yield 产出监听节点的执行结果"""
        payload = {"prompt": workflow_data, "client_id": self.client_id}

        async with aiohttp.ClientSession(timeout=self._http_timeout) as session:
            async with session.post(f"{self.http_url}/prompt", json=payload) as resp:
                reply = await resp.json()
                if "error" in reply:
                    raise ValueError(f"提交失败: {reply['error']}")
                prompt_id = reply["prompt_id"]

        # 为当前任务创建专属队列
        queue = asyncio.Queue()
        self.active_tasks[prompt_id] = {
            "queue": queue,
            "listen": [str(n) for n in listen]
        }

        try:
            # 持续从队列消费并抛出，直到收到结束信号
            # 如果 WS 监听器已死，600s 超时防止永久挂起
            while True:
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=600)
                except asyncio.TimeoutError:
                    raise Exception(
                        "ComfyUI 响应超时，请检查 ComfyUI 是否正常运行"
                    )

                if result["type"] == "done":
                    break  # 任务彻底结束，退出生成器

                elif result["type"] == "error":
                    raise Exception(f"渲染出错: {result['message']}")

                elif result["type"] == "node_result":
                    # 组装为字典直接 yield 给外层
                    yield {result["node"]: result["output"]}

        finally:
            # 无论成功或报错，清理上下文
            self.active_tasks.pop(prompt_id, None)

    async def query(self, prompt_id: str):
        """查询特定任务的详细历史信息"""
        async with aiohttp.ClientSession(timeout=self._http_timeout) as session:
            async with session.get(f"{self.http_url}/history/{prompt_id}") as resp:
                return await resp.json()

    async def stop(self):
        """中断当前 ComfyUI 正在执行的任务"""
        async with aiohttp.ClientSession(timeout=self._http_timeout) as session:
            async with session.post(f"{self.http_url}/interrupt") as resp:
                return resp.status == 200

    async def upload_image(self, image_bytes: bytes, filename: str | None = None):
        """上传图片到 ComfyUI 的 input 目录（支持自动识别格式与唯一命名）"""

        # 1. 尝试从字节流中识别文件类型（需要事先引入 python-magic，或通过前几个字节判断）
        # 这里提供一个轻量且无外部依赖的纯字节判断方案：
        if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            ext, mime = '.png', 'image/png'
        elif image_bytes.startswith(b'\xff\xd8\xff'):
            ext, mime = '.jpg', 'image/jpeg'
        elif image_bytes.startswith(b'RIFF') and image_bytes[8:12] == b'WEBP':
            ext, mime = '.webp', 'image/webp'
        else:
            ext, mime = '.png', 'image/png'  # 兜底方案

        # 2. 如果未指定文件名，使用 UUID 防止并发覆盖，并拼接正确后缀
        if not filename:
            filename = f"{uuid.uuid4()}{ext}"

        data = aiohttp.FormData()
        data.add_field('image', image_bytes, filename=filename, content_type=mime)
        data.add_field('overwrite', 'true')

        async with aiohttp.ClientSession(timeout=self._http_timeout) as session:
            async with session.post(f"{self.http_url}/upload/image", data=data) as resp:
                return await resp.json()

    async def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output"):
        """根据产物元数据下载真实图片字节流"""
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type
        }
        async with aiohttp.ClientSession(timeout=self._http_timeout) as session:
            # 发起 GET 请求拉取图片文件
            async with session.get(f"{self.http_url}/view", params=params) as resp:
                if resp.status == 200:
                    return await resp.read()  # 返回二进制 bytes
                else:
                    raise Exception(f"获取图片失败，HTTP 状态码: {resp.status}")

    async def close(self):
        """清理资源与后台任务"""
        if self._ws_task:
            self._ws_task.cancel()