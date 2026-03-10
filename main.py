"""
模块名称：病历分析系统主入口
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
    image_path: str = None,
    raw_text_input: str = None,
    patient_id: str = None,
    patient_info: dict = None,
) -> str:
    """执行管线：融合 OCR 感知与纯文本直通双模态"""
    logger.info("=" * 50)
    logger.info(f"开启双模态分析管线")
    try:
        ner_engine = NEREngine()
        processor = DataProcessor()
        storage = StorageEngine()
        pid = patient_id if patient_id else generate_patient_id()

        if raw_text_input is not None and raw_text_input.strip():
            logger.info("⚡ 命中纯文本模式：跳过 OCR 算子，直通结构化认知层")
            raw_text = raw_text_input.strip()
        elif image_path:
            logger.info(f"📸 命中图像模式：唤醒 OCR 算子解析 {image_path}")
            ocr_engine = OCREngine()
            raw_text = ocr_engine.extract(image_path)
        else:
            raise MedicalSystemError("管线阻断：必须提供影像或纯文本输入之一")

        cleaned_text = processor.clean_text(raw_text)
        clinical_sections = processor.extract_clinical_sections(cleaned_text)

        # 【核心修复 1】：纯文本兜底容错机制
        # 如果一段文本没有任何诸如“主诉：”的引导词，它会被正则全部丢弃。
        # 这里进行兜底拦截，如果全为空，直接包装为“综合病历文本”强制送入 NER 引擎。
        has_extracted_content = any(bool(v.strip()) for v in clinical_sections.values())
        if not has_extracted_content and cleaned_text.strip():
            clinical_sections["综合病历文本"] = cleaned_text.strip()

        # EMPI 历史继承机制
        history = storage.get_patient_history(pid)
        for key in ["姓名", "性别", "年龄"]:
            val = ""
            if patient_info and patient_info.get(key):
                val = patient_info.get(key)
            elif history.get(key):
                val = history.get(key)
            if val:
                clinical_sections[key] = val

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

        # NER 推理切片
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
