from typing import List,Dict,Any,Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def keyboard_build(choices: List[Tuple[str, Any]], command: str, row_width: int = 1) -> InlineKeyboardMarkup:
    """
    构建 InlineKeyboardMarkup
    callback_data 格式为 -> command:choice
    """
    buttons = [
        InlineKeyboardButton(text=text, callback_data=f"{command}:{data}")
        for text, data in choices
    ]

    # 按照指定的 row_width 分组，默认每行一个按钮
    keyboard = [buttons[i:i + row_width] for i in range(0, len(buttons), row_width)]

    return InlineKeyboardMarkup(keyboard)

