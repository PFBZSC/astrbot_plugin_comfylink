import asyncio

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig
import astrbot.api.message_components as Comp


from .handlers.web_api import WebApiHandler
from .utils.parser import Parser,parse_result
from .utils.storage import Storage

from .services.comfyUIService import ComfyUIService

@register("astrbot_plugin_comfylink", "PFBZSC", "AstrBot联动ComfyUI", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.api_service = WebApiHandler(self.context, self.name)
        self.api_service.register()

        self.parser = Parser(self.name)
        self.st = Storage(self.name)
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
            yield event.plain_result("提交成功")


            try:
                async for partial_result in self.comfy_service.send(data, listen=listen):
                    # 这里的 partial_result 就是单个节点的产物，例如: {"9": {"images": [...]}}
                    # 收到一个，就立刻给用户发一条消息
                    result_data,text = parse_result(result["data"]["outputs"],partial_result)
                    img = await self.comfy_service.get_image(*result_data)
                    if self.st.save_file('outputs',result_data[0],img):
                        if text.strip():
                            yield event.plain_result(f"{text}")
                        logger.info(self.st.dirs["outputs"] / result_data[0])
                        chain = [Comp.Image.fromFileSystem(str(self.st.dirs["outputs"] / result_data[0]))]
                        yield event.chain_result(chain)
            except Exception as e:
                yield event.plain_result(f"执行异常: {e}")

        else:
            yield event.plain_result("输入有误")