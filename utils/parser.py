from .storage import Storage
# from astrbot.api import logger


def parse_result(outputs:list[dict], source:dict):
    source = source[ id := list(source.keys())[0]] # type:{...}
    conf = {} # id type text
    for each in outputs:
        if each["id"] == id:
            conf = each
            break
    if not conf:
        return None,None,None
    if conf.get("type") == "images":
        # TODO 逻辑优化
        tmp = source["images"][0]
        return "images",(tmp["filename"], tmp["subfolder"], tmp["type"]),conf.get('text', "")
    elif conf.get("type") == "text":
        # TODO 逻辑优化
        tmp = source["text"][0]
        return "text",tmp,conf.get('text', "")
    return None,None,None

class Parser:
    def __init__(self,name:str,storage: Storage):
        self.name = name
        self.st = storage

    def parse_cmd(self,cmd:str):
        cmd = cmd[4:].strip() # 剥离前缀

        # 1.配置 2.默认参 3.参数1 4.参数2
        if not cmd:
            return {"success":True,"data":{}}

        tmp = cmd.split(maxsplit=1)
        _config_name = tmp[0] # 1.配置
        if len(tmp) != 2:
            result = {"config_name":_config_name}
            return {"success":True,"data":result}
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
        args = [e.split(":",1) for e in [each.strip() for each in cmd.strip().split('--') if each.strip()]]
        result = self.parse_data(_config_name,_default,args)
        if result:
            return {"success":True,"data":result}
        else:
            return {"success":False,"data":{}}

    def parse_data(self,config_name:str,default:str,args:list):
        data = {"config_name":config_name,"workflows":"","inputs_texts":[],"inputs_images":[],"outputs":[]}
        # -----解析实际键-----
        config_list = self.st.get_category("core")
        # 查找对应配置
        config_json = {}
        for each in config_list:
            if each['commands'] == config_name:
                config_json = each
                data["workflows"] = config_json["workflows"]
                break
        if not config_json:
            #没找到配置
            return {}

        if (default_key := config_json.get("default", "")) and default:
            args.append([default_key,default])

        arg_dict = {}
        for each in args:
            key,value = each if len(each) == 2 else (each[0], True)
            arg_dict[key] = value

        for each in config_json["inputs_texts"]:
            if value:=arg_dict.get(each["var_name"],""):
                data["inputs_texts"].append({
                    "id":each["id"],
                    "key_name":each["key_name"],
                    "value":value
                })
            elif each.get("default",""):
                data["inputs_texts"].append({
                    "id": each["id"],
                    "key_name": each["key_name"],
                    "value": each["default"]
                })


        for each in config_json["inputs_images"]:
            data["inputs_images"].append({
                "id":each["id"],
                "key_name":each["key_name"],
                "value":""
            })

        for each in config_json["outputs"]:
            data["outputs"].append({
                "id":each["id"],
                "type":each["type"],
                "text":each["text"]
            })



        return data

    def parse_comfy_data(self, data:list):
        config = self.st.get_file("workflows",data["workflows"])
        if not config:
            return {}
        for each in data["inputs_texts"]:
            config[each["id"]]["inputs"][each["key_name"]] = each["value"]
        for each in data["inputs_images"]:
            config[each["id"]]["inputs"][each["key_name"]] = each["value"]
        return config

if __name__ == "__main__":
    p = Parser("astrbot_plugin_comfylink",Storage('astrbot_plugin_comfylink',debug=True))
    result = p.parse_cmd("draw zit 提示词")
    inputs_texts = p.parse_comfy_data(result["data"])
    print(inputs_texts)