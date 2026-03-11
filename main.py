"""
模块名称：病历分析系统主控调度器 (Main Pipeline Orchestrator)
功能描述：基于 DAG (有向无环图) 思想构建的双模态任务流转中枢。
         负责协调感知层(OCR)、数据中台(Processor)与认知层(NER)的串联运行，
         并处理 EMPI 历史档案的继承机制与 CDSS 预警的初步聚合。
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
from app.exceptions import MedicalSystemError

# 全局日志配置
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_patient_id() -> str:
    """
    生成全局唯一的患者主索引标识符 (EMPI PID)。

    Returns:
        str: 带有 "PID_" 前缀的 8 位大写十六进制随机字符串。
    """
    return "PID_" + uuid.uuid4().hex[:8].upper()


def run_medical_pipeline(
    image_path: str = None,
    raw_text_input: str = None,
    patient_id: str = None,
    patient_info: dict = None,
) -> str:
    """
    执行双模态医疗结构化分析管线。

    根据入参智能分流：若提供纯文本，则直通 NER 认知层；若提供图像，则先唤醒 OCR 感知层。
    执行完毕后将所有张量结果、快照与预警信息移交持久层归档。

    Args:
        image_path (str, optional): 待解析的医学影像物理路径。
        raw_text_input (str, optional): 医生直接粘贴或从文档提取的纯文本。
        patient_id (str, optional): 既有患者的 PID。若为空则自动生成新档。
        patient_info (dict, optional): 包含姓名、性别、年龄等基础信息的字典。

    Returns:
        str: 成功执行后，返回生成的本地就诊快照存储目录路径。

    Raises:
        MedicalSystemError: 当输入模态全部为空时触发管线阻断。
        Exception: 捕获并记录其他所有未预期的子模块崩溃。
    """
    logger.info("=" * 50)
    logger.info("开启双模态医疗分析管线 (Dual-Pipeline)")
    try:
        # 1. 挂载核心引擎
        ner_engine = NEREngine()
        processor = DataProcessor()
        storage = StorageEngine()
        pid = patient_id if patient_id else generate_patient_id()

        # 2. 模态侦测与分流网关
        if raw_text_input is not None and raw_text_input.strip():
            logger.info("⚡ 命中纯文本模式：跳过 OCR 算子，直通结构化认知层")
            raw_text = raw_text_input.strip()
        elif image_path:
            logger.info(f"📸 命中图像模式：唤醒 OCR 算子解析 [{image_path}]")
            ocr_engine = OCREngine()
            raw_text = ocr_engine.extract(image_path)
        else:
            raise MedicalSystemError("致命阻断：必须提供影像流或纯文本输入之一")

        # 3. 数据中台清洗与截断
        cleaned_text = processor.clean_text(raw_text)
        clinical_sections = processor.extract_clinical_sections(cleaned_text)

        # 兜底容错机制：若长文本未能匹配任何正则锚点，自动包裹进综合沙箱
        has_extracted_content = any(bool(v.strip()) for v in clinical_sections.values())
        if not has_extracted_content and cleaned_text.strip():
            clinical_sections["综合病历文本"] = cleaned_text.strip()

        # 4. EMPI 历史健康档案继承与对齐
        history = storage.get_patient_history(pid)
        for key in ["姓名", "性别", "年龄"]:
            val = ""
            if patient_info and patient_info.get(key):
                val = str(patient_info.get(key)).strip()
            elif history.get(key):
                val = str(history.get(key)).strip()
            if val:
                clinical_sections[key] = val

        # 智能合并既往史与过敏史（防止文本重复）
        hist_allergy = history.get("过敏史", "").strip()
        if hist_allergy:
            current_allergy = str(clinical_sections.get("过敏史", "")).strip()
            if hist_allergy not in current_allergy:
                clinical_sections["过敏史"] = (
                    f"{current_allergy}，{hist_allergy}".strip("，")
                )

        hist_past = history.get("既往史", "").strip()
        if hist_past:
            current_past = str(clinical_sections.get("既往史", "")).strip()
            if hist_past not in current_past:
                clinical_sections["既往史"] = f"{current_past}，{hist_past}".strip("，")

        # 5. 神经认知层张量推理
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
                # 计算切片在原段落中的绝对起始坐标
                chunk_start_idx = content.find(chunk, cursor)
                if chunk_start_idx == -1:
                    chunk_start_idx = cursor

                raw_entities = ner_engine.predict_chunk(chunk)
                final_entities = processor.resolve_nested_entities(raw_entities)

                # 将切片相对坐标映射回段落绝对坐标
                for ent in final_entities:
                    ent["start"] += chunk_start_idx
                    ent["end"] += chunk_start_idx
                    ent["section"] = section_name
                    section_all_entities.append(ent)

                cursor = chunk_start_idx + len(chunk)

            # 执行极性辖域传导
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

        # 6. 智能辅诊结论聚合 (AI Summary)
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

        # 7. 触发持久化归档落盘
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
        logger.error(f"管线流转崩溃:\n{traceback.format_exc()}")
        raise e


def run_partial_ner(section_name: str, content: str) -> list:
    """
    局部热重载：对单独修改的病历段落重新执行 NER 推理。

    用于前端工作站的【增删重载】功能。仅对局部文本进行张量运算，
    避免全局重载带来的算力浪费，实现毫秒级交互反馈。

    Args:
        section_name (str): 段落名称（如 '现病史'）。
        content (str): 修改后的最新文本内容。

    Returns:
        list: 重新提取并对齐绝对坐标的实体字典列表。
    """
    logger.info(f"触发动态微服务：重载 [{section_name}] 段落的神经推理管线")
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
