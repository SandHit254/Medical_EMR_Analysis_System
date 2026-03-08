"""
模块名称：持久层与存储控制模块
功能描述：控制底层文件系统，对系统管线的执行结果进行统一归档与快照持久化。
"""

import os
import json
import time
import shutil
from app.config_manager import ConfigManager
from app.exceptions import StorageError


class StorageEngine:
    """本地存储引擎类"""

    def __init__(self):
        """初始化存储路径"""
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
        持久化单次就诊的全量数据，包括原始图、过程数据及最终结构化 JSON。
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
            # 新增：CDSS 临床决策支持预警 (冲突检测逻辑)
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
