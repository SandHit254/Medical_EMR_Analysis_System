"""
模块名称：病历分析系统主入口
功能描述：作为系统的主调度器，负责初始化配置模块、构建业务流管线，
         管理各处理层之间的参数流转并负责最外层异常捕获。
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

# 配置应用级标准日志输出
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_patient_id() -> str:
    """生成并返回全局唯一短标识符"""
    return uuid.uuid4().hex[:8].upper()


def run_medical_pipeline(image_path: str):
    """
    执行完整的病历分析业务流水线。

    Args:
        image_path (str): 待处理的病历图片物理路径。
    """
    logger.info("=" * 50)
    logger.info("系统启动：医疗病历智能分析模块")

    try:
        # 1. 引擎初始化
        ocr = OCREngine()
        processor = DataProcessor()
        ner = NEREngine()
        storage = StorageEngine()

        pid = generate_patient_id()
        logger.info(f"分配就诊系统标识符: PID_{pid}")

        # 2. 感知层处理
        logger.info("[环节 1/4] 执行 OCR 图像文本提取任务...")
        try:
            raw_text = ocr.extract(image_path)
        except Exception as e:
            raise OCRProcessError(f"OCR 引擎故障: {str(e)}")

        # 3. 预处理与结构划分
        logger.info("[环节 2/4] 执行文本清洗与病历结构划分...")
        cleaned_text = processor.clean_text(raw_text)
        clinical_sections = processor.extract_clinical_sections(cleaned_text)
        if clinical_sections:
            logger.info(f"已识别病历段落: {list(clinical_sections.keys())}")

        # 4. 认知层处理：医疗实体抽取与上下文关联
        logger.info("[环节 3/4] 结合病历段落执行医疗实体抽取与智能组合...")

        chunked_results = []
        all_chunks_text = []
        all_aggregated_issues = []

        for section_name, section_content in clinical_sections.items():
            if not section_content.strip():
                continue

            chunks = processor.split_into_chunks(section_content)

            for chunk in chunks:
                all_chunks_text.append(f"[{section_name}] {chunk}")

                try:
                    raw_entities = ner.predict_chunk(chunk)
                except Exception as e:
                    raise NERModelError(
                        f"NER 模型推理异常，目标句 '{chunk[:10]}...': {str(e)}"
                    )

                resolved_entities = processor.resolve_nested_entities(raw_entities)
                final_entities = processor.flag_negations(chunk, resolved_entities)

                # 实体关联计算
                sentence_issues = processor.aggregate_relations(
                    final_entities, chunk_text=chunk
                )
                for issue in sentence_issues:
                    issue["来源段落"] = section_name
                    all_aggregated_issues.append(issue)
                    logger.info(f"逻辑推断结论: [{section_name}] {issue['临床结论']}")

                for ent in final_entities:
                    ent["所属段落"] = section_name
                    flag = "[否定语境]" if ent.get("is_negated") else ""
                    logger.info(
                        f"实体记录: [{section_name}] -> [{ent['type']}] : {ent['text']} {flag}"
                    )

                chunked_results.append(
                    {
                        "section": section_name,
                        "chunk_text": chunk,
                        "entities": final_entities,
                    }
                )

        # 5. 持久层归档
        logger.info("[环节 4/4] 触发持久化存储机制...")
        save_dir = storage.save_visit_snapshot(
            patient_id=pid,
            image_path=image_path,
            raw_ocr=raw_text,
            chunks=all_chunks_text,
            chunked_results=chunked_results,
            sections=clinical_sections,
            aggregated_issues=all_aggregated_issues,
        )
        logger.info(f"分析流水线执行完毕。系统存档路径: {save_dir}")

    except MedicalSystemError as me:
        logger.error(f"业务逻辑阻断异常: {str(me)}")
    except Exception as e:
        logger.error("系统级崩溃拦截，堆栈跟踪信息如下：")
        logger.error(traceback.format_exc())
    finally:
        logger.info("=" * 50)


if __name__ == "__main__":
    target_image = "R.jpg"
    run_medical_pipeline(target_image)
