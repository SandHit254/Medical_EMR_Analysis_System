"""
模块名称：神经认知系统全局异常基类 (Exceptions)
功能描述：定义系统在各层级运行中可能出现的特有异常类，便于主调度器精细化捕获、
         熔断与排查，避免底层报错直接穿透至前端。
"""


class MedicalSystemError(Exception):
    """
    医疗病历系统基础异常基类。
    所有本系统的自定义异常均应继承于此。
    """

    pass


class OCRProcessError(MedicalSystemError):
    """
    感知层异常：在 OCR 识别引擎提取、图像解码或 ONNX 运行时阶段引发的致命错误。
    """

    pass


class NERModelError(MedicalSystemError):
    """
    认知层异常：在 NER 模型加载、张量切片、或 GlobalPointer 推理阶段引发的异常。
    """

    pass


class StorageError(MedicalSystemError):
    """
    持久层异常：文件系统 I/O 读写、快照目录创建或 CDSS 规则序列化阶段引发的异常。
    """

    pass
