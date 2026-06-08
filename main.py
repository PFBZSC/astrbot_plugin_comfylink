from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from .handlers.web_api import WebApiHandler

@register("astrbot_plugin_comfylink", "PFBZSC", "AstrBot联动ComfyUI", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        self.api_service = WebApiHandler(self.context, self.name)
        self.api_service.register()