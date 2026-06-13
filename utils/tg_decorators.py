import functools

# 内存临时注册表：{函数引用: "command_name"}
_pending_callbacks = {}


def tg_callback(command: str):
    """
    Telegram 内联键盘回调装饰器
    用法:
        @tg_callback("draw")
        async def handle_draw_click(self, update, context, action):
    """

    def decorator(func):
        # 记录函数的所属 command 名字
        _pending_callbacks[func] = command

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def get_pending_callbacks():
    """获取待绑定的回调函数字典"""
    return _pending_callbacks