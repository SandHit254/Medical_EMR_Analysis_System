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
        self.root = cfg.get("root_path", "output/records")

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

        Args:
            patient_id (str): 患者全局唯一标识符。
            image_path (str): 原始病历图片路径。
            raw_ocr (str): 原始 OCR 提取文本。
            chunks (list): 携带段落标识的短句文本集合。
            chunked_results (list): 分块保存的实体分析结果。
            sections (dict): 切分完成的非医疗结构化段落。
            aggregated_issues (list): 高级组合实体关联结论。

        Returns:
            str: 当前就诊记录生成的目录路径。

        Raises:
            StorageError: 当文件权限不足或目录创建失败时抛出。
        """
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            visit_dir = os.path.join(self.root, f"PID_{patient_id}", f"V_{timestamp}")
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

            with open(
                os.path.join(visit_dir, "05_final_summary.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(summary, f, ensure_ascii=False, indent=4)

            return visit_dir

        except Exception as e:
            raise StorageError(f"文件系统写入失败: {str(e)}")
