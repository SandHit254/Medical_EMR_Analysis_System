"""
模块名称：持久层与存储控制模块
功能描述：控制底层文件系统，对系统管线的执行结果进行统一归档与快照持久化。
         包含目录创建、原始图像备份、OCR 中间件落盘、NER 结果存储
         以及触发临床决策支持系统 (CDSS) 的冲突拦截。
"""

import os
import json
import time
import shutil
from app.config_manager import ConfigManager
from app.exceptions import StorageError


class StorageEngine:
    """
    本地文件存储引擎。

    负责根据就诊批次生成独立的流水目录，并按流转顺序落盘各个模型节点的输出状态，
    从而保证临床数据的防篡改性与完全可溯源性。
    """

    def __init__(self):
        """
        初始化存储引擎。

        从全局配置中心 (ConfigManager) 中动态读取 'storage' 配置节点，
        并设定系统结构化数据归档的物理根目录。
        """
        cfg = ConfigManager().get_section("storage")
        self.root = cfg.get("root_path", "output/patient_records")

    def save_visit_snapshot(
        self,
        patient_id: str,
        image_path: str,
        raw_ocr: str,
        chunks: list,
        chunked_results: list,
        sections: dict,
        aggregated_issues: list,
    ) -> str:
        """
        持久化单次就诊的全量业务数据，并触发 CDSS 预警校验。

        该方法按顺序生成 01_source 到 05_final_summary 的快照文件，涵盖从
        原始图像到最终结构化提取结果的全生命周期。同时，会在最终步骤中读取内存中的
        CDSS 规则库，对当前提取的实体与病历文本进行过敏原/禁忌药物的碰撞计算。

        Args:
            patient_id (str): 患者的唯一身份标识符 (如 "PID_XXXXX")。
            image_path (str): 前端上传后缓存在本地的原始医疗扫描件物理路径。
            raw_ocr (str): OCR 引擎提取出的全量未经清洗的原始脏文本。
            chunks (list): 经过物理标点切片处理的短句字符串列表。
            chunked_results (list): 包含各个短句文本及其被提取出实体的详细参数列表字典。
            sections (dict): 按照 "主诉"、"现病史" 等标准临床表头进行结构化切割的文本字典。
            aggregated_issues (list): 智能诊断逻辑抛出的核心问题汇总列表。

        Returns:
            str: 生成的本次就诊批次专属存储根目录路径 (例如 'output/patient_records/PID_XXX/V_XXX')。

        Raises:
            StorageError: 当物理磁盘路径创建失败、文件权限不足或 JSON 序列化发生异常时抛出。
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        patient_folder = (
            patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
        )
        visit_dir = os.path.join(self.root, patient_folder, f"V_{timestamp}")

        try:
            os.makedirs(visit_dir, exist_ok=True)

            if os.path.exists(image_path):
                shutil.copy(image_path, os.path.join(visit_dir, "01_source.jpg"))

            with open(
                os.path.join(visit_dir, "02_ocr_raw.txt"), "w", encoding="utf-8"
            ) as f:
                f.write(raw_ocr)

            chunk_text_formatted = "\n".join(
                [f"[{i+1}] {c}" for i, c in enumerate(chunks)]
            )
            with open(
                os.path.join(visit_dir, "03_ocr_chunked.txt"), "w", encoding="utf-8"
            ) as f:
                f.write(chunk_text_formatted)

            with open(
                os.path.join(visit_dir, "04_ner_analysis.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(chunked_results, f, ensure_ascii=False, indent=4)

            # =========================================================
            # 生成终态结构化草案
            # =========================================================
            summary = {
                "就诊编号": f"V_{timestamp}",
                "患者ID": patient_id,
                "结构化病历": sections,
                "智能诊断核心问题": aggregated_issues,
                "提取实体": [],
            }

            all_ents = []
            for cr in chunked_results:
                all_ents.extend(cr["entities"])
            summary["提取实体"] = all_ents

            # =========================================================
            # CDSS 临床决策支持预警 (冲突检测逻辑)
            # =========================================================
            rules_cfg = ConfigManager().get_section("rules")
            cdss_rules = rules_cfg.get("cdss_rules", [])
            cdss_warnings = []

            # 将结构化文本展平，方便全局查找过敏史
            emr_full_text = json.dumps(sections, ensure_ascii=False)
            # 获取所有被 NER 模型提取出的实体纯文本
            extracted_entity_texts = [e["text"] for e in all_ents]

            for rule in cdss_rules:
                # 触发条件 1：病历的任何段落（尤其是既往史/过敏史）中出现了过敏原
                if rule["allergy"] in emr_full_text:
                    for drug in rule["drugs"]:
                        # 触发条件 2：只要提取出的实体包含禁忌药名词根，立刻拦截
                        if any(drug in ent_text for ent_text in extracted_entity_texts):
                            cdss_warnings.append(
                                rule["warning"].replace("{drug}", drug)
                            )

            if cdss_warnings:
                summary["CDSS预警"] = list(set(cdss_warnings))
            # =========================================================

            # 生成终态 05 结构化草案文件供 Web 层渲染
            with open(
                os.path.join(visit_dir, "05_final_summary.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(summary, f, ensure_ascii=False, indent=4)

            return visit_dir

        except Exception as e:
            raise StorageError(f"归档过程失败: {str(e)}")
