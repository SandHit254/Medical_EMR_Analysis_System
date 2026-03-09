"""
模块名称：持久层与存储控制模块
"""

import os
import json
import time
import shutil
from app.config_manager import ConfigManager
from app.exceptions import StorageError


class StorageEngine:
    """本地文件存储引擎"""

    def __init__(self):
        cfg = ConfigManager().get_section("storage")
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root_cfg = cfg.get("root_path", "output/patient_records")

        if os.path.isabs(root_cfg):
            self.root = root_cfg
        else:
            self.root = os.path.join(base_dir, root_cfg)

    def get_all_patients_info(self) -> list:
        if not os.path.exists(self.root):
            return []

        patients = [d for d in os.listdir(self.root) if d.startswith("PID_")]
        patients.sort(
            key=lambda x: os.path.getmtime(os.path.join(self.root, x)), reverse=True
        )

        result = []
        for p in patients:
            hist = self.get_patient_history(p)
            result.append(
                {
                    "id": p,
                    "name": hist.get("姓名", "") or "未知",
                    "gender": hist.get("性别", "") or "-",
                    "age": hist.get("年龄", "") or "-",
                }
            )
        return result

    def get_patient_history(self, patient_id: str) -> dict:
        patient_folder = (
            patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
        )
        patient_dir = os.path.join(self.root, patient_folder)
        history = {"姓名": "", "性别": "", "年龄": "", "既往史": "", "过敏史": ""}

        if not os.path.exists(patient_dir):
            return history

        visits = sorted(
            [d for d in os.listdir(patient_dir) if d.startswith("V_")], reverse=True
        )
        if not visits:
            return history

        latest_visit = visits[0]
        target_file = os.path.join(patient_dir, latest_visit, "06_human_verified.json")
        if not os.path.exists(target_file):
            target_file = os.path.join(
                patient_dir, latest_visit, "05_final_summary.json"
            )

        if os.path.exists(target_file):
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                emr = data.get("结构化病历", {})
                history["姓名"] = emr.get("姓名", "")
                history["性别"] = emr.get("性别", "")
                history["年龄"] = emr.get("年龄", "")
                history["既往史"] = emr.get("既往史", "")
                history["过敏史"] = emr.get("过敏史", "")

        return history

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
            # 修复版 CDSS：全局拦截 (双向比对文本与实体)
            # =========================================================
            rules_cfg = ConfigManager().get_section("rules")
            cdss_rules = rules_cfg.get("cdss_rules", [])
            cdss_warnings = []
            emr_full_text = json.dumps(sections, ensure_ascii=False)
            extracted_entity_texts = [e["text"] for e in all_ents]

            for rule in cdss_rules:
                if rule["allergy"] in emr_full_text:
                    for drug in rule["drugs"]:
                        # 只要禁忌药物出现在医生手写文本中 OR 在提取实体中，统统拦截！
                        if drug in emr_full_text or any(
                            drug in ent_text for ent_text in extracted_entity_texts
                        ):
                            cdss_warnings.append(
                                rule["warning"].replace("{drug}", drug)
                            )

            if cdss_warnings:
                summary["CDSS预警"] = list(set(cdss_warnings))

            with open(
                os.path.join(visit_dir, "05_final_summary.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(summary, f, ensure_ascii=False, indent=4)

            return visit_dir
        except Exception as e:
            raise StorageError(f"归档过程失败: {str(e)}")
