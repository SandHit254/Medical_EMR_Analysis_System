"""
模块名称：数据中台与逻辑工程模块 (Data Processor)
功能描述：负责处理文本的预处理（清洗、纠错）、中置处理（切句、段落划分）、
         以及后置处理（实体嵌套消解、极性分析、业务逻辑组装）。
"""

import re
from app.config_manager import ConfigManager


class DataProcessor:
    """
    文本与数据结构化处理核心类。
    提供一系列无状态的字符串处理、正则匹配与逻辑判定方法，
    作为感知层 (OCR) 与认知层 (NER) 之间的桥梁，保障流入大模型的文本纯净度。
    """

    def __init__(self):
        """
        初始化数据处理器。
        从全局配置中心动态读取文本清洗、段落截断与极性传导所需的所有正则锚点与字典。
        """
        post_cfg = ConfigManager().get_section("post_processing")
        rules_cfg = ConfigManager().get_section("rules")

        self.enable_correction = post_cfg.get("enable_auto_correction", True)
        self.corrections = rules_cfg.get("corrections", {})

        self.section_patterns = rules_cfg.get("section_patterns", [])
        self.negation_words = rules_cfg.get("negation_words", [])

    def clean_text(self, raw_text: str) -> str:
        """
        执行 OCR 输出文本的清洗与字典校对。

        Args:
            raw_text (str): 原始粗糙文本。

        Returns:
            str: 消除空格与换行，并应用 corrections 字典纠错后的连续纯净文本。
        """
        text = raw_text.replace(" ", "").replace("\n", "。").replace("\r", "。")
        text = re.sub(r"。+", "。", text)

        if self.enable_correction:
            for wrong, right in self.corrections.items():
                text = text.replace(wrong, right)
        return text

    def extract_clinical_sections(self, text: str) -> dict:
        """
        基于正则锚点（如"主诉:"）对病历长文本进行段落截断与结构化。

        Args:
            text (str): 清洗后的连续长文本。

        Returns:
            dict: 键为段落名，值为对应内容的字典。若无锚点则返回空字典。
        """
        sections = {}
        if not self.section_patterns:
            return sections

        pattern = r"(" + "|".join(self.section_patterns) + r")[:：]?"
        matches = list(re.finditer(pattern, text))

        if not matches:
            return sections

        for i, match in enumerate(matches):
            section_name = match.group(1)
            start_idx = match.end()
            end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start_idx:end_idx].strip(" 。，；,;")
            sections[section_name] = content

        return sections

    def split_into_chunks(self, text: str, max_len: int = 120) -> list:
        """
        将超长段落安全切分为不超过模型限制长度的短句集合。

        Args:
            text (str): 待切分的长段落。
            max_len (int): BERT 模型允许的最大序列长度 (扣除首尾特殊符)。

        Returns:
            list: 字符串切片列表。
        """
        sentences = re.split(r"([。！？；!?;])", text)
        sentences.append("")
        sentences = ["".join(i) for i in zip(sentences[0::2], sentences[1::2])]

        chunks = []
        current_chunk = ""
        for s in sentences:
            if not s:
                continue
            if len(current_chunk) + len(s) <= max_len:
                current_chunk += s
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = s
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    def resolve_nested_entities(self, entities: list) -> list:
        """
        实体嵌套消解算法 (Maximum Length First)。
        当同一位置识别出多个相互重叠的实体时，保留最长的一个。

        Args:
            entities (list): 原始实体列表。

        Returns:
            list: 消除重叠冲突后的实体列表。
        """
        if not entities:
            return []

        # 排序策略：起始位置越前越优先，起始位置相同则长度越长越优先
        entities = sorted(
            entities, key=lambda x: (x["start"], -(x["end"] - x["start"]))
        )

        resolved = []
        last_end = -1
        for ent in entities:
            if ent["start"] >= last_end:
                resolved.append(ent)
                last_end = ent["end"]
            elif ent["end"] > last_end:
                ent["start"] = last_end
                if ent["end"] > ent["start"]:
                    resolved.append(ent)
                    last_end = ent["end"]
        return resolved

    def detect_entity_polarity(
        self, entities: list, text: str, window_size: int = 6
    ) -> list:
        """
        基于滑动窗口与辖域传导的实体极性分析 (Polarity Analysis)。

        判定实体是否存在被“否定”或“排除”的语境。除常规的前置扫描外，还能识别并处理
        如 "否认高血压、糖尿病、心脏病" 这种由顿号连接的连续否定辖域传导。

        Args:
            entities (list): 降噪后的实体列表。
            text (str): 实体所在的原始段落文本。
            window_size (int): 扫描实体前方 N 个字符以探测否定词，默认为 6。

        Returns:
            list: 追加了 "polarity" ("阳性" 或 "阴性") 字段的新列表。
        """
        entities.sort(key=lambda x: x["start"])

        for i, ent in enumerate(entities):
            start_idx = ent.get("start", 0)
            window_start = max(0, start_idx - window_size)
            prefix_context = text[window_start:start_idx]

            ent["polarity"] = "阳性"

            # 1. 独立否定词检测
            if any(neg in prefix_context for neg in self.negation_words):
                ent["polarity"] = "阴性"
                continue

            # 2. 顿号辖域传导检测
            check_idx = ent["start"] - 1
            while check_idx >= 0 and text[check_idx] in ["、", "，", ",", "与", "和"]:
                is_chained_neg = False
                prev_ent = next((e for e in entities if e["end"] == check_idx), None)

                if prev_ent and prev_ent.get("polarity") == "阴性":
                    is_chained_neg = True
                else:
                    scan_start = max(0, check_idx - window_size)
                    if any(
                        neg in text[scan_start:check_idx] for neg in self.negation_words
                    ):
                        is_chained_neg = True

                if is_chained_neg:
                    ent["polarity"] = "阴性"
                    break
                check_idx -= 1

        return entities
