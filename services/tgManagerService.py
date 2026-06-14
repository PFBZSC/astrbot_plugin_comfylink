from __future__ import annotations

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context
from astrbot.core.platform.sources.telegram.tg_adapter import TelegramPlatformAdapter
from astrbot.api import logger

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler,ContextTypes

from ..utils.tg_decorators import get_pending_callbacks

class TelegramManagerService:
    """Telegram实例管理器"""
    def __init__(self):
        self.tg_insts:dict[str,TelegramInstance] = {} # platform_id : TelegramInstance
        self.callback_routes = {} # { command : ( instance, method ) }

    def register_routes(self, instance):
        """
        全能注册器：支持手动传入任何实例（包括 main.py 的 self）
        具备穿透框架装饰器、解包 Bound Method 的能力
        """

        pending_callbacks = get_pending_callbacks()

        # 统一获取底层的类对象，用来做最稳妥的源码级函数映射
        cls = instance.__class__

        for attr_name in dir(instance):
            try:
                # 优先从“类（Class）”而非“实例（Instance）”中提取原始函数符号
                # 这样可以完美避开实例绑定（Bound Method）导致的哈希值不一致问题
                raw_attr = getattr(cls, attr_name, None)
                if not raw_attr:
                    raw_attr = getattr(instance, attr_name)

                if not callable(raw_attr):
                    continue

                # 如果方法被 @filter.command 装饰，AstrBot 会将其包装
                underlying_func = raw_attr
                while hasattr(underlying_func, "__wrapped__"):
                    underlying_func = getattr(underlying_func, "__wrapped__")

                # 兜底处理常规 Bound Method
                if hasattr(underlying_func, "__func__"):
                    underlying_func = underlying_func.__func__

                # 进行哈希匹配
                if underlying_func in pending_callbacks:
                    command = pending_callbacks[underlying_func]

                    # 运行期分发需要绑定实例的方法
                    bound_method = getattr(instance, attr_name)
                    self.callback_routes[command] = (instance, bound_method)
                    logger.info(
                        f"[TelegramManager] 成功在 {instance.__class__.__name__} 中捕获并注册回调命令 -> {command} (映射至 .{attr_name})")

            except (AttributeError, TypeError):
                continue

    def add_inst(self,event:AstrMessageEvent,context:Context) -> TelegramInstance|None:
        platform_id = event.get_platform_id()

        if self.tg_insts.get(platform_id,None):
            logger.warn(f"[TelegramManagerService] platform_id:{platform_id} 的TelegramInstance已存在，已避免重复创建")
            return self.tg_insts[platform_id]

        platform = context.get_platform_inst(platform_id)
        if not isinstance(platform, TelegramPlatformAdapter):
            logger.error(f"[TelegramManagerService] platform_id:{platform_id} 不是TelegramPlatformAdapter")
            return None


        #实例化TelegramInstance
        self.tg_insts[platform_id] = TelegramInstance(platform_id,platform,self)
        logger.info(f"[TelegramManagerService] 已创建platform_id:{platform_id} TelegramInstance实例化")
        return self.tg_insts[platform_id]

    def terminate(self):
        self._del_all_inst()
        self._clear_routes()

    def del_inst(self,platform_id):
        instance = self.tg_insts.get(platform_id,None)
        if not instance:
            logger.warn(f"[TelegramManagerService] 未找到platform_id:{platform_id} 的TelegramInstance实例化")
            return
        instance.remove_handler()
        del self.tg_insts[platform_id]
        logger.info(f"[TelegramManagerService] 已移除platform_id:{platform_id} 的TelegramInstance实例化")

    def _del_all_inst(self):
        platform_list = list(self.tg_insts.keys())
        for platform_id in platform_list:
            self.del_inst(platform_id)
        self.tg_insts.clear()

    def _clear_routes(self):
        self.callback_routes.clear()

    def __getitem__(self, item) -> TelegramInstance:
        return self.tg_insts[item]

    def __contains__(self, platform_id) -> bool:
        return platform_id in self.tg_insts

class TelegramInstance:
    """单个Telegram Bot实例"""
    def __init__(self,platform_id:str,adapter: TelegramPlatformAdapter,mgr:TelegramManagerService):
        self.platform_id = platform_id
        self.adapter = adapter
        self.mgr = mgr
        if getattr(self.adapter,"_patched_from_telegramManagerService",False):
            self.client = adapter.get_client()
            logger.info("[TelegramInstance] 已添加CallbackQueryHandler，跳过重复添加")
            return

        self.adapter._patched_from_telegramManagerService = True # 加上标识避免重复添加handler
        self.handler_ref = CallbackQueryHandler(self._handle_callback)
        self.adapter.application.add_handler(self.handler_ref)
        logger.info("[TelegramInstance] 成功添加CallbackQueryHandler")
        self.client = adapter.get_client()

    def remove_handler(self):
        if not getattr(self.adapter,"_patched_from_telegramManagerService",False):
            logger.warn("[TelegramInstance] CallbackQueryHandler已经被卸载")
            return
        self.adapter.application.remove_handler(self.handler_ref)
        delattr(self.adapter, "_patched_from_telegramManagerService")
        logger.warn("[TelegramInstance] 成功卸载CallbackQueryHandler")


    async def send(self,chat_id,text:str,reply_markup:InlineKeyboardMarkup|None=None) -> int|bool:
        sent_message = await self.client.send_message(chat_id=chat_id,text = text,reply_markup=reply_markup)
        return sent_message.message_id

    async def edit(self,chat_id,message_id,text:str,reply_markup:InlineKeyboardMarkup|None=None) -> int|bool:
        sent_message = await self.client.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=reply_markup)
        return getattr(sent_message,"message_id",False)


    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("触发_handle_callback")
        query = update.callback_query
        data:str|None = getattr(query,"data",None)
        if not (data and ":" in data):
            return

        command,value = data.split(":",1)
        if command in self.mgr.callback_routes:
            instance, method = self.mgr.callback_routes[command]
            try:
                await method(update,context,value)
            except Exception as e:
                logger.error(f"[TelegramManager] 执行回调 {command}:{value} 失败: {e}")
                await query.answer()
        else:
            logger.warn(f"[TelegramManager] 执行回调 {command}:{value} 被忽略")
        await query.answer()

