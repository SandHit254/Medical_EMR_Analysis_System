"""
模块名称：视觉感知算子 (OCR Engine)
功能描述：封装 RapidOCR 运行时，提供从医学影像或扫描件中提取结构化文本的视觉特征感知能力。
"""

import os
from rapidocr_onnxruntime import RapidOCR
from app.config_manager import ConfigManager
from app.exceptions import OCRProcessError


class OCREngine:
    """图像文本多模态感知类"""

    def __init__(self):
        """
        初始化 OCR 视觉引擎。
        自动挂载 ConfigManager，热加载预处理参数（如文字方向分类器策略）。
        """
        cfg = ConfigManager().get_section("ocr")
        self.engine = RapidOCR(use_angle_cls=cfg.get("use_angle_cls", True))

    def extract(self, image_path: str) -> str:
        """
        执行图像到文本的张量提取。

        Args:
            image_path (str): 图像的绝对物理路径。

        Returns:
            str: 提取出的全部文本，默认以全角逗号拼接为连续长文本。

        Raises:
            FileNotFoundError: 文件系统寻址失败。
            OCRProcessError: ONNX 运行时或底层 C++ 算子执行崩溃。
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(
                f"视觉感知管线阻断：目标图像路径缺失 [{image_path}]"
            )

        try:
            # 唤醒底层算子进行推理
            result, _ = self.engine(image_path)

            if result:
                # 提取矩阵块的第二维度（文本内容）并安全拼接
                return "，".join([res[1] for res in result])

            return ""

        except Exception as e:
            raise OCRProcessError(f"底层 OCR 推理算子崩溃，明细: {str(e)}")
