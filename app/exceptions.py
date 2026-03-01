"""
模块名称：自定义异常处理模块
功能描述：定义系统在各层级运行中可能出现的特有异常类，便于主程序捕获与排查。
"""


class MedicalSystemError(Exception):
    """医疗病历系统基础异常基类"""

    pass


class OCRProcessError(MedicalSystemError):
    """感知层：OCR 识别阶段引发的异常"""

    pass


class NERModelError(MedicalSystemError):
    """认知层：NER 模型加载或推理阶段引发的异常"""

    pass


class StorageError(MedicalSystemError):
    """持久层：文件存储或目录创建阶段引发的异常"""

    pass
