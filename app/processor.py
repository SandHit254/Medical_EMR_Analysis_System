"""
模块名称：数据处理引擎模块
功能描述：负责处理文本的预处理（清洗、纠错）、中置处理（切句、段落划分）、
         以及后置处理（实体嵌套消解、业务逻辑组装）。
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

        Args:
            raw_text (str): 原始文本。

        Returns:
            str: 纠错后的文本。
        """
        if not self.enable_correction:
            return raw_text
        cleaned = raw_text
        for wrong, right in self.corrections.items():
            cleaned = cleaned.replace(wrong, right)
        return cleaned

    def split_into_chunks(self, text: str) -> list:
        """
        根据常见中文标点符号将长段落切分为短句列表，防止模型截断。

        Args:
            text (str): 待切分长文本。

        Returns:
            list: 切分后的非空短句字符串列表。
        """
        chunks = re.split(r"([。，；！？])", text)
        sentences = ["".join(i) for i in zip(chunks[0::2], chunks[1::2])]
        if len(chunks) % 2 != 0 and chunks[-1]:
            sentences.append(chunks[-1])
        return [s.strip() for s in sentences if len(s.strip()) > 1]

    def resolve_nested_entities(self, entities: list) -> list:
        """
        消除嵌套实体，并引入实体清洗与黑名单过滤机制。
        解决模型过召回（Over-Recall）与领域偏移（Domain Shift）带来的脏数据。
        """
        # 1. 前置过滤规则：利用正则过滤掉纯数字、纯标点、无意义的单字
        filtered_entities = []
        # 定义一个简单的黑名单（可在后续移入 rules.json 中）
        blacklist = {"母乳", "间径", "cm", "mm", "无", "否", "未"}

        for e in entities:
            text = e["text"].strip(" ，。；、：:()（）[]【】")
            # 规则 a: 长度太短（单字）且不是特殊缩写的，丢弃
            if len(text) < 2 and not re.match(r"[痛痒晕肿]", text):
                continue
            # 规则 b: 纯数字、纯英文或带单位的数值（如 26cm, 100mmHg），大概率是指标值而非疾病，丢弃
            if re.fullmatch(
                r"[a-zA-Z0-9\.\+\-\*\/]+(cm|mm|kg|g|ml|l|bp|bpm|mmhg)?", text.lower()
            ):
                continue
            # 规则 c: 命中黑名单的，丢弃
            if text in blacklist or any(b in text for b in blacklist if len(b) > 2):
                continue

            # 更新清洗后的干净文本
            e["text"] = text
            filtered_entities.append(e)

        # 2. 嵌套消解逻辑（保留原有的长短实体去重逻辑）
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
                    # 发现被包含的短实体，将其从长实体字符串中剔除（可选策略）
                    textA = textA.replace(entB["text"], "")

            textA = textA.strip('”"’‘，。、 ')
            if len(textA) >= 2 or re.match(r"[痛痒晕肿]", textA):  # 二次校验长度
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

        result, seen_texts = [], set()
        for e in final_ents:
            key = f"{e['type']}-{e['text']}"
            if key not in seen_texts:
                seen_texts.add(key)
                result.append(e)
        return result

    def flag_negations(self, chunk: str, entities: list) -> list:
        """
        根据短句语境判断并标记实体是否处于否定状态。

        Args:
            chunk (str): 实体所在的原文短句。
            entities (list): 实体列表。

        Returns:
            list: 增加了 'is_negated' 布尔值的实体列表。
        """
        has_negation = any(nw in chunk for nw in self.negation_words)
        for ent in entities:
            ent["is_negated"] = has_negation
        return entities

    def aggregate_relations(self, entities: list, chunk_text: str = "") -> list:
        """
        基于实体分类与位置距离，进行医学逻辑关联分析与结论生成。

        Args:
            entities (list): 当前短句内清洗完毕的实体集合。
            chunk_text (str): 实体所属的原文，用于提取时间属性。

        Returns:
            list: 关联分析结果列表。
        """
        issues = []
        ents = sorted(entities, key=lambda x: x.get("start", 0))

        for i in range(len(ents) - 1):
            e1, e2 = ents[i], ents[i + 1]
            if e1.get("is_negated") or e2.get("is_negated"):
                continue

            distance = e2["start"] - e1["end"]
            if 0 <= distance <= 8:
                if e1["type"] == "身体部位" and e2["type"] in ["症状", "疾病"]:
                    issues.append(
                        {
                            "临床结论": f"{e1['text']}出现{e2['text']}",
                            "逻辑类型": "发病部位",
                        }
                    )
                elif e1["type"] == "手术/检查" and e2["type"] in ["疾病", "症状"]:
                    issues.append(
                        {
                            "临床结论": f"{e1['text']}诊断出{e2['text']}",
                            "逻辑类型": "检查结果",
                        }
                    )
                elif e1["type"] == "手术/检查" and e2["type"] == "身体部位":
                    issues.append(
                        {
                            "临床结论": f"对{e2['text']}进行{e1['text']}",
                            "逻辑类型": "治疗动作",
                        }
                    )
                elif (e1["type"] == "药物" and e2["type"] == "症状") or (
                    e1["type"] == "症状" and e2["type"] == "药物"
                ):
                    drug = e1["text"] if e1["type"] == "药物" else e2["text"]
                    sym = e2["text"] if e2["type"] == "症状" else e1["text"]
                    issues.append(
                        {"临床结论": f"使用[{drug}]应对[{sym}]", "逻辑类型": "用药目的"}
                    )

        for ent in ents:
            if ent["type"] == "症状" and not ent.get("is_negated"):
                search_area = chunk_text[ent["end"] : ent["end"] + 10]
                time_match = re.search(self.time_pattern, search_area)
                if time_match:
                    issues.append(
                        {
                            "临床结论": f"{ent['text']} (持续: {time_match.group(0)})",
                            "逻辑类型": "症状病程",
                        }
                    )
        return issues

    def extract_clinical_sections(self, text: str) -> dict:
        """
        采用锚点截断法将长文本按照病历结构切分为独立段落。
        解决正则贪婪匹配问题，对定义为短字段(如姓名、科室)的属性进行边界阻断。

        Args:
            text (str): 完整病历文本。

        Returns:
            dict: 键为段落标题，值为段落内容的字典。
        """
        sections = {}
        if not self.section_patterns:
            return sections

        sorted_patterns = sorted(self.section_patterns, key=len, reverse=True)
        pattern_str = r"【?(" + "|".join(sorted_patterns) + r")】?\s*[:：]"

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
