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


def run_medical_pipeline(
    image_path: str, patient_id: str = None, patient_info: dict = None
) -> str:
    """执行管线：融合 OCR 提取、EMPI 历史继承与前端手动输入"""
    logger.info("=" * 50)
    logger.info(f"开启病历分析管线，目标文件: {image_path}")
    try:
        ocr_engine = OCREngine()
        ner_engine = NEREngine()
        processor = DataProcessor()
        storage = StorageEngine()

        pid = patient_id if patient_id else generate_patient_id()

        raw_text = ocr_engine.extract(image_path)
        cleaned_text = processor.clean_text(raw_text)
        clinical_sections = processor.extract_clinical_sections(cleaned_text)

        # =========================================================
        # EMPI 历史档案与手动输入预设信息继承机制
        # =========================================================
        history = storage.get_patient_history(pid)

        # 1. 基础信息注入 (优先级：手动输入 > 历史档案 > OCR识别)
        for key in ["姓名", "性别", "年龄"]:
            val = ""
            if patient_info and patient_info.get(key):
                val = patient_info.get(key)
            elif history.get(key):
                val = history.get(key)

            # 若已有可靠输入，强行覆盖 OCR 可能产生的杂乱文本
            if val:
                clinical_sections[key] = val

        # 2. 既往史与过敏史拼接继承 (防遗漏机制)
        hist_allergy = history.get("过敏史", "").strip()
        if hist_allergy:
            current_allergy = clinical_sections.get("过敏史", "").strip()
            if hist_allergy not in current_allergy:
                clinical_sections["过敏史"] = (
                    f"{current_allergy}，{hist_allergy}".strip("，")
                )

        hist_past = history.get("既往史", "").strip()
        if hist_past:
            current_past = clinical_sections.get("既往史", "").strip()
            if hist_past not in current_past:
                clinical_sections["既往史"] = f"{current_past}，{hist_past}".strip("，")
        # =========================================================

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

        # 智能辅诊聚合
        all_ents = []
        for cr in chunked_results:
            all_ents.extend(cr["entities"])

        positive_diseases = set(
            e["text"]
            for e in all_ents
            if e["type"] == "疾病" and e.get("polarity") != "阴性"
        )
        positive_symptoms = set(
            e["text"]
            for e in all_ents
            if e["type"] == "症状" and e.get("polarity") != "阴性"
        )

        if positive_diseases:
            all_aggregated_issues.append(
                f"模型检出阳性疾病指征: {', '.join(positive_diseases)}。"
            )
        if positive_symptoms:
            all_aggregated_issues.append(
                f"患者伴随主要病理症状: {', '.join(positive_symptoms)}。"
            )
        if not positive_diseases and not positive_symptoms:
            all_aggregated_issues.append(
                "未提取到明显的阳性疾病或症状指标，请结合临床或影像学作进一步判定。"
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


def run_partial_ner(section_name: str, content: str) -> list:
    """局部神经推理微服务（热重载模式）"""
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
    return section_all_entities
