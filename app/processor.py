"""
模块名称：数据处理引擎模块
功能描述：负责处理文本的预处理（清洗、纠错）、中置处理（切句、段落划分）、
         以及后置处理（实体嵌套消解、极性分析、业务逻辑组装）。
"""

import re
from app.config_manager import ConfigManager


class DataProcessor:
    """文本与数据结构化处理类"""

    def __init__(self):
        """初始化处理器，从 ConfigManager 加载文本处理所需的正则与规则字典"""
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
        """
        if not self.enable_correction or not self.corrections:
            return raw_text

        cleaned = raw_text
        for wrong, right in self.corrections.items():
            cleaned = cleaned.replace(wrong, right)
        return cleaned

    def extract_clinical_sections(self, text: str) -> dict:
        """
        采用锚点截断法将长文本按照病历结构切分为独立段落。
        解决正则贪婪匹配问题，对定义为短字段(如姓名、科室)的属性进行边界阻断。
        """
        sections = {}
        if not self.section_patterns:
            return sections

        sorted_patterns = sorted(self.section_patterns, key=len, reverse=True)

        # 兼容 "1、" "2." "【" "一、" 等前缀，确保切分点在标号或括号之前
        pattern_str = (
            r"(?:(?:\d{1,2}|[一二三四五六七八九十])[、\.\s]+|【)?("
            + "|".join(sorted_patterns)
            + r")】?\s*[:：]"
        )

        found_headers = []
        for match in re.finditer(pattern_str, text):
            header_name = match.group(1)
            # 异常过滤：拒绝超长非标题文本
            if len(header_name) > 15:
                continue
            found_headers.append(
                {"start": match.start(), "end": match.end(), "header": header_name}
            )

        found_headers.sort(key=lambda x: x["start"])

        # 提取文件头部通用信息
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

            # 短字段边界控制逻辑
            if current["header"] in self.short_fields:
                parts = [
                    p.strip() for p in re.split(r"[，,。；;]", content) if p.strip()
                ]
                if parts:
                    content = parts[0]
                    # 检测越界捕获
                    if content in self.section_patterns:
                        content = ""
                else:
                    content = ""

            sections[current["header"]] = content

        return sections

    def split_into_chunks(self, text: str) -> list:
        """
        按标点符号切分长段落，避免超过大语言模型的 Token 长度限制。
        将长病历切分为适合单次张量推理的短句。
        """
        if not text:
            return []

        # 以中文句号、分号、换行符作为物理截断点
        chunks = [c.strip() for c in re.split(r"[。；\n]", text) if c.strip()]
        return chunks

    def resolve_nested_entities(self, entities: list) -> list:
        """
        消除嵌套实体，并引入实体清洗与黑名单过滤机制。
        解决模型过召回（Over-Recall）与领域偏移带来的脏数据。
        """
        # 1. 前置过滤规则
        filtered_entities = []
        blacklist = {"母乳", "间径", "cm", "mm", "无", "否", "未"}

        for e in entities:
            text = e["text"].strip(" ，。；、：:()（）[]【】")
            # 规则 a: 长度太短且不是特殊缩写
            if len(text) < 2 and not re.match(r"[痛痒晕肿]", text):
                continue
            # 规则 b: 纯数字或带单位的数值
            if re.fullmatch(
                r"[a-zA-Z0-9\.\+\-\*\/]+(cm|mm|kg|g|ml|l|bp|bpm|mmhg)?", text.lower()
            ):
                continue
            # 规则 c: 命中黑名单
            if text in blacklist or any(b in text for b in blacklist if len(b) > 2):
                continue

            e["text"] = text
            filtered_entities.append(e)

        # 2. 嵌套消解逻辑
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

        # 3. 最终去重
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
        实体极性分析 (Polarity Analysis)
        通过前置文本滑动窗口检测否定词，并支持“、”“，”等标点符号的连续否定辖域传导。
        """
        # 必须先按在文本中的出现顺序排序，才能进行连续向后传导
        entities.sort(key=lambda x: x["start"])

        for i, ent in enumerate(entities):
            start_idx = ent.get("start", 0)

            # 1. 常规滑动窗口探测
            window_start = max(0, start_idx - window_size)
            prefix_context = text[window_start:start_idx]

            ent["polarity"] = "阳性"  # 默认均为阳性（存在）

            # 扫描前置上下文中是否包含否定词
            for neg_word in self.negation_words:
                if neg_word in prefix_context:
                    ent["polarity"] = "阴性"
                    break

            # 2. 连续否定辖域传导 (Negation Scope Propagation)
            # 如果当前实体常规探测为阳性，但它前面存在其他实体
            if ent["polarity"] == "阳性" and i > 0:
                prev_ent = entities[i - 1]
                # 如果前一个实体被判定为阴性（被否定）
                if prev_ent.get("polarity") == "阴性":
                    # 截取两个实体中间的间隔文本
                    gap_text = text[prev_ent["end"] : start_idx].strip()
                    # 如果间隔文本仅仅是枚举连接符，说明它们处于同一个否定句式中，执行极性感染
                    if re.fullmatch(r"[、，,和及与\s]*", gap_text):
                        ent["polarity"] = "阴性"

        return entities
