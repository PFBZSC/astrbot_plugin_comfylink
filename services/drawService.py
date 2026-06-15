from typing import List
from functools import partial
import asyncio

from astrbot.api.event import AstrMessageEvent
from astrbot.core.utils.io import download_image_by_url
from astrbot.api.event import MessageChain
from astrbot.api import logger
from astrbot.core.utils.session_waiter import (session_waiter,SessionController)
from astrbot.api.star import Context

from telegram import Update
from telegram.ext import ContextTypes

from ..telegram.tg_session_controller import TelegramSessionController
from ..utils.parser import ParsedResult, CommandParsedData, InputItem, OutputItem
from ..utils import parser
from ..utils.tg_inline_builder import keyboard_build
from ..services.tgManagerService import TelegramManagerService, TelegramInstance
from ..services.comfyUIService import ComfyUIService
from ..utils.storage import Storage
from ..utils.tg_decorators import tg_callback


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
        # 获取实例
        platform_id = event.get_platform_id()
        if not platform_id in self.tg_mgr:
            self.tg_mgr.add_inst(event,self.context)
        tg_inst = self.tg_mgr[platform_id]

        # command:user_input:session_id
        tg_config_list = self.storage.get_category("telegram")
        if not tg_config_list:
            await tg_inst.send(event.get_session_id(), "后台未配置工作流")
            return

        # 创建tg_session
        session_id = self.tg_sc.create_session(timeout=60)
        self.tg_sc.get_data(session_id)["event"] = event
        # get_tg_config:name:session_id
        choices = [(each['name'],f"get_tg_config:{each['name']}:{session_id}") for each in tg_config_list]
        reply_markup = keyboard_build(choices,"tg_draw",3)

        msg_id = await tg_inst.send(event.get_session_id(),"选择工作流：",reply_markup=reply_markup)
        bound_callback = partial(self.tg_terminate,tg_inst=tg_inst,chat_id=event.get_session_id(),message_id=msg_id)
        self.tg_sc.update_callback(session_id, bound_callback)


    @tg_callback("tg_draw")
    async def tg_draw(self,update:Update,_context: ContextTypes.DEFAULT_TYPE,value:str):
        # 输入拆解
        logger.info(f"tg_draw收到字符串:{value}")
        command,user_input,session_id = value.split(":")
        data = self.tg_sc.get_data(session_id)
        if data is None:
            # 超时
            logger.error(f"获取不到session_id:{session_id},可能已经超时或未被注册")
            await update.effective_sender.send_message("选择无效")
            return
        # 重置计时器
        await self.tg_sc.reset_timer(session_id)


        if command == "get_tg_config":
            # TODO 后续抽离专门负责解析telegram配置
            # tg_config_name,tg_config,core,workflows
            data["tg_config_name"] = user_input
            tg_config_list = self.storage.get_category("telegram")

            config = {}
            for each in tg_config_list:
                if each.get("name") == user_input:
                    config = each
            data["tg_config"] = config
            if not config:
                await self.tg_sc.close_session(session_id)
                await update.callback_query.edit_message_text("获取配置时出现错误：未找到tg_config")
                return
            # 通过core_id获取core配置
            if (core_id := config.get("core_id")) is None:
                await self.tg_sc.close_session(session_id)
                await update.callback_query.edit_message_text("获取配置时出现错误：未找到tg_config中core_id")
                return

            data["core"] = self.storage.get_file("core",f"{core_id}.json")

            if (workflows := data["core"].get("workflows")) is None:
                await self.tg_sc.close_session(session_id)
                await update.callback_query.edit_message_text("获取配置时出现错误：未找到config中workflows")
                return
            data["workflows"] = self.storage.get_file("workflows",workflows)
            command = "send_setting"

        if command == "get_setting":
            var_name,var_value = user_input.split("=")
            if var_name and var_value:
                if data.get("var_list") is None:
                    data["var_list"] = []
                data["var_list"].append([var_name,var_value])
            command = "send_setting"

        if command == "send_setting":
            # 读取问询配置
            if data["tg_config"]["dialog"]:
                dialog = data["tg_config"]["dialog"].pop(0)
                text = dialog["text"]
                # TODO can_input需要注册多轮对话
                # can_input = first_dialog["can_input"]
                # get_tg_config:varname=value:session_id
                choices = [(each["name"], f"get_setting:{each["var_name"]}={each["value"]}:{session_id}") for each in
                           dialog["option"]]
                reply_markup = keyboard_build(choices, "tg_draw", 3)
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
                return
            else:
                command = "send_prompt_1"

        if command[:-2] == "get_prompt":
            stage = command.split("_")[-1]
            if stage == "1":
                data["input_prompt"] = data["system_prompt"].get("framework")[int(user_input)]["text"]
                command = f"send_prompt_{int(stage) + 1}"
            elif stage == "2":
                data["input_prompt"] = parser.smart_format(data["input_prompt"],data["system_prompt"].get("description")[int(user_input)]["text"])
                command = f"send_prompt_{int(stage) + 1}"
            elif data["system_prompt"]["trigger"]:
                trigger = data["system_prompt"]["trigger"].pop(int(user_input))
                data["input_prompt"] = parser.smart_format(data["input_prompt"],trigger["text"])
                command = f"send_prompt_{int(stage) + 1}"
            else:
                command = "parse"

        if command[:-2] == "send_prompt":
            stage = command.split("_")[-1]
            if data.get("system_prompt") is None:
                data["system_prompt"] = self.storage.get_file("prompt", "system.json")
            text = ""
            if stage == "1" and (stage_prompt := data["system_prompt"].get("framework")):
                text = "选择提示词框架："
            elif stage == "2" and (stage_prompt := data["system_prompt"].get("description")):
                text = "选择提示词描述："
            elif stage_prompt := data["system_prompt"].get("trigger"):
                text = "选择提示词触发词："
            if text:
                # get_prompt_X:index:session_id
                choices = [(stage_prompt[i]["name"], f"get_prompt_{stage}:{i}:{session_id}") for i in
                           range(len(stage_prompt))]
                choices.append(("跳过", f"parse::{session_id}"))
                reply_markup = keyboard_build(choices, "tg_draw", 3)
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            else:
                command = "parse"

        if command == "parse":
            core = data.get("core")
            workflows = data.get("workflows")
            var_list = data.get("var_list")
            prompt = data.get("input_prompt")
            parsed_data = parser.parse_data(core["commands"],prompt,var_list,[core])
            if parsed_data:
                listen_node = [each.id for each in parsed_data.outputs]

                # 是否需要上传图片
                if inputs_images := parsed_data.inputs_images:
                    await update.callback_query.edit_message_text("参数记录完毕")
                    event = data["event"]
                    await self.tg_sc.close_session(session_id)

                    # 放入后台任务防阻塞
                    async def process_and_send():
                        # 1. 先收集图片，这会更新 inputs_images 里对象的值为 ComfyUI 返回的文件名
                        final_images = await self._collect_images(event, inputs_images)
                        if not final_images:
                            return
                        parsed_data.inputs_images = final_images

                        # 2. 【核心修复】必须在图片收集并赋值完成后，再将数据装配进工作流
                        final_workflows = parser.parse_comfy_data(parsed_data, workflows)

                        logger.info(f"监听节点：{str(listen_node)}")
                        logger.info(core)
                        logger.info(parsed_data)
                        await self._execute_and_send_tg(update, final_workflows, listen_node, parsed_data.outputs)

                    asyncio.create_task(process_and_send())
                else:
                    # 如果不需要发图，直接装配并执行
                    final_workflows = parser.parse_comfy_data(parsed_data, workflows)
                    logger.info(f"监听节点：{str(listen_node)}")
                    await self._execute_and_send_tg(update, final_workflows, listen_node, parsed_data.outputs)
            else:
                await update.callback_query.edit_message_text("解析时出现错误")


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
        await event.send(event.plain_result("已将任务提交至ComfyUI"))
        async for partial_result in self.comfy_service.send(workflows, listen=listen_nodes):
            # 这里的 partial_result 就是单个节点的产物，例如: {"9": {"images": [...]}}
            # 收到一个，就立刻给用户发一条消息
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

    async def _execute_and_send_tg(self, update:Update, workflows: dict, listen_nodes: list,output_config: List[OutputItem]):
        """最终发送"""
        async for partial_result in self.comfy_service.send(workflows, listen=listen_nodes):
            # 这里的 partial_result 就是单个节点的产物，例如: {"9": {"images": [...]}}
            # 收到一个，就立刻给用户发一条消息
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