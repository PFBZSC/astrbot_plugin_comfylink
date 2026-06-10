from .models import CommandParsedData, InputItem, OutputItem, ParsedResult,ComfyNodeResult
from typing import Optional, List


# from astrbot.api import logger

def parse_cmd(cmd: str, config_list) -> ParsedResult:
    parsed_result = ParsedResult(success=False)

    cmd = cmd.split(maxsplit=1)[1].strip()  # 剥离前缀

    # 1.配置 2.默认参 3.参数1 4.参数2
    if not cmd:
        return parsed_result

    tmp = cmd.split(maxsplit=1)
    _config_name = tmp[0]  # 1.配置
    if len(tmp) != 2:
        parsed_result.success = True
        parsed_result.data = CommandParsedData(config_name=_config_name)
        return parsed_result
    cmd = tmp[1]

    # 解析2.默认参
    _default = ''
    if (i := cmd.find("--")) == -1:
        _default = cmd.strip()
        cmd = ''
    elif i > 1:
        _default = cmd[:i].strip()
        cmd = cmd[i:]
    # 解析3.显式参
    args = [e.split(":", 1) for e in [each.strip() for each in cmd.strip().split('--') if each.strip()]]
    result = parse_data(_config_name, _default, args, config_list)
    if result:
        parsed_result.success = True
        parsed_result.data = result
        return parsed_result

    parsed_result.error_msg = f"找不到名为 '{_config_name}' 的配置。"
    return parsed_result


def parse_data(config_name: str, default: str, args: list, config_list: list) -> Optional[CommandParsedData]:
    parsed_data = CommandParsedData(
        config_name=config_name,
        workflows=""
    )
    # -----解析实际键-----
    # 查找对应配置
    config_json = {}
    for each in config_list:
        if each['commands'] == config_name:
            config_json = each
            parsed_data.workflows = config_json["workflows"]
            break
    if not config_json:
        #没找到配置
        return None

    if (default_key := config_json.get("default", "")) and default:
        args.append([default_key, default])

    arg_dict = {}
    for each in args:
        key, value = each if len(each) == 2 else (each[0], True)
        arg_dict[key] = value

    for each in config_json["inputs_texts"]:
        value = arg_dict.get(each["var_name"], "")
        if value is None: value = ""
        parsed_data.inputs_texts.append(
            InputItem(id=each["id"], key_name=each["key_name"], value=value)
        )

    for each in config_json["inputs_images"]:
        parsed_data.inputs_texts.append(
            InputItem(id=each["id"], key_name=each["key_name"], value="")
        )

    for each in config_json["outputs"]:
        parsed_data.outputs.append(
            OutputItem(id=each["id"], type=each["type"], text=each["text"])
        )

    return parsed_data


def parse_comfy_data(data: CommandParsedData, workflows: dict) -> dict:
    """根据CommandParsedData解析出可发送给ComfyUI的workflows"""
    if not workflows:
        return {}
    for each in data.inputs_texts:
        workflows[each.id]["inputs"][each.key_name] = each.value
    for each in data.inputs_images:
        workflows[each.id]["inputs"][each.key_name] = each.value
    return workflows


if __name__ == "__main__":
    from storage import Storage

    storage = Storage('astrbot_plugin_comfylink', debug=True)
    configs = storage.get_category("core")
    result = parse_cmd("draw zit 提示词", configs)
    # inputs_texts = parse_comfy_data(result["data"])
    # print(inputs_texts)


def parse_node_result(outputs: List[OutputItem], source: dict) -> Optional[ComfyNodeResult]:
    source = source[id := list(source.keys())[0]]  # type:{...}
    node = None
    for each in outputs:
        if each.id == id:
            node = each
            break
    if not node:
        return None
    if node.type == "images":
        # TODO 逻辑优化
        tmp = source["images"][0]
        content = (tmp["filename"], tmp["subfolder"], tmp["type"])
        return ComfyNodeResult(msg_type="images",content = content ,text=node.text)
    elif node.type == "text":
        # TODO 逻辑优化
        tmp = source["text"][0]
        return ComfyNodeResult(msg_type="text",content=tmp,text = node.text)
    return None
