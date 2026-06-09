from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from .handlers.web_api import WebApiHandler
from .utils.parser import Parser

@register("astrbot_plugin_comfylink", "PFBZSC", "AstrBot联动ComfyUI", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        self.api_service = WebApiHandler(self.context, self.name)
        self.api_service.register()

        self.parser = Parser(self.name)
        self.comfy_service = ComfyUIService(self.config['url'])

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent):
        result = self.parser.parse_cmd(event.message_str)
        if result == {'success': True, 'data': {}}:
            if event.get_platform_name() == "telegram":
                # TODO:Telegram
                pass
            yield event.plain_result("TODO:TG")
        elif result["success"]:
            # TODO:Send to ComfyUIService
            yield event.plain_result("TODO:Send")
        else:
            yield event.plain_result("输入有误")