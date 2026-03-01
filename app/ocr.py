"""
模块名称：光学字符识别 (OCR) 引擎模块
功能描述：封装 RapidOCR 库，提供从医学影像或扫描件中提取结构化文本的接口。
"""

import os
from rapidocr_onnxruntime import RapidOCR
from app.config_manager import ConfigManager


class OCREngine:
    """图像文本感知类"""

    def __init__(self):
        """
        初始化 OCR 引擎。
        自适应读取全局配置中的引擎参数（如方向分类器开关）。
        """
        cfg = ConfigManager().get_section("ocr")
        self.engine = RapidOCR(use_angle_cls=cfg.get("use_angle_cls", True))

    def extract(self, image_path: str) -> str:
        """
        从目标图像中提取文本信息。

        Args:
            image_path (str): 图像的绝对或相对文件路径。

        Returns:
            str: 提取出的全部文本，以全角逗号分隔各检测框的内容。

        Raises:
            FileNotFoundError: 当指定的图像路径不存在时抛出。
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"指定的图像路径不存在: {image_path}")

        result, _ = self.engine(image_path)

        if result:
            # result 结构中，第二个元素为提取的文本内容
            return "，".join([res[1] for res in result])

        return ""
