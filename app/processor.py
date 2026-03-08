"""
模块名称：数据处理引擎模块
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
        self.corrections = ConfigManager().get_section("corrections")

        self.section_patterns = rules_cfg.get("section_patterns", [])
        self.negation_words = rules_cfg.get("negation_words", [])
        self.short_fields = set(rules_cfg.get("short_fields", []))
        self.time_pattern = rules_cfg.get(
            "time_pattern", r"(\d+|[一二三四五六七八九十两半]+)(个)?(天|月|年|周|小时)"
        )

    def clean_text(self, raw_text: str) -> str:
        """
        利用修正字典对原始 OCR 文本进行纠错清洗。

        Args:
            raw_text (str): 从 OCR 引擎输出的原始、可能包含乱码的脏文本。

        Returns:
            str: 经过 rules.json 中 corrections 字典正则替换后的纯净文本。
        """
        if not self.enable_correction or not self.corrections:
            return raw_text

        cleaned = raw_text
        for wrong, right in self.corrections.items():
            cleaned = cleaned.replace(wrong, right)
        return cleaned

    def extract_clinical_sections(self, text: str) -> dict:
        """
        采用锚点截断法，将连续的长文本切分为独立的临床病历段落。

        通过匹配类似于 "1. 主诉：" 或 "【现病史】：" 的表头特征，将非结构化文本
        转化为键值对结构，并特殊处理短字段边界以防止正则贪婪匹配越界。

        Args:
            text (str): 待切分的全量连续文本。

        Returns:
            dict: 键为段落名称（如 '主诉'），值为对应段落内容的字典。
        """
        sections = {}
        if not self.section_patterns:
            return sections

        # 优先匹配较长的表头，防止被短表头截胡
        sorted_patterns = sorted(self.section_patterns, key=len, reverse=True)

        pattern_str = (
            r"(?:(?:\d{1,2}|[一二三四五六七八九十])[、\.\s]+|【)?("
            + "|".join(sorted_patterns)
            + r")】?\s*[:：]"
        )

        found_headers = []
        for match in re.finditer(pattern_str, text):
            header_name = match.group(1)
            if len(header_name) > 15:
                continue
            found_headers.append(
                {"start": match.start(), "end": match.end(), "header": header_name}
            )

        found_headers.sort(key=lambda x: x["start"])

        if found_headers and found_headers[0]["start"] > 0:
            preamble = text[: found_headers[0]["start"]].strip(" ，。；、\n")
            if preamble:
                sections["头部信息"] = preamble

        for i, current in enumerate(found_headers):
            start_cut = current["end"]
            if i + 1 < len(found_headers):
                end_cut = found_headers[i + 1]["start"]
                content = text[start_cut:end_cut]
            else:
                content = text[start_cut:]

            content = content.strip(" ，。；、\n")

            if current["header"] in self.short_fields:
                parts = [
                    p.strip() for p in re.split(r"[，,。；;]", content) if p.strip()
                ]
                if parts:
                    content = parts[0]
                    if content in self.section_patterns:
                        content = ""
                else:
                    content = ""

            sections[current["header"]] = content

        return sections

    def split_into_chunks(self, text: str) -> list:
        """
        按物理标点切分长段落文本。

        由于预训练语言模型（如 MacBERT）存在 Token 最大长度限制（如 512），
        必须将长病历切分为短句阵列，防止显存溢出 (OOM) 并保证张量特征不丢失。

        Args:
            text (str): 需要切分的单段长文本。

        Returns:
            list: 以句号、分号或换行符分割后的短句字符串列表。
        """
        if not text:
            return []

        chunks = [c.strip() for c in re.split(r"[。；\n]", text) if c.strip()]
        return chunks

    def resolve_nested_entities(self, entities: list) -> list:
        """
        消除嵌套实体，并执行黑名单过滤降噪。

        当模型同时提取出 "左下腹" 和 "左下腹痛" 时，仅保留跨度最长、语义最完整的实体。
        同时基于启发式规则拦截明显荒谬的识别结果（如纯数字、无意义字符）。

        Args:
            entities (list): NER 模型输出的原始实体字典列表。

        Returns:
            list: 经过降噪去重后的高精度实体列表。
        """
        filtered_entities = []
        blacklist = {"母乳", "间径", "cm", "mm", "无", "否", "未"}

        for e in entities:
            text = e["text"].strip(" ，。；、：:()（）[]【】")
            if len(text) < 2 and not re.match(r"[痛痒晕肿]", text):
                continue
            if re.fullmatch(
                r"[a-zA-Z0-9\.\+\-\*\/]+(cm|mm|kg|g|ml|l|bp|bpm|mmhg)?", text.lower()
            ):
                continue
            if text in blacklist or any(b in text for b in blacklist if len(b) > 2):
                continue

            e["text"] = text
            filtered_entities.append(e)

        unique_ents = []
        seen = set()
        for e in filtered_entities:
            identifier = f"{e['type']}-{e['start']}-{e['end']}"
            if identifier not in seen:
                seen.add(identifier)
                unique_ents.append(e)

        unique_ents.sort(key=lambda x: x["end"] - x["start"], reverse=True)
        final_ents = []
        for i, entA in enumerate(unique_ents):
            textA = entA["text"]
            for entB in unique_ents[i + 1 :]:
                if entB["start"] >= entA["start"] and entB["end"] <= entA["end"]:
                    textA = textA.replace(entB["text"], "")

            textA = textA.strip('”"’‘，。、 ')
            if len(textA) >= 2 or re.match(r"[痛痒晕肿]", textA):
                final_ents.append(
                    {
                        "text": textA,
                        "type": entA["type"],
                        "score": entA["score"],
                        "start": entA["start"],
                        "end": entA["end"],
                    }
                )

        result, seen_texts = [], set()
        for e in final_ents:
            key = f"{e['type']}-{e['text']}"
            if key not in seen_texts:
                seen_texts.add(key)
                result.append(e)

        return result

    def detect_entity_polarity(
        self, entities: list, text: str, window_size: int = 5
    ) -> list:
        """
        基于滑动窗口与辖域传导的实体极性分析 (Polarity Analysis)。

        判定实体是否存在被“否定”或“排除”的语境。除常规的前置扫描外，还能识别并处理
        如 "否认高血压、糖尿病、心脏病" 这种由顿号连接的连续否定辖域传导。

        Args:
            entities (list): 降噪后的实体列表，需包含其在文本中的绝对坐标 start。
            text (str): 实体所在的原始段落文本。
            window_size (int): 扫描实体前方 N 个字符以探测否定词，默认为 5。

        Returns:
            list: 在每个实体字典中追加了 "polarity" ("阳性" 或 "阴性") 字段的新列表。
        """
        entities.sort(key=lambda x: x["start"])

        for i, ent in enumerate(entities):
            start_idx = ent.get("start", 0)

            window_start = max(0, start_idx - window_size)
            prefix_context = text[window_start:start_idx]

            ent["polarity"] = "阳性"

            for neg_word in self.negation_words:
                if neg_word in prefix_context:
                    ent["polarity"] = "阴性"
                    break

            if ent["polarity"] == "阳性" and i > 0:
                prev_ent = entities[i - 1]
                if prev_ent.get("polarity") == "阴性":
                    gap_text = text[prev_ent["end"] : start_idx].strip()
                    if re.fullmatch(r"[、，,和及与\s]*", gap_text):
                        ent["polarity"] = "阴性"

        return entities
