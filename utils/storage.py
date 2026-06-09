import json
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from pathlib import Path


class Storage:
    def __init__(self, name,debug=False):
        self.name = name

        # 初始化持久化存储目录
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / name

        if debug:
            self.data_dir = Path(get_astrbot_data_path()).parents[3] / "plugin_data" / name
            print(self.data_dir)

        self.dirs = {
            "core": self.data_dir / "configs",
            "prompt": self.data_dir / "prompt",
            "telegram": self.data_dir / "telegram",
            "workflows": self.data_dir / "workflows"
        }

        # 确保目录存在
        for p in self.dirs.values():
            p.mkdir(parents=True, exist_ok=True)

    def get_all(self):
        """加载所有目录下的 JSON 数据"""
        result = {"core": [], "prompt": [], "telegram": [], "workflows": {}}

        for category, dir_path in self.dirs.items():
            for file_path in dir_path.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if category == "workflows":
                            # workflows 使用文件名作为 key
                            result["workflows"][file_path.name] = data
                        else:
                            result[category].append(data)
                except Exception as e:
                    # 遇到损坏的 json 直接跳过，避免中断整个读取过程
                    continue

        return result

    def save_item(self, category: str, filename: str, data: dict) -> bool:
        """保存单条 JSON 数据"""
        if category not in self.dirs:
            return False

        file_path = self.dirs[category] / filename
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def delete_item(self, category: str, filename: str) -> bool:
        """删除单条 JSON 数据"""
        if category not in self.dirs:
            return False

        file_path = self.dirs[category] / filename
        if file_path.exists():
            try:
                file_path.unlink()
                return True
            except Exception:
                return False
        return False

    def get_category(self, category: str):
        """获取指定分类目录下的所有 JSON 数据"""
        if category not in self.dirs:
            return None

        result = {} if category == "workflows" else []
        dir_path = self.dirs[category]
        for file_path in dir_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if category == "workflows":
                        result[file_path.name] = data
                    else:
                        result.append(data)
            except Exception:
                continue
        return result

    def get_file(self, category: str, filename: str):
        """获取指定分类目录下的单个 JSON 文件数据"""
        if category not in self.dirs:
            return None

        file_path = self.dirs[category] / filename
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

if __name__ == "__main__":
    st = Storage("astrbot_plugin_comfylink",debug=True)