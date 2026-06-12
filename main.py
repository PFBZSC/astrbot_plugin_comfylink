import asyncio
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig

from .utils import parser
from .utils.storage import Storage
from .services.drawService import DrawService
from .handlers.web_api import WebApiHandler
from .services.tgManagerService import TelegramManagerService
from .services.comfyUIService import ComfyUIService

@register("astrbot_plugin_comfylink", "PFBZSC", "AstrBot联动ComfyUI", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.storage = Storage(self.name)

        self.api_service = WebApiHandler(self.context, self.name,self.storage)
        self.api_service.register()

        self.tg_mgr = TelegramManagerService()
        self.comfy_service = ComfyUIService(self.config.get("url"))
        self.draw_service = DrawService(context,self.storage,self.tg_mgr,self.comfy_service)

        asyncio.create_task(self.start_listening())

    async def start_listening(self):
        await self.comfy_service.start_listening()

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent):
        event.stop_event()# 暂不考虑事件传播，先一刀切了吧
        configs = self.storage.get_category("core")
        parsed_data = parser.parse_cmd(event.message_str,configs)

        await self.draw_service.handle_draw(event,parsed_data)