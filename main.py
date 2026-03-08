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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_patient_id() -> str:
    return "PID_" + uuid.uuid4().hex[:8].upper()


def run_medical_pipeline(image_path: str) -> str:
    logger.info("=" * 50)
    logger.info(f"开启病历分析管线，目标文件: {image_path}")
    try:
        ocr_engine = OCREngine()
        ner_engine = NEREngine()
        processor = DataProcessor()
        storage = StorageEngine()

        pid = generate_patient_id()

        raw_text = ocr_engine.extract(image_path)
        cleaned_text = processor.clean_text(raw_text)
        clinical_sections = processor.extract_clinical_sections(cleaned_text)

        chunked_results = []
        all_chunks_text = []
        all_aggregated_issues = []

        for section_name, content in clinical_sections.items():
            if not content or len(content) < 2:
                continue
            chunks = processor.split_into_chunks(content)
            cursor = 0
            section_all_entities = []

            for chunk in chunks:
                all_chunks_text.append(chunk)
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

            chunked_results.append(
                {
                    "section": section_name,
                    "chunk_text": content,
                    "entities": section_all_entities,
                }
            )

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


# =========================================================================
# 【新增核心调度器】支持只处理单段文本的局部管线重启
# =========================================================================
def run_partial_ner(section_name: str, content: str) -> list:
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
