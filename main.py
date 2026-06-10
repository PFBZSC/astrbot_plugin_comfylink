import asyncio
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger,AstrBotConfig
from astrbot.core.utils.io import download_image_by_url
from astrbot.api.event import MessageChain

from .handlers.web_api import WebApiHandler
from .utils.parser import Parser,parse_result
from .utils.storage import Storage

from .services.comfyUIService import ComfyUIService
from astrbot.core.utils.session_waiter import (session_waiter,SessionController)

@register("astrbot_plugin_comfylink", "PFBZSC", "AstrBot联动ComfyUI", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context,config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.storage = Storage(self.name)

        self.api_service = WebApiHandler(self.context, self.name,self.storage)
        self.api_service.register()


        self.parser = Parser(self.name,self.storage)

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

        elif not result["success"]:# 指令调用
            yield event.plain_result("输入有误")
            return

        if inputs_images := result["data"]["inputs_images"]:
            # 图片上传
            img_list = []
            yield event.plain_result(f"请上传图片{len(img_list)+1}")

            @session_waiter(timeout=60, record_history_chains=False)
            async def upload_waiter(controller: SessionController, event: AstrMessageEvent):
                user_input = event.get_messages()

                if user_input[0].type == "Plain" and user_input[0].toDict()["data"]["text"] == "/stop":
                    # 终止
                    await event.send(event.plain_result("已提前终止"))
                    controller.stop()
                    return
                elif user_input[0].type == "Image":
                    img_list.append(user_input[0].path if user_input[0].path else user_input[0].url)
                    if len(img_list) >= len(inputs_images):
                        await event.send(event.plain_result("记录完毕"))
                        controller.stop()
                    else:
                        await event.send(event.plain_result(f"请上传图片{len(img_list)+1}"))
                else:
                    await event.send(event.plain_result(f"发送有误，请上传图片{len(img_list)+1}"))
                controller.keep(timeout=60, reset_timeout=True)

            try:
                await upload_waiter(event)
            except TimeoutError as _:  # 当超时后，会话控制器会抛出 TimeoutError
                yield event.send(event.plain_result("超时结束"))
            except Exception as e:
                yield event.plain_result("发生错误，请联系管理员: " + str(e))
            finally:
                event.stop_event()

            if len(img_list) != len(inputs_images):
                return
            for i in range(len(img_list)):
                img_url_or_path = img_list[i].strip()
                img = None
                if img_url_or_path.lower().startswith('http'):
                    try:
                        img_path = await download_image_by_url(img_url_or_path)
                        img = self.storage.get_temp_img(img_path)
                    except Exception as e:
                        logger.error(f"下载图片发生异常: {str(e)}, URL: {img_url_or_path}")
                else:
                    try:
                        img = self.storage.get_temp_img(img_url_or_path)
                    except Exception as e:
                        logger.error(f"获取本地缓存图片失败: {str(e)}, 路径: {img_url_or_path}")

                if img is None:
                    logger.warning(f"第 {i + 1} 张图片数据为空，跳过上传。")
                    continue

                try:
                    # 上传 comfyui
                    res = await self.comfy_service.upload_image(img)
                    logger.info(f"成功上传第 {i + 1} 张图片，ComfyUI 服务端文件名: {res['name']}")
                    inputs_images[i]["value"] = res['name']
                except Exception as e:
                    logger.error(f"上传图片到 ComfyUI 失败: {str(e)}")
            # 更新result
            result["data"]["inputs_images"] = inputs_images

        data = self.parser.parse_comfy_data(result["data"])
        listen = [each["id"] for each in result["data"]["outputs"]]
        logger.info(f"监听节点：{str(listen)}")
        umo = event.unified_msg_origin
        async for partial_result in self.comfy_service.send(data, listen=listen):
            # 这里的 partial_result 就是单个节点的产物，例如: {"9": {"images": [...]}}
            # 收到一个，就立刻给用户发一条消息
            msg_type,result_data,text = parse_result(result["data"]["outputs"],partial_result)
            if msg_type == "images":
                img = await self.comfy_service.get_image(*result_data)
                if self.storage.save_file('outputs',result_data[0],img):
                    if text.strip():
                        message_chain = MessageChain().message(text)
                        await self.context.send_message(event.unified_msg_origin, message_chain)
                    message_chain = MessageChain().file_image(str(self.storage.dirs["outputs"] / result_data[0]))
                    await self.context.send_message(event.unified_msg_origin, message_chain)
            elif msg_type == "text":
                if text.strip():
                    result_data = f"{text} {result_data}"
                message_chain = MessageChain().message(result_data)
                await self.context.send_message(event.unified_msg_origin, message_chain)