"""
模块名称：病历分析系统主入口
功能描述：作为系统的主调度器，负责初始化配置模块、构建业务流管线，
         管理各处理层之间的参数流转并负责最外层异常捕获与抛出。
"""

import os
import uuid
import logging
import traceback
from app.config_manager import ConfigManager
from app.ocr import OCREngine
from app.ner import NEREngine
from app.processor import DataProcessor
from app.storage import StorageEngine
from app.exceptions import MedicalSystemError, OCRProcessError, NERModelError

# 配置全局日志记录器
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_patient_id() -> str:
    """
    生成唯一的患者就诊标识符。

    Returns:
        str: 以 "PID_" 开头，后接 8 位大写十六进制哈希值的唯一字符串标识符。
    """
    return "PID_" + uuid.uuid4().hex[:8].upper()


def run_medical_pipeline(image_path: str) -> str:
    """
    触发并执行完整的病历分析全链路流水线（批处理模式）。

    该管线依次调度感知层 (OCR) 提取文本、数据处理层清洗切分、
    认知层 (NER) 提取实体、逻辑层极性判定，最终由持久层落盘归档。

    Args:
        image_path (str): 前端上传并缓存至本地的医疗影像物理路径。

    Returns:
        str: 生成的单次就诊快照存档目录的绝对物理路径。

    Raises:
        Exception: 捕获并记录管线流转中发生的任何异常，随后向调用方抛出。
    """
    logger.info("=" * 50)
    logger.info(f"开启病历分析管线，目标文件: {image_path}")
    try:
        # 1. 实例化各层级处理引擎
        ocr_engine = OCREngine()
        ner_engine = NEREngine()
        processor = DataProcessor()
        storage = StorageEngine()

        pid = generate_patient_id()

        # 2. 图像感知与文本清洗
        raw_text = ocr_engine.extract(image_path)
        cleaned_text = processor.clean_text(raw_text)
        clinical_sections = processor.extract_clinical_sections(cleaned_text)

        chunked_results = []
        all_chunks_text = []
        all_aggregated_issues = []

        # 3. 结构化段落分块与实体认知推断
        for section_name, content in clinical_sections.items():
            if not content or len(content) < 2:
                continue

            # 按标点符号物理切片以防止模型张量输入溢出
            chunks = processor.split_into_chunks(content)
            cursor = 0
            section_all_entities = []

            for chunk in chunks:
                all_chunks_text.append(chunk)
                chunk_start_idx = content.find(chunk, cursor)
                if chunk_start_idx == -1:
                    chunk_start_idx = cursor

                # 神经实体抽取与嵌套消解
                raw_entities = ner_engine.predict_chunk(chunk)
                final_entities = processor.resolve_nested_entities(raw_entities)

                # 将短句内的相对坐标映射回段落的绝对坐标
                for ent in final_entities:
                    ent["start"] += chunk_start_idx
                    ent["end"] += chunk_start_idx
                    ent["section"] = section_name
                    section_all_entities.append(ent)
                cursor = chunk_start_idx + len(chunk)

            # 4. 后置极性传导 (阴阳性判定)
            if section_all_entities:
                section_all_entities = processor.detect_entity_polarity(
                    entities=section_all_entities, text=content
                )

            chunked_results.append(
                {
                    "section": section_name,
                    "chunk_text": content,
                    "entities": section_all_entities,
                }
            )

        # 5. 生成持久化防篡改快照并触发 CDSS 检查
        save_dir = storage.save_visit_snapshot(
            patient_id=pid,
            image_path=image_path,
            raw_ocr=raw_text,
            chunks=all_chunks_text,
            chunked_results=chunked_results,
            sections=clinical_sections,
            aggregated_issues=all_aggregated_issues,
        )
        return save_dir

    except Exception as e:
        logger.error(traceback.format_exc())
        raise e


def run_partial_ner(section_name: str, content: str) -> list:
    """
    触发局部神经推理微服务（热重载模式）。

    脱离主干流程，仅对前端发生变动的特定文本段落执行短句切分、实体推断与极性传导。
    用于响应医生的文本增删操作，实现局部无感刷新。

    Args:
        section_name (str): 触发重载的病历段落名称（如"现病史"）。
        content (str): 医生修改后的该段落的全新纯文本。

    Returns:
        list: 重新提取并计算好绝对坐标和极性的实体字典列表。
    """
    logger.info(f"触发动态流转：正在重载 [{section_name}] 段落的神经推理管线...")
    ner_engine = NEREngine()
    processor = DataProcessor()

    chunks = processor.split_into_chunks(content)
    cursor = 0
    section_all_entities = []

    for chunk in chunks:
        chunk_start_idx = content.find(chunk, cursor)
        if chunk_start_idx == -1:
            chunk_start_idx = cursor

        raw_entities = ner_engine.predict_chunk(chunk)
        final_entities = processor.resolve_nested_entities(raw_entities)

        for ent in final_entities:
            ent["start"] += chunk_start_idx
            ent["end"] += chunk_start_idx
            ent["section"] = section_name
            section_all_entities.append(ent)

        cursor = chunk_start_idx + len(chunk)

    if section_all_entities:
        section_all_entities = processor.detect_entity_polarity(
            entities=section_all_entities, text=content
        )

    logger.info(f"局部管线重载完毕，共提取 {len(section_all_entities)} 个实体。")
    return section_all_entities
