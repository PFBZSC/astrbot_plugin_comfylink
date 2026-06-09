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

                        # 1. 收集单个节点的执行结果
                        if event_type == "executed":
                            node_id = event_data.get("node")
                            output = event_data.get("output")
                            # 将产物存入该任务的临时缓存区
                            task_ctx["outputs"][node_id] = output

                        # 2. 监听整个工作流是否执行结束 (node 为 None 代表队列中的该任务已完成)
                        elif event_type == "executing":
                            if event_data.get("node") is None:
                                # 结算时刻：根据 listen 列表提取目标数据
                                listen_nodes = task_ctx["listen"]
                                final_result = {}

                                if listen_nodes:
                                    # 只提取指定的节点产物
                                    for nid in listen_nodes:
                                        if nid in task_ctx["outputs"]:
                                            final_result[nid] = task_ctx["outputs"][nid]
                                else:
                                    # 如果未指定 listen，则返回所有收集到的产物
                                    final_result = task_ctx["outputs"]

                                task_ctx["future"].set_result(final_result)

                        # 3. 异常处理保持不变
                        elif event_type == "execution_error":
                            error_msg = event_data.get("exception_message")
                            task_ctx["future"].set_exception(Exception(f"渲染出错: {error_msg}"))

    async def send(self, workflow_data: dict, listen: list = None):
        """
        提交任务并挂起
        :param workflow_data: 工作流 JSON 字典
        :param listen: 需要监听并返回产物的 node_id 列表，例如 ["9", "15"]
        """
        listen = listen or []
        payload = {"prompt": workflow_data, "client_id": self.client_id}

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.http_url}/prompt", json=payload) as resp:
                reply = await resp.json()
                if "error" in reply:
                    raise ValueError(f"提交失败: {reply['error']}")
                prompt_id = reply["prompt_id"]

        loop = asyncio.get_running_loop()
        fut = loop.create_future()

        # 升级上下文结构，携带 future、listen 配置和暂存区
        self.active_tasks[prompt_id] = {
            "future": fut,
            "listen": [str(n) for n in listen],  # 确保转为字符串以匹配 WS 返回的 ID 格式
            "outputs": {}
        }

        try:
            return await fut
        finally:
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

    async def upload_image(self, image_bytes: bytes, filename: str = "upload.png"):
        """上传图片到 ComfyUI 的 input 目录"""
        data = aiohttp.FormData()
        data.add_field('image', image_bytes, filename=filename, content_type='image/png')
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