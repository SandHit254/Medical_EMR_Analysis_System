"""
模块名称：配置管理模块
功能描述：基于单例模式管理全局配置。自动遍历并合并 configs 目录下的所有 JSON 文件，
         为上层业务提供统一的配置读取接口。
"""

import json
import os


class ConfigManager:
    """配置管理类（单例）"""

    _instance = None

    def __new__(cls, config_dir="configs"):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance.config_dir = config_dir
            cls._instance._load_all()
        return cls._instance

    def _load_all(self):
        """遍历配置目录，加载所有 JSON 文件至内存字典"""
        self.settings = {}
        if not os.path.exists(self.config_dir):
            raise FileNotFoundError(f"配置文件夹缺失: {self.config_dir}")

        for filename in os.listdir(self.config_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(self.config_dir, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        self.settings[key] = value

    def get_section(self, section_name: str) -> dict:
        """
        获取指定模块的配置信息。

        Args:
            section_name (str): 配置节点的键名（如 'rules', 'ner'）。

        Returns:
            dict: 包含该节点所有配置的字典。若键名不存在则返回空字典。
        """
        return self.settings.get(section_name, {})
