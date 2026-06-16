"""
Telegram 交互式绘图流程处理器
负责内联键盘交互的完整状态机：配置选择 → 对话框 → 提示词 → 解析执行
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, List

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..telegram.tg_session_controller import TelegramSessionController
from ..utils import parser
from ..utils.tg_inline_builder import keyboard_build
from ..utils.tg_decorators import tg_callback
from ..utils.storage import Storage
from ..services.tgManagerService import TelegramManagerService, TelegramInstance
from ..services.comfyUIService import ComfyUIService

if TYPE_CHECKING:
    from ..services.drawService import DrawService


class TgDrawHandler:
    """Telegram 交互式绘图流程的状态机处理器"""

    # 精确匹配的命令 → handler 方法名
    _EXACT_HANDLERS: dict[str, str] = {
        "get_tg_config": "_handle_get_config",
        "get_setting":   "_handle_get_setting",
        "send_setting":  "_handle_send_setting",
        "parse":         "_handle_parse",
    }

    def __init__(
        self,
        storage: Storage,
        tg_sc: TelegramSessionController,
        comfy_service: ComfyUIService,
        tg_mgr: TelegramManagerService,
        draw_service: DrawService,
    ):
        self.storage = storage
        self.tg_sc = tg_sc
        self.comfy_service = comfy_service
        self.tg_mgr = tg_mgr
        self.draw_service = draw_service

    def register(self) -> None:
        """向 TelegramManagerService 注册本实例上 @tg_callback 装饰的方法"""
        self.tg_mgr.register_routes(self)

    # ========== 主入口 ==========

    async def start_flow(self, event: AstrMessageEvent, tg_inst: TelegramInstance) -> None:
        """启动交互式流程：创建会话 → 发送工作流选择键盘 → 绑定超时

        DrawService._handle_telegram 将调用此方法作为主入口。
        """
        tg_config_list = self.storage.get_category("telegram")
        if not tg_config_list:
            await tg_inst.send(event.get_session_id(), "后台未配置工作流")
            return

        session_id = self.tg_sc.create_session(timeout=60)
        self.tg_sc.get_data(session_id)["event"] = event

        keyboard = self._render_workflow_keyboard(tg_config_list, session_id)
        msg_id = await tg_inst.send(
            event.get_session_id(), "选择工作流：", reply_markup=keyboard
        )
        bound_callback = partial(
            self.draw_service.tg_terminate,
            tg_inst=tg_inst,
            chat_id=event.get_session_id(),
            message_id=msg_id,
        )
        self.tg_sc.update_callback(session_id, bound_callback)

    @tg_callback("tg_draw")
    async def tg_draw(self, update: Update, _context: ContextTypes.DEFAULT_TYPE, value: str) -> None:
        """内联键盘回调入口 — 校验会话 → 解析输入 → 分发到对应 handler"""
        logger.info(f"[TgDrawHandler] 收到回调: {value}")

        parts = self._parse_value(value)
        if parts is None:
            logger.error(f"[TgDrawHandler] 无法解析回调数据: {value}")
            return
        command, user_input, session_id = parts

        data = self._get_session_or_fail(session_id, update)
        if data is None:
            return

        # 重置会话超时计时器
        await self.tg_sc.reset_timer(session_id)

        await self._dispatch(command, user_input, session_id, data, update)

    # ========== 输入解析 ==========

    @staticmethod
    def _parse_value(value: str) -> tuple[str, str, str] | None:
        """安全解析回调字符串 'command:user_input:session_id'

        返回 (command, user_input, session_id) 或 None（格式错误）。
        user_input 中可能包含 ':'，所以只按前两个冒号分割。
        """
        if not value or ":" not in value:
            return None
        parts = value.split(":", 2)
        if len(parts) != 3:
            return None
        return parts[0], parts[1], parts[2]

    def _get_session_or_fail(self, session_id: str, update: Update) -> dict | None:
        """获取会话数据，会话不存在时发送错误提示并返回 None"""
        data = self.tg_sc.get_data(session_id)
        if data is None:
            logger.warning(f"[TgDrawHandler] 会话不存在或已超时: {session_id}")
            # 异步发送错误消息（不等待以防火上浇油）
            asyncio.create_task(
                update.effective_sender.send_message("选择无效，会话已超时")
            )
            return None
        return data

    # ========== 命令分发 ==========

    async def _dispatch(
        self,
        command: str,
        user_input: str,
        session_id: str,
        data: dict,
        update: Update,
    ) -> None:
        """按 command 前缀路由到对应的 handler 方法"""
        try:
            if command in self._EXACT_HANDLERS:
                handler_name = self._EXACT_HANDLERS[command]
                handler = getattr(self, handler_name)
                await handler(update, session_id, user_input, data)
            elif command.startswith("get_prompt_"):
                stage = int(command[len("get_prompt_"):])
                await self._handle_get_prompt(update, session_id, stage, user_input, data)
            elif command.startswith("send_prompt_"):
                stage = int(command[len("send_prompt_"):])
                await self._handle_send_prompt(update, session_id, stage, data)
            else:
                logger.error(f"[TgDrawHandler] 未知命令: {command}")
        except Exception:
            logger.exception(f"[TgDrawHandler] 执行 handler 时发生异常, command={command}")

    # ========== 阶段 1: 配置加载 ==========

    async def _handle_get_config(
        self, update: Update, session_id: str, user_input: str, data: dict
    ) -> None:
        """加载 TG 配置 → core 配置 → workflows JSON"""
        data["tg_config_name"] = user_input

        # 查找匹配的 telegram 配置
        tg_config_list = self.storage.get_category("telegram")
        config = {}
        for each in tg_config_list:
            if each.get("name") == user_input:
                config = each
                break
        data["tg_config"] = config

        if not config:
            await self.tg_sc.close_session(session_id)
            await update.callback_query.edit_message_text("获取配置时出现错误：未找到 tg_config")
            return

        # 通过 core_id 获取 core 配置
        core_id = config.get("core_id")
        if core_id is None:
            await self.tg_sc.close_session(session_id)
            await update.callback_query.edit_message_text("获取配置时出现错误：未找到 tg_config 中 core_id")
            return

        data["core"] = self.storage.get_file("core", f"{core_id}.json")

        workflows = data["core"].get("workflows")
        if workflows is None:
            await self.tg_sc.close_session(session_id)
            await update.callback_query.edit_message_text("获取配置时出现错误：未找到 config 中 workflows")
            return

        data["workflows"] = self.storage.get_file("workflows", workflows)

        # 创建 dialog 队列副本，避免破坏原始配置数据
        data["_dialog_queue"] = list(config.get("dialog", []))

        # 推进到对话框阶段
        await self._handle_send_setting(update, session_id, "", data)

    # ========== 阶段 2: 对话框变量收集 ==========

    async def _handle_get_setting(
        self, update: Update, session_id: str, user_input: str, data: dict
    ) -> None:
        """收集对话框变量 var_name=value"""
        if "=" not in user_input:
            logger.warning(f"[TgDrawHandler] get_setting 格式无效: {user_input}")
            await self._handle_send_setting(update, session_id, "", data)
            return

        var_name, var_value = user_input.split("=", 1)
        if var_name and var_value:
            if data.get("var_list") is None:
                data["var_list"] = []
            data["var_list"].append([var_name, var_value])

        # 继续处理下一个对话框项
        await self._handle_send_setting(update, session_id, "", data)

    async def _handle_send_setting(
        self, update: Update, session_id: str, _user_input: str, data: dict
    ) -> None:
        """弹出下一个对话框项并渲染选项键盘，或推进到提示词阶段"""
        dialog_queue: list = data.get("_dialog_queue", [])

        if dialog_queue:
            dialog = dialog_queue.pop(0)
            text = dialog["text"]
            keyboard = self._render_dialog_keyboard(dialog, session_id)
            await update.callback_query.edit_message_text(text, reply_markup=keyboard)
        else:
            # 对话框处理完毕，进入提示词阶段
            await self._handle_send_prompt(update, session_id, stage=1, data=data)

    # ========== 阶段 3: 提示词选择 ==========

    async def _handle_get_prompt(
        self, update: Update, session_id: str, stage: int, user_input: str, data: dict
    ) -> None:
        """处理提示词选择，累积到 input_prompt"""
        system_prompt = data.get("system_prompt", {})

        if stage == 1:
            framework_list = system_prompt.get("framework", [])
            try:
                idx = int(user_input)
                data["input_prompt"] = framework_list[idx]["text"]
            except (IndexError, ValueError):
                logger.error(f"[TgDrawHandler] 提示词框架选择索引无效: {user_input}")
            await self._handle_send_prompt(update, session_id, stage=2, data=data)

        elif stage == 2:
            description_list = system_prompt.get("description", [])
            try:
                idx = int(user_input)
                data["input_prompt"] = parser.smart_format(
                    data.get("input_prompt", ""), description_list[idx]["text"]
                )
            except (IndexError, ValueError):
                logger.error(f"[TgDrawHandler] 提示词描述选择索引无效: {user_input}")
            await self._handle_send_prompt(update, session_id, stage=3, data=data)

        else:
            # stage >= 3: 触发词选择
            trigger_queue: list = data.get("_trigger_queue", [])
            if trigger_queue:
                try:
                    idx = int(user_input)
                    trigger = trigger_queue.pop(idx)
                    data["input_prompt"] = parser.smart_format(
                        data.get("input_prompt", ""), trigger["text"]
                    )
                except (IndexError, ValueError):
                    logger.error(f"[TgDrawHandler] 触发词选择索引无效: {user_input}")
                await self._handle_send_prompt(
                    update, session_id, stage=stage + 1, data=data
                )
            else:
                # 无更多触发词，直接进入解析
                await self._handle_parse(update, session_id, "", data)

    async def _handle_send_prompt(
        self, update: Update, session_id: str, stage: int, data: dict
    ) -> None:
        """渲染提示词选择键盘，或推进到下一阶段／解析"""
        # 懒加载 system.json
        if data.get("system_prompt") is None:
            data["system_prompt"] = self.storage.get_file("prompt", "system.json") or {}
            # 创建 trigger 队列副本
            trigger_list = data["system_prompt"].get("trigger")
            data["_trigger_queue"] = list(trigger_list) if trigger_list else []

        system_prompt: dict = data["system_prompt"]
        text = ""
        stage_prompt = None

        if stage == 1:
            stage_prompt = system_prompt.get("framework")
            text = "选择提示词框架："
        elif stage == 2:
            stage_prompt = system_prompt.get("description")
            text = "选择提示词描述："
        else:
            # stage >= 3: 检查是否还有触发词
            trigger_queue: list = data.get("_trigger_queue", [])
            if trigger_queue:
                stage_prompt = trigger_queue
                text = "选择提示词触发词："

        if text and stage_prompt:
            keyboard = self._render_prompt_keyboard(stage, stage_prompt, session_id)
            await update.callback_query.edit_message_text(text, reply_markup=keyboard)
        else:
            # 当前阶段无内容，直接进入解析
            await self._handle_parse(update, session_id, "", data)

    # ========== 阶段 4: 解析与执行 ==========

    async def _handle_parse(
        self, update: Update, session_id: str, _user_input: str, data: dict
    ) -> None:
        """组装所有数据 → parser.parse_data() → 执行 ComfyUI 工作流"""
        core = data.get("core")
        workflows = data.get("workflows")
        var_list = data.get("var_list")
        prompt = data.get("input_prompt")

        parsed_data = parser.parse_data(core["commands"], prompt, var_list, [core])

        if not parsed_data:
            await update.callback_query.edit_message_text("解析时出现错误")
            return

        listen_node = [each.id for each in parsed_data.outputs]

        # 是否需要上传图片
        if inputs_images := parsed_data.inputs_images:
            await update.callback_query.edit_message_text("参数记录完毕")
            event = data["event"]
            await self.tg_sc.close_session(session_id)

            # 放入后台任务防阻塞
            async def process_and_send():
                final_images = await self.draw_service._collect_images(event, inputs_images)
                if not final_images:
                    return
                parsed_data.inputs_images = final_images
                final_workflows = parser.parse_comfy_data(parsed_data, workflows)
                logger.info(f"[TgDrawHandler] 监听节点：{listen_node}")
                logger.info(f"[TgDrawHandler] core: {core}")
                logger.info(f"[TgDrawHandler] parsed_data: {parsed_data}")
                await self.draw_service._execute_and_send_tg(
                    update, final_workflows, listen_node, parsed_data.outputs
                )

            asyncio.create_task(process_and_send())
        else:
            # 无需图片，直接装配并执行
            final_workflows = parser.parse_comfy_data(parsed_data, workflows)
            logger.info(f"[TgDrawHandler] 监听节点：{listen_node}")
            await self.draw_service._execute_and_send_tg(
                update, final_workflows, listen_node, parsed_data.outputs
            )

    # ========== 键盘渲染辅助方法 ==========

    def _render_workflow_keyboard(
        self, configs: list, session_id: str
    ) -> InlineKeyboardMarkup:
        """构建工作流选择键盘"""
        choices = [
            (each["name"], f"get_tg_config:{each['name']}:{session_id}")
            for each in configs
        ]
        return keyboard_build(choices, "tg_draw", 3)

    def _render_dialog_keyboard(
        self, dialog_item: dict, session_id: str
    ) -> InlineKeyboardMarkup:
        """构建对话框选项键盘"""
        choices = [
            (
                option["name"],
                f"get_setting:{option['var_name']}={option['value']}:{session_id}",
            )
            for option in dialog_item["option"]
        ]
        return keyboard_build(choices, "tg_draw", 3)

    def _render_prompt_keyboard(
        self, stage: int, items: list, session_id: str
    ) -> InlineKeyboardMarkup:
        """构建提示词选择键盘（含"跳过"选项）"""
        choices = [
            (item["name"], f"get_prompt_{stage}:{i}:{session_id}")
            for i, item in enumerate(items)
        ]
        choices.append(("跳过", f"parse::{session_id}"))
        return keyboard_build(choices, "tg_draw", 3)
