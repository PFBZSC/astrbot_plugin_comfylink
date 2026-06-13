import asyncio
from typing import Dict,Any
import secrets

class TelegramSessionController:
    def __init__(self):
        self.sessions:Dict[str, Dict] = {}
        self._timers: Dict[str, asyncio.Task] = {}

    def create_session(self,timeout:float=60) -> str:
        session_id = secrets.token_urlsafe(7)
        self.sessions[session_id] = {
            "data":{},
            "timeout":timeout
        }

        self._timers[session_id] = asyncio.create_task(
            self._timer_countdown(session_id, timeout)
        )

        return session_id

    def get_data(self, session_id: str) -> Any:
        """对外暴露获取真实数据的接口"""
        session_node = self.sessions.get(session_id)
        return session_node["data"] if session_node else None

    async def reset_timer(self, session_id: str, timeout: float = -1) -> bool:
        """
        重置指定 session 的计时时长
        :param session_id: 会话id
        :param timeout: 新的超时时间。若为 -1，则使用 default_timeout
        :return: 重置成功返回 True，若 session 不存在返回 False
        """
        if session_id not in self.sessions:
            return False

        # 取消当前的计时任务
        await self._cancel_timer(session_id)

        # 确定新的超时时长
        actual_timeout = self.sessions[session_id]["timeout"] if timeout == -1 else timeout

        # 重新启动计时任务
        self._timers[session_id] = asyncio.create_task(
            self._timer_countdown(session_id, actual_timeout)
        )
        return True

    async def _timer_countdown(self, session_id: str, timeout: float) -> None:
        """内部异步计时逻辑"""
        try:
            await asyncio.sleep(timeout)
            # 时间到，执行剔除逻辑
            self.sessions.pop(session_id, None)
            self._timers.pop(session_id, None)
        except asyncio.CancelledError:
            # 任务被取消（说明被重置或手动销毁），不做任何处理
            pass

    async def _cancel_timer(self, session_id: str) -> None:
        timer_task = self._timers.pop(session_id, None)
        if timer_task and not timer_task.done():
            timer_task.cancel()
            try:
                await timer_task
            except asyncio.CancelledError:
                pass