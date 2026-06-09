from storage import *

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
            print("无传参")
            result = {"config_name":_config_name}
            return {"success":True,"data":result}
        cmd = tmp[1]

        # 解析2.默认参
        _default = ''
        if (i := cmd.find("--")) == -1:
            _default = cmd[:i].strip()
            cmd = ''
        elif i > 1:
            _default = cmd[:i].strip()
            cmd = cmd[i:]
        # 解析3.显式参
        args = [e.split(":") for e in [each.strip() for each in cmd.strip().split('--') if each.strip()]]
        result = self.parse_data(_config_name,_default,args)
        if result:
            return {"success":True,"data":result}
        else:
            return {"success":False,"data":{}}

    def parse_data(self,config_name:str,default:str,args:list):
        data = {"config_name":config_name,"inputs":[]}
        # -----解析实际键-----
        config_list = self.st.get_category("core")
        # 查找对应配置
        config_json = {}
        for each in config_list:
            if each['commands'] == config_name:
                config_json = each
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
                data["inputs"].append({
                    "id":each["id"],
                    "key_name":each["key_name"],
                    "value":value
                })
            elif value:=each.get("default",""):
                data["inputs"].append({
                    "id": each["id"],
                    "key_name": each["key_name"],
                    "value": each["default"]
                })

        return data


if __name__ == "__main__":
    p = Parser("astrbot_plugin_comfylink",debug=True)
    data = p.parse_cmd("draw zit 提示 词 哦 --cfg:1280")
    print(data)