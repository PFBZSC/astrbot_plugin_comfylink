import asyncio

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig


from .handlers.web_api import WebApiHandler
from .utils.parser import Parser
from .services.comfyUIService import ComfyUIService

@register("astrbot_plugin_comfylink", "PFBZSC", "AstrBot联动ComfyUI", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.api_service = WebApiHandler(self.context, self.name)
        self.api_service.register()

        self.parser = Parser(self.name)
        self.comfy_service = ComfyUIService(self.config.get("url"))

        asyncio.create_task(self.start_listening())

    async def start_listening(self):
        await self.comfy_service.start_listening()

    @filter.command("draw")
    async def draw(self, event: AstrMessageEvent):
        result = self.parser.parse_cmd(event.message_str)
        if result == {'success': True, 'data': {}}:# 无参调用
            if event.get_platform_name() == "telegram":
                # TODO:Telegram
                pass
            yield event.plain_result("无参调用")

        elif result["success"]:# 指令调用
            data = self.parser.parse_comfy_data(result["data"])

            # TODO 图片上传
            # inputs_images = result["data"]["inputs_images"]

            listen = [each["id"] for each in result["data"]["outputs"]]

            result = await self.comfy_service.send(data, listen=listen)

            yield event.plain_result(str(data))
            yield event.plain_result(str(result))

        else:
            yield event.plain_result("输入有误")