"""
模块名称：配置管理模块
功能描述：基于单例模式管理全局配置。自动遍历并合并 configs 目录下的所有 JSON 文件，
         为上层业务提供统一的配置读取接口。支持动态热重载机制。
"""

import json
import os


class ConfigManager:
    """
    全局配置管理类（单例模式）。

    负责在系统启动时一次性将所有 JSON 配置文件装载到内存中，并提供统一的读取接口。
    同时提供 reload 方法，支持在不重启 Python 进程的情况下，实现业务规则的热更新。
    """

    _instance = None

    def __new__(cls, config_dir="configs"):
        """
        单例实例化方法。

        确保在整个系统的生命周期内，只存在一个 ConfigManager 实例，
        避免多线程环境下频繁读取磁盘带来的 I/O 开销。

        Args:
            config_dir (str): 存放系统配置文件的相对或绝对目录路径。默认为 "configs"。

        Returns:
            ConfigManager: 全局唯一的配置管理器实例。
        """
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance.config_dir = config_dir
            cls._instance._load_all()
        return cls._instance

    def _load_all(self):
        """
        装载目录下所有的 JSON 配置文件至内存。

        内部方法。遍历 config_dir 目录，将所有 .json 文件的顶级键值对
        合并到自身的 settings 字典中。

        Raises:
            FileNotFoundError: 如果指定的配置文件夹不存在时抛出。
        """
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
            section_name (str): 配置文件中的顶级键名（例如 'ner', 'ocr', 'rules'）。

        Returns:
            dict: 包含该模块对应配置的字典。若指定的键名不存在，则返回空字典 {}。
        """
        return self.settings.get(section_name, {})

    def reload(self):
        """
        触发内存热重载机制。

        清空当前内存中的 settings 字典，并重新扫描读取 configs 目录。
        常用于接收到 Web 端的参数修改请求后，使新规则即时生效，实现 MLOps 持续交付。
        """
        self._load_all()
