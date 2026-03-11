"""
模块名称：全局配置中枢模块 (Config Manager)
功能描述：基于线程安全的单例模式管理全局配置。自动遍历合并 configs 目录下的所有 JSON 文件，
         为上层神经算子提供统一的参数注入，支持 MLOps 级别的动态热重载机制。
"""

import os
import json
import threading
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    全局配置管理类（线程安全单例模式）。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """
        线程安全的单例实例化方法。

        Returns:
            ConfigManager: 全局唯一的配置管理器实例。
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)

                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                cls._instance.config_dir = os.path.join(base_dir, "configs")
                cls._instance._load_all()

        return cls._instance

    def _load_all(self):
        """
        I/O 装载算子。
        遍历 configs 目录，将所有 .json 文件的顶级键值对序列化并加载至内存树中。

        Raises:
            FileNotFoundError: 如果配置目录丢失则触发阻断。
        """
        self.settings = {}
        if not os.path.exists(self.config_dir):
            raise FileNotFoundError(f"致命阻断：配置文件夹缺失: {self.config_dir}")

        for filename in os.listdir(self.config_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(self.config_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for key, value in data.items():
                            self.settings[key] = value
                except json.JSONDecodeError as e:
                    logger.error(f"解析配置文件 {filename} 失败: {str(e)}")

    def get_section(self, section_name: str) -> dict:
        """
        配置分发接口。

        Args:
            section_name (str): 配置文件中的顶级节点（如 'ner', 'ocr', 'rules'）。

        Returns:
            dict: 包含该模块对应配置的字典快照。
        """
        return self.settings.get(section_name, {})

    def reload(self):
        """
        触发内存热重载机制 (Hot-Reload)。
        由 Web 端的保存操作触发，无需重启 Python 进程即可将最新参数同步至各推理管线。
        """
        logger.info("执行配置中心热重载...")
        self._load_all()
