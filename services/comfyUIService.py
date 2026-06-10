import asyncio
import aiohttp
import json
import uuid


class ComfyUIService:
    def __init__(self, server_address="127.0.0.1:8188"):
        self.server_address = server_address
        self.http_url = f"http://{server_address}"
        self.ws_url = f"ws://{server_address}/ws"

        # 生成唯一客户端ID，防止与 ComfyUI 上其他任务的 WS 消息冲突
        self.client_id = str(uuid.uuid4())

        # 任务分拣字典：{ prompt_id: asyncio.Future }
        self.active_tasks = {}
        # 存储 WS 监听后台任务的句柄
        self._ws_task = None

    async def start_listening(self):
        """启动全局的 WebSocket 监听（在发送任何任务前调用即可）"""
        if self._ws_task is None:
            self._ws_task = asyncio.create_task(self._listen_ws())

    async def _listen_ws(self):
        """后台持续接收 ComfyUI 的广播，并精准唤醒对应的挂起任务"""
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"{self.ws_url}?clientId={self.client_id}") as ws:
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

                        # 1. 某个节点完成，立刻放入队列
                        if event_type == "executed":
                            node_id = event_data.get("node")
                            output = event_data.get("output")
                            listen_nodes = task_ctx["listen"]

                            # 如果节点在目标列表内（或未指定列表），立刻塞入队列
                            if not listen_nodes or node_id in listen_nodes:
                                # 使用 put_nowait 防止阻塞 WS 监听器
                                queue.put_nowait({"type": "node_result", "node": node_id, "output": output})

                        # 2. 整个工作流执行结束
                        elif event_type == "executing":
                            if event_data.get("node") is None:
                                queue.put_nowait({"type": "done"})

                        # 3. 异常处理
                        elif event_type == "execution_error":
                            error_msg = event_data.get("exception_message")
                            queue.put_nowait({"type": "error", "message": error_msg})

    async def send(self, workflow_data: dict, listen: list = None):
        """提交任务，并逐个 yield 产出监听节点的执行结果"""
        listen = listen or []
        payload = {"prompt": workflow_data, "client_id": self.client_id}

        async with aiohttp.ClientSession() as session:
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
            while True:
                result = await queue.get()

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
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.http_url}/history/{prompt_id}") as resp:
                return await resp.json()

    async def stop(self):
        """中断当前 ComfyUI 正在执行的任务"""
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.http_url}/interrupt") as resp:
                return resp.status == 200

    async def upload_image(self, image_bytes: bytes, filename: str = None):
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

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.http_url}/upload/image", data=data) as resp:
                return await resp.json()

    async def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output"):
        """根据产物元数据下载真实图片字节流"""
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type
        }
        async with aiohttp.ClientSession() as session:
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