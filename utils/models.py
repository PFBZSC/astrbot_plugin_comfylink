from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class InputItem(BaseModel):
    id: str
    key_name: str
    value: str = ""

class OutputItem(BaseModel):
    id: str
    type: str  # "text" | "images"
    text: str = ""

class CommandParsedData(BaseModel):
    config_name: str
    workflows: str = ""
    inputs_texts: List[InputItem] = Field(default_factory=list)
    inputs_images: List[InputItem] = Field(default_factory=list)
    outputs: List[OutputItem] = Field(default_factory=list)

class ParsedResult(BaseModel):
    success: bool
    data: Optional[CommandParsedData] = None
    error_msg: Optional[str] = None


class ComfyNodeResult(BaseModel):
    msg_type: str = ""        # "images" | "text" | "error"
    content: Any         # 存放图片元组或文本字符串
    text: str = "" # 前缀文本