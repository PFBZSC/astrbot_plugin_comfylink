from .storage import *
from astrbot.api import logger

class Parser:
    def __init__(self,name:str,debug = False):
        self.name = name
        self.st = Storage(name,debug = debug)

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
        return config

if __name__ == "__main__":
    p = Parser("astrbot_plugin_comfylink",debug=True)
    result = p.parse_cmd("draw zit 提示词")
    inputs_texts = p.parse_comfy_data(result["data"])
    print(inputs_texts)