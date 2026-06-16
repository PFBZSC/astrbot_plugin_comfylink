"""
通用多平台交互式绘图流程处理器
使用 AstrBot 原生 session_waiter 实现多轮对话，以文本编号菜单替代内联键盘，
支持所有平台（QQ、Discord、微信、WebChat 等）的交互式 /draw 流程。

状态机阶段：配置选择 → 对话框变量 → 提示词框架 → 描述 → 触发词 → 解析执行
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController

from ..utils import parser
from ..utils.storage import Storage
from ..services.comfyUIService import ComfyUIService

if TYPE_CHECKING:
    from ..services.drawService import DrawService


class InteractiveDrawHandler:
    """通用交互式绘图流程的状态机处理器

    使用 AstrBot session_waiter 实现跨平台的多轮文本对话，
    以编号菜单（1. 2. 3.）接收用户选择。
    """

    # 阶段常量
    STAGE_CONFIG      = 1  # 选择工作流配置
    STAGE_DIALOG      = 2  # 收集对话框变量
    STAGE_FRAMEWORK   = 3  # 选择提示词框架
    STAGE_DESCRIPTION = 4  # 选择提示词描述
    STAGE_TRIGGER     = 5  # 选择触发词

    def __init__(
        self,
        storage: Storage,
        comfy_service: ComfyUIService,
        draw_service: DrawService,
    ):
        self.storage = storage
        self.comfy_service = comfy_service
        self.draw_service = draw_service

    # ========== 静态工具方法 ==========

    @staticmethod
    def _render_numbered_menu(
        title: str,
        item_names: list[str],
        include_skip: bool = False,
    ) -> str:
        """将选项列表渲染为编号文本菜单

        Args:
            title: 菜单标题（可为空字符串）
            item_names: 选项名称列表
            include_skip: 是否在末尾追加"跳过"选项

        Returns:
            格式化后的菜单文本
        """
        lines = []
        if title:
            lines.append(title)
        for i, name in enumerate(item_names, start=1):
            lines.append(f"{i}. {name}")
        if include_skip:
            lines.append(f"{len(item_names) + 1}. 跳过")
        lines.append("")
        lines.append("请回复数字序号选择，或输入 /stop 取消")
        return "\n".join(lines)

    @staticmethod
    def _parse_choice(user_input: str, max_choice: int) -> int | None:
        """解析用户输入的数字选择

        Args:
            user_input: 用户输入的原始文本
            max_choice: 最大有效序号

        Returns:
            0-based 索引，或 None（无效输入）
        """
        try:
            idx = int(user_input.strip()) - 1
        except ValueError:
            return None
        if 0 <= idx < max_choice:
            return idx
        return None

    # ========== 主入口 ==========

    async def start_flow(self, event: AstrMessageEvent) -> None:
        """启动通用交互式流程

        从 storage 加载配置列表，发送首级菜单，进入 session_waiter 状态机循环。
        """
        tg_config_list = self.storage.get_category("telegram")
        if not tg_config_list:
            await event.send(event.plain_result("后台未配置工作流"))
            return

        # 构建状态字典（闭包捕获，在 waiter 每次调用间保持）
        state: dict = {
            "_stage": self.STAGE_CONFIG,
            "_dialog_queue": [],
            "_trigger_queue": [],
            "tg_config_name": "",
            "tg_config": {},
            "core": {},
            "workflows": {},
            "system_prompt": None,   # 懒加载
            "input_prompt": "",
            "var_list": [],
        }

        # 发送首级菜单
        first_menu = self._render_numbered_menu(
            "选择工作流：",
            [cfg["name"] for cfg in tg_config_list],
        )
        await event.send(event.plain_result(first_menu))

        @session_waiter(timeout=120, record_history_chains=False)
        async def waiter(controller: SessionController, evt: AstrMessageEvent):
            user_input = evt.message_str.strip()

            if user_input == "/stop":
                await evt.send(evt.plain_result("已取消交互式绘图"))
                controller.stop()
                return

            try:
                stage = state["_stage"]
                if stage == self.STAGE_CONFIG:
                    await self._handle_config(evt, controller, state, tg_config_list, user_input)
                elif stage == self.STAGE_DIALOG:
                    await self._handle_dialog(evt, controller, state, user_input)
                elif stage == self.STAGE_FRAMEWORK:
                    await self._handle_framework(evt, controller, state, user_input)
                elif stage == self.STAGE_DESCRIPTION:
                    await self._handle_description(evt, controller, state, user_input)
                elif stage == self.STAGE_TRIGGER:
                    await self._handle_trigger(evt, controller, state, user_input)
            except Exception as e:
                logger.exception(
                    f"[InteractiveDrawHandler] 阶段 {state['_stage']} 发生异常: {e}"
                )
                await evt.send(evt.plain_result(f"处理出错: {str(e)}"))
                controller.stop()

        try:
            await waiter(event)
        except TimeoutError:
            await event.send(event.plain_result("会话超时，请使用 /draw 重新开始"))

    # ========== 阶段推进辅助方法 ==========

    async def _advance_dialog(
        self, event: AstrMessageEvent, controller: SessionController, state: dict,
    ) -> None:
        """弹出下一个对话框项并渲染菜单，或推进到提示词阶段"""
        dialog_queue: list = state.get("_dialog_queue", [])

        if dialog_queue:
            dialog = dialog_queue.pop(0)
            state["_current_dialog"] = dialog
            state["_stage"] = self.STAGE_DIALOG
            text = dialog["text"]
            option_names = [opt["name"] for opt in dialog.get("option", [])]
            menu = self._render_numbered_menu(text, option_names)
            await event.send(event.plain_result(menu))
            controller.keep(timeout=120, reset_timeout=True)
        else:
            # 无对话框项，直接进入提示词阶段
            await self._advance_framework(event, controller, state)

    async def _advance_framework(
        self, event: AstrMessageEvent, controller: SessionController, state: dict,
    ) -> None:
        """进入提示词框架选择阶段（占位，后续 commit 实现）"""
        state["_stage"] = self.STAGE_FRAMEWORK
        await event.send(event.plain_result("（提示词阶段待实现）"))
        controller.keep(timeout=120, reset_timeout=True)

    # ========== 阶段处理器（占位，后续 commit 实现） ==========

    async def _handle_config(
        self, event: AstrMessageEvent, controller: SessionController,
        state: dict, config_list: list, user_input: str,
    ) -> None:
        """阶段1：处理工作流配置选择，加载 core/workflows，进入对话框阶段"""
        idx = self._parse_choice(user_input, len(config_list))
        if idx is None:
            menu = self._render_numbered_menu(
                "输入无效，请重新选择工作流：",
                [cfg["name"] for cfg in config_list],
            )
            await event.send(event.plain_result(menu))
            controller.keep(timeout=120, reset_timeout=True)
            return

        config = config_list[idx]
        state["tg_config_name"] = config.get("name", "")
        state["tg_config"] = config

        # 通过 core_id 加载 core 配置
        core_id = config.get("core_id")
        if core_id is None:
            await event.send(event.plain_result("配置错误：未找到 core_id"))
            controller.stop()
            return

        state["core"] = self.storage.get_file("core", f"{core_id}.json")
        if not state["core"]:
            await event.send(event.plain_result(f"配置错误：无法加载 core 配置 '{core_id}'"))
            controller.stop()
            return

        workflows_name = state["core"].get("workflows")
        if not workflows_name:
            await event.send(event.plain_result("配置错误：core 中未指定 workflows"))
            controller.stop()
            return

        state["workflows"] = self.storage.get_file("workflows", workflows_name)
        if not state["workflows"]:
            await event.send(event.plain_result(f"配置错误：无法加载工作流 '{workflows_name}'"))
            controller.stop()
            return

        # 复制对话框队列（不破坏原始数据）
        state["_dialog_queue"] = list(config.get("dialog", []))

        # 推进到对话框阶段
        await self._advance_dialog(event, controller, state)

    async def _handle_dialog(
        self, event: AstrMessageEvent, controller: SessionController,
        state: dict, user_input: str,
    ) -> None:
        """阶段2：处理对话框变量选择，记录 var_list，继续下一个对话框项"""
        current_dialog: dict = state.get("_current_dialog", {})
        options: list = current_dialog.get("option", [])

        idx = self._parse_choice(user_input, len(options))
        if idx is None:
            text = current_dialog.get("text", "")
            option_names = [opt["name"] for opt in options]
            menu = self._render_numbered_menu(
                f"输入无效，请重新选择：\n{text}", option_names,
            )
            await event.send(event.plain_result(menu))
            controller.keep(timeout=120, reset_timeout=True)
            return

        # 记录变量
        option = options[idx]
        if state.get("var_list") is None:
            state["var_list"] = []
        state["var_list"].append([option.get("var_name", ""), option.get("value", "")])

        # 继续下一个对话框项
        await self._advance_dialog(event, controller, state)

    async def _handle_framework(
        self, event: AstrMessageEvent, controller: SessionController,
        state: dict, user_input: str,
    ) -> None:
        pass

    async def _handle_description(
        self, event: AstrMessageEvent, controller: SessionController,
        state: dict, user_input: str,
    ) -> None:
        pass

    async def _handle_trigger(
        self, event: AstrMessageEvent, controller: SessionController,
        state: dict, user_input: str,
    ) -> None:
        pass

    async def _do_parse_and_execute(
        self, event: AstrMessageEvent, controller: SessionController, state: dict,
    ) -> None:
        pass
