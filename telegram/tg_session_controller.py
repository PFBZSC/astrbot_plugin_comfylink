import asyncio
from typing import Dict,Any,Callable
import inspect
import secrets
# from astrbot.api import logger

class TelegramSessionController:
    def __init__(self):
        self.sessions:Dict[str, Dict] = {}
        self._timers: Dict[str, asyncio.Task] = {}

    def create_session(self,timeout:float=60,callback:Callable|None = None) -> str:
        session_id = secrets.token_urlsafe(7)

        # 先创建 timer，成功后再存储 session — 避免 task 创建失败导致
        # 永久泄漏（session 无超时守卫）
        timer_task = asyncio.create_task(
            self._timer_countdown(session_id, timeout)
        )
        self._timers[session_id] = timer_task
        self.sessions[session_id] = {
            "data":{},
            "timeout":timeout,
            "callback":callback,
            "_callback_fired": False,
        }

        return session_id

    def get_data(self, session_id: str) -> Any:
        """对外暴露获取真实数据的接口"""
        session_node = self.sessions.get(session_id)
        return session_node["data"] if session_node else None

    def update_callback(self, session_id: str, new_callback: Callable) -> bool:
        """允许在运行途中动态更换回调函数"""
        if session_id not in self.sessions:
            return False
        self.sessions[session_id]["callback"] = new_callback
        return True

    async def reset_timer(self, session_id: str, timeout: float = -1) -> bool:
        """
        重置指定 session 的计时时长
        :param session_id: 会话id
        :param timeout: 新的超时时间。若为 -1，则使用 default_timeout
        :return: 重置成功返回 True，若 session 不存在返回 False
        """
        if session_id not in self.sessions:
            return False

        # 确定新的超时时长
        actual_timeout = self.sessions[session_id]["timeout"] if timeout == -1 else timeout

        # 先创建新 timer，再取消旧的 — 避免创建失败导致 session 无超时守卫
        new_task = asyncio.create_task(
            self._timer_countdown(session_id, actual_timeout)
        )

        old_task = self._timers.get(session_id)
        if old_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass

        self._timers[session_id] = new_task
        return True

    async def close_session(self, session_id: str, trigger_callback: bool = False) -> bool:
        """
        显式关闭/结束指定会话
        :param session_id: 会话 id
        :param trigger_callback: 是否在关闭时触发回调，默认False
        :return: 关闭成功返回 True，若 session 不存在返回 False
        """
        if session_id not in self.sessions:
            return False

        # 1. 立即取消并清理计时器，防止触发 _timer_countdown 中的默认剔除逻辑
        await self._cancel_timer(session_id)

        # 2. 弹出并获取会话数据
        session = self.sessions.pop(session_id, None)
        if not session:
            return False

        # 3. 根据参数决定是否执行回调（带 _callback_fired 防护）
        if trigger_callback and not session.get("_callback_fired"):
            session["_callback_fired"] = True
            callback:Callable|None = session.get("callback")
            if callback:
                if inspect.iscoroutinefunction(callback):
                    await callback(session_id, session.get("data"))
                else:
                    callback(session_id, session.get("data"))

        return True

    async def _timer_countdown(self, session_id: str, timeout: float) -> None:
        """内部异步计时逻辑"""
        try:
            await asyncio.sleep(timeout)
            # 时间到，执行剔除逻辑
            session = self.sessions.pop(session_id, None)
            self._timers.pop(session_id, None)

            if session and not session.get("_callback_fired"):
                session["_callback_fired"] = True
                callback:Callable|None = session.get("callback")
                if callback:
                    if inspect.iscoroutinefunction(callback):
                        await callback(session_id,session.get("data"))
                    else:
                        callback(session_id,session.get("data"))

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