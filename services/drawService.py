from typing import List

from astrbot.api.event import AstrMessageEvent
from astrbot.core.utils.io import download_image_by_url
from astrbot.api.event import MessageChain
from astrbot.api import logger
from astrbot.core.utils.session_waiter import (session_waiter,SessionController)
from astrbot.api.star import Context

from telegram import Update

from ..telegram.tg_session_controller import TelegramSessionController
from ..utils.parser import ParsedResult, CommandParsedData, InputItem, OutputItem
from ..utils import parser
from ..services.tgManagerService import TelegramManagerService, TelegramInstance
from ..services.comfyUIService import ComfyUIService
from ..utils.storage import Storage


class DrawService:
    def __init__(self,
            context:Context,
            storage:Storage,
            tg_mgr:TelegramManagerService,
            tg_sc:TelegramSessionController,
            comfy_service:ComfyUIService):

        self.context = context
        self.storage = storage
        self.tg_mgr = tg_mgr
        self.tg_sc = tg_sc
        self.parser = parser
        self.comfy_service = comfy_service

        from ..services.tg_draw_handler import TgDrawHandler
        self.tg_handler = TgDrawHandler(
            storage=storage,
            tg_sc=tg_sc,
            comfy_service=comfy_service,
            tg_mgr=tg_mgr,
            draw_service=self,
        )
        self.tg_handler.register()
        self.tg_mgr.register_routes(self)

    # ========== 主入口 路由 ==========
    async def handle_draw(self, event:AstrMessageEvent, parsed_result:ParsedResult):
        if not parsed_result.success:# 指令调用
            await event.send(event.plain_result("输入有误"))
            return

        if parsed_result.data is None:# 无参调用
            if event.get_platform_name() == "telegram":
                # TODO:Telegram
                await self._handle_telegram(event)
            else:
                await event.send(event.plain_result("当前仅支持telegram平台"))

        else:
            await self._handle_standard(event, parsed_result.data)

    # ========== 指令 / 平台 ==========
    async def _handle_standard(self, event:AstrMessageEvent, parsed_data:CommandParsedData):
        # 是否需要上传图片
        if inputs_images := parsed_data.inputs_images:
            # 更新result
            parsed_data.inputs_images = await self._collect_images(event, inputs_images)

        config = self.storage.get_file("workflows", parsed_data.workflows)
        data = self.parser.parse_comfy_data(parsed_data, config)
        listen_node = [each.id for each in parsed_data.outputs]
        logger.info(f"监听节点：{str(listen_node)}")
        await self._execute_and_send(event, data, listen_node, parsed_data.outputs)

    async def _handle_telegram(self, event: AstrMessageEvent):
        """Telegram 交互式流程入口"""
        platform_id = event.get_platform_id()
        if platform_id not in self.tg_mgr:
            await self.tg_mgr.add_inst(event, self.context)
        tg_inst = self.tg_mgr.get(platform_id)
        if tg_inst is None:
            logger.error(f"[DrawService] 无法获取 Telegram 实例: {platform_id}")
            return
        await self.tg_handler.start_flow(event, tg_inst)


    @staticmethod
    async def tg_terminate(_session_id, _data, tg_inst:TelegramInstance, chat_id, message_id):
        await tg_inst.edit(chat_id, message_id, "会话超时")


    # ========== 底层方法 ==========
    async def _collect_images(self, event: AstrMessageEvent, inputs_images: List[InputItem]) -> list:
        """图片上传"""
        img_list = []
        await event.send(event.plain_result(f"请上传图片{len(img_list)+1}"))

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
                    controller.stop()
                else:
                    await event.send(event.plain_result(f"请上传图片{len(img_list)+1}"))
            else:
                await event.send(event.plain_result(f"发送有误，请上传图片{len(img_list)+1}"))
            controller.keep(timeout=60, reset_timeout=True)

        try:
            await upload_waiter(event)
        except TimeoutError as _:  # 当超时后，会话控制器会抛出 TimeoutError
            await event.send(event.plain_result("超时结束"))
            event.stop_event()
        except Exception as e:
            await event.send(event.plain_result("发生错误，请联系管理员: " + str(e)))

        if not img_list or len(img_list) != len(inputs_images):
            # TODO 如果后续要做可选上传图片，需修改
            return []

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
                inputs_images[i].value = res['name']
            except Exception as e:
                logger.error(f"上传图片到 ComfyUI 失败: {str(e)}")

        return inputs_images

    async def _execute_and_send(self, event: AstrMessageEvent, workflows: dict, listen_nodes: list,output_config: List[OutputItem]):
        """最终发送"""
        if not await self.comfy_service.health_check():
            await event.send(event.plain_result("ComfyUI 未启动，请先启动 ComfyUI 再重试"))
            return
        await self.comfy_service.start_listening()
        await event.send(event.plain_result("已将任务提交至ComfyUI"))
        try:
            async for partial_result in self.comfy_service.send(workflows, listen=listen_nodes):
                try:
                    node_res = parser.parse_node_result(output_config, partial_result)
                    if not node_res:
                        continue
                    logger.info(f"解析类型：{node_res.msg_type}")
                    if node_res.msg_type == "images":
                        img = await self.comfy_service.get_image(*node_res.content)
                        if self.storage.save_file('outputs', node_res.content[0], img):
                            if node_res.text.strip():
                                message_chain = MessageChain().message(node_res.text)
                                await self.context.send_message(event.unified_msg_origin, message_chain)
                            message_chain = MessageChain().file_image(str(self.storage.dirs["outputs"] / node_res.content[0]))
                            await self.context.send_message(event.unified_msg_origin, message_chain)
                    elif node_res.msg_type == "text":
                        if node_res.text.strip():
                            content = f"{node_res.text} {node_res.content}"
                        else:
                            content = node_res.content
                        message_chain = MessageChain().message(content)
                        await self.context.send_message(event.unified_msg_origin, message_chain)
                except Exception as e:
                    logger.error(f"处理节点结果时出错: {e}", exc_info=True)
                    # 单节点失败不阻止后续节点
                    continue
        except Exception as e:
            await event.send(event.plain_result(f"ComfyUI 执行出错: {str(e)}"))

    async def _execute_and_send_tg(self, update:Update, workflows: dict, listen_nodes: list,output_config: List[OutputItem]):
        """最终发送"""
        if not await self.comfy_service.health_check():
            await update.effective_sender.send_message("ComfyUI 未启动，请先启动 ComfyUI 再重试")
            return
        await self.comfy_service.start_listening()
        try:
            async for partial_result in self.comfy_service.send(workflows, listen=listen_nodes):
                try:
                    node_res = parser.parse_node_result(output_config, partial_result)
                    if not node_res:
                        continue
                    logger.info(f"解析类型：{node_res.msg_type}")
                    if node_res.msg_type == "images":
                        img = await self.comfy_service.get_image(*node_res.content)
                        if self.storage.save_file('outputs', node_res.content[0], img):
                            if node_res.text.strip():
                                await update.effective_sender.send_message(node_res.text)
                            await update.effective_sender.send_photo(str(self.storage.dirs["outputs"] / node_res.content[0]))
                    elif node_res.msg_type == "text":
                        if node_res.text.strip():
                            content = f"{node_res.text} {node_res.content}"
                        else:
                            content = node_res.content
                        await update.effective_sender.send_message(content)
                except Exception as e:
                    logger.error(f"处理节点结果时出错: {e}", exc_info=True)
                    continue
        except Exception as e:
            await update.effective_sender.send_message(f"ComfyUI 执行出错: {str(e)}")