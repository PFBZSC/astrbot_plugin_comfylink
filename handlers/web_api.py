from astrbot.api.star import Context
from quart import request, jsonify
from ..utils.storage import Storage


class WebApiHandler:
    def __init__(self, context: Context, plugin_name: str,storage:Storage):
        self.context = context
        self.name = plugin_name
        self.st = storage

    def register(self):
        # 统一注册Api
        # (将原有的 get_item 替换为更符合前端需求的 get_all)
        self.context.register_web_api(f"/{self.name}/get_all", self.get_all, ["GET"], "获取所有数据")
        self.context.register_web_api(f"/{self.name}/save_item", self.save_item, ["POST"], "保存单条数据")
        self.context.register_web_api(f"/{self.name}/delete_item", self.delete_item, ["POST"], "删除单条数据")

    async def get_all(self):
        # 获取全部数据返回给前端
        data = self.st.get_all()
        return jsonify(data)

    async def save_item(self):
        req = await request.get_json()
        if req is None:
            return jsonify({"error": "请求体不能为空"}), 400
        category = req.get("category")
        filename = req.get("filename")
        data = req.get("data")

        if self.st.save_item(category, filename, data):
            return jsonify({"status": "ok"})
        return jsonify({"error": "保存失败或参数不正确"}), 400

    async def delete_item(self):
        req = await request.get_json()
        if req is None:
            return jsonify({"error": "请求体不能为空"}), 400
        category = req.get("category")
        filename = req.get("filename")

        if self.st.delete_item(category, filename):
            return jsonify({"status": "ok"})
        return jsonify({"error": "删除失败或文件不存在"}), 400