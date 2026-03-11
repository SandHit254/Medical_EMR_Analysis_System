"""
模块名称：持久层与存储控制模块
功能描述：控制底层文件系统，对系统管线的执行结果进行统一归档与快照持久化。
         包含绝对路径寻址、跨历史文件多模态检索、以及 CDSS 规则碰撞拦截。
"""

import os
import json
import time
import shutil
import logging
from app.config_manager import ConfigManager
from app.exceptions import StorageError

logger = logging.getLogger(__name__)


class StorageEngine:
    """本地文件存储引擎"""

    def __init__(self):
        """初始化存储引擎，动态计算基于项目根目录的绝对存储路径"""
        cfg = ConfigManager().get_section("storage")
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root_cfg = cfg.get("root_path", "output/patient_records")
        if os.path.isabs(root_cfg):
            self.root = root_cfg
        else:
            self.root = os.path.join(base_dir, root_cfg)

    def get_patient_tree(self) -> list:
        """获取患者树状目录 (用于左侧栏手风琴导航)"""
        tree = []
        if not os.path.exists(self.root):
            return tree

        pids = [d for d in os.listdir(self.root) if d.startswith("PID_")]
        pids.sort(
            key=lambda x: os.path.getmtime(os.path.join(self.root, x)), reverse=True
        )

        for pid in pids:
            hist = self.get_patient_history(pid)
            patient_dir = os.path.join(self.root, pid)
            visits = sorted(
                [d for d in os.listdir(patient_dir) if d.startswith("V_")], reverse=True
            )
            visit_list = []

            for v in visits:
                time_str = v.replace("V_", "")
                try:
                    formatted_time = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]} {time_str[9:11]}:{time_str[11:13]}"
                except Exception:
                    formatted_time = time_str
                visit_list.append({"visit_id": v, "time": formatted_time})

            tree.append(
                {
                    "patient_id": pid,
                    "name": hist.get("姓名", "") or "未知",
                    "gender": hist.get("性别", "") or "-",
                    "visits": visit_list,
                }
            )
        return tree

    def search_records(self, query: str) -> list:
        """多模态检索引擎：支持按姓名、PID、以及提取出的医疗实体词检索历史病历"""
        results = []
        query = query.lower().strip()
        if not query or not os.path.exists(self.root):
            return results

        pids = [d for d in os.listdir(self.root) if d.startswith("PID_")]
        pids.sort(
            key=lambda x: os.path.getmtime(os.path.join(self.root, x)), reverse=True
        )

        for pid in pids:
            patient_dir = os.path.join(self.root, pid)
            visits = sorted(
                [d for d in os.listdir(patient_dir) if d.startswith("V_")], reverse=True
            )

            for v in visits:
                target_file = os.path.join(patient_dir, v, "06_human_verified.json")
                if not os.path.exists(target_file):
                    target_file = os.path.join(patient_dir, v, "05_final_summary.json")

                if os.path.exists(target_file):
                    try:
                        with open(target_file, "r", encoding="utf-8") as f:
                            data = json.load(f)

                        emr = data.get("结构化病历", {})
                        name = emr.get("姓名", "")
                        ents = data.get("提取实体", [])
                        ent_texts = [e.get("text", "").lower() for e in ents]

                        match_pid = query in pid.lower()
                        match_name = query in name.lower()
                        matched_ents = [t for t in ent_texts if query in t]
                        match_ent = len(matched_ents) > 0

                        if match_pid or match_name or match_ent:
                            tags = []
                            if match_name:
                                tags.append("姓名匹配")
                            if match_pid:
                                tags.append("PID匹配")
                            if match_ent:
                                tags.append(f"实体命中: {matched_ents[0]}")

                            time_str = v.replace("V_", "")
                            try:
                                formatted_time = (
                                    f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
                                )
                            except Exception:
                                formatted_time = time_str

                            results.append(
                                {
                                    "patient_id": pid,
                                    "visit_id": v,
                                    "name": name or "未知",
                                    "time": formatted_time,
                                    "tags": tags[:2],
                                }
                            )
                    except json.JSONDecodeError:
                        # 【核心修复】：防止单一文件损坏导致的检索雪崩崩溃
                        logger.warning(f"搜索器隔离了损坏的 JSON 文件: {target_file}")
                        continue
        return results

    def get_all_patients_info(self) -> list:
        """EMPI 网关接口：获取所有患者基础信息"""
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
        """跨时空档案继承：获取某个患者最新一次的历史病历信息"""
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
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    emr = data.get("结构化病历", {})
                    history["姓名"] = emr.get("姓名", "")
                    history["性别"] = emr.get("性别", "")
                    history["年龄"] = emr.get("年龄", "")
                    history["既往史"] = emr.get("既往史", "")
                    history["过敏史"] = emr.get("过敏史", "")
            except json.JSONDecodeError:
                pass
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
        """双向 CDSS 拦截检验与快照持久化归档"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        patient_folder = (
            patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
        )
        visit_dir = os.path.join(self.root, patient_folder, f"V_{timestamp}")

        try:
            os.makedirs(visit_dir, exist_ok=True)

            # 兼容纯文本直通模式，若无图径则跳过物理复制
            if image_path and os.path.exists(image_path):
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

            rules_cfg = ConfigManager().get_section("rules")
            cdss_rules = rules_cfg.get("cdss_rules", [])
            cdss_warnings = []
            emr_full_text = json.dumps(sections, ensure_ascii=False)
            extracted_entity_texts = [e["text"] for e in all_ents]

            for rule in cdss_rules:
                if rule["allergy"] in emr_full_text:
                    for drug in rule["drugs"]:
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
            raise StorageError(f"归档持久化过程失败: {str(e)}")
