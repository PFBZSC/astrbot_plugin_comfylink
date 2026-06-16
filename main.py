import asyncio
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig
from telegram import Update
from telegram.ext import ContextTypes

from .telegram.tg_session_controller import TelegramSessionController
from .utils.tg_decorators import tg_callback
from .utils import parser
from .utils.storage import Storage
from .utils.tg_inline_builder import keyboard_build
from .services.drawService import DrawService
from .handlers.web_api import WebApiHandler
from .services.tgManagerService import TelegramManagerService
from .services.comfyUIService import ComfyUIService

@register("astrbot_plugin_comfylink", "PFBZSC", "AstrBot联动ComfyUI", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        logger.info("MyPlugin 初始化开始")
        self.config = config

        self.storage = Storage(self.name)

        self.api_service = WebApiHandler(self.context, self.name,self.storage)
        self.api_service.register()

        self.tg_mgr = TelegramManagerService()
        self.tg_sc = TelegramSessionController()
        self.comfy_service = ComfyUIService(self.config.get("url"))
        self.draw_service = DrawService(context,self.storage,self.tg_mgr,self.tg_sc,self.comfy_service)

        self.tg_mgr.register_routes(self)

        asyncio.create_task(self.start_listening())

    async def start_listening(self):
        await self.comfy_service.start_listening()

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent):
        event.stop_event()# 暂不考虑事件传播，先一刀切了吧
        configs = self.storage.get_category("core")
        parsed_data = parser.parse_cmd(event.message_str,configs)

        await self.draw_service.handle_draw(event,parsed_data)

    @filter.command("test")
    @filter.platform_adapter_type(filter.PlatformAdapterType.TELEGRAM)
    async def test(self,event:AstrMessageEvent):
        event.stop_event()
        platform_id = event.get_platform_id()
        if platform_id not in self.tg_mgr:
            await self.tg_mgr.add_inst(event,self.context)
        tg_inst = self.tg_mgr.get(platform_id)
        if tg_inst is None:
            logger.error(f"无法获取 Telegram 实例: {platform_id}")
            return

        reply_markup = keyboard_build([
            ("选项A", "choice_A"),
            ("选项B", "choice_B")
        ], "call_test",2)

        await tg_inst.send(
            event.get_session_id(),
            "选择选项：",
            reply_markup = reply_markup
        )
    @tg_callback("call_test")
    async def call_test(self,update:Update,context: ContextTypes.DEFAULT_TYPE,value:str):
        logger.info("触发call_test")
        await update.callback_query.edit_message_text(f"你选择了：{value}")

    async def terminate(self):
        await self.comfy_service.close()
        self.tg_mgr.terminate()