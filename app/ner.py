"""
模块名称：命名实体识别 (NER) 推理引擎模块
功能描述：负责加载预训练的 BERT 语言模型与 GlobalPointer 权重，
         对输入的切片文本进行特征编码与实体解码。
"""

import torch
import os
from transformers import BertTokenizerFast, BertModel
from app.model import GlobalPointer
from app.config_manager import ConfigManager


class NEREngine:
    """医疗实体抽取推理核心类"""

    def __init__(self):
        """
        初始化 NER 引擎。
        从配置管理中心读取硬件设置、模型参数、标签映射字典，并完成权重加载。
        """
        sys_cfg = ConfigManager().get_section("system")
        ner_cfg = ConfigManager().get_section("ner")

        # 硬件调度逻辑
        device_str = sys_cfg.get("device", "cpu")
        self.device = torch.device(device_str if torch.cuda.is_available() else "cpu")

        # 模型参数装载
        self.max_len = ner_cfg.get("max_len", 128)
        self.threshold = ner_cfg.get("inference_threshold", 0.0)
        self.categories = ner_cfg.get("categories", [])
        self.id2label = ner_cfg.get("id2label", {})

        bert_path = ner_cfg.get("bert_pretrain_path")
        model_path = ner_cfg.get("checkpoint_path")

        # 初始化分词器与编码器
        self.tokenizer = BertTokenizerFast.from_pretrained(bert_path)
        bert = BertModel.from_pretrained(bert_path)

        # 初始化自定义 GlobalPointer 头
        self.model = GlobalPointer(
            encoder=bert,
            ent_type_size=len(self.categories),
            inner_dim=ner_cfg.get("inner_dim", 64),
            device=self.device,
        )

        # 加载微调权重并设定为评估模式
        if os.path.exists(model_path):
            self.model.load_state_dict(torch.load(model_path, map_location=self.device))
        self.model.to(self.device).eval()

    def predict_chunk(self, text: str) -> list:
        """
        对单句短文本进行实体抽取推理。

        Args:
            text (str): 长度受限于 max_len 的待处理短句。

        Returns:
            list: 包含实体字典的列表，字典结构包含文本、类型、置信度以及起止坐标。
        """
        if not text:
            return []

        # 分词并返回字符级偏移量映射，用于准确截取原文
        tokenized = self.tokenizer(
            text,
            max_length=self.max_len,
            truncation=True,
            return_offsets_mapping=True,
            return_tensors="pt",
        )

        input_ids = tokenized["input_ids"].to(self.device)
        mask = tokenized["attention_mask"].to(self.device)
        offsets = tokenized["offset_mapping"][0].tolist()

        # 冻结梯度进行推理
        with torch.no_grad():
            logits = self.model(input_ids, mask)[0]
            scores = torch.where(logits > self.threshold)

        entities = []
        for cat_id, start_idx, end_idx in zip(*scores):
            cat_id, start_idx, end_idx = cat_id.item(), start_idx.item(), end_idx.item()

            # 过滤超出偏移量映射边界的异常预测
            if start_idx >= len(offsets) or end_idx >= len(offsets):
                continue

            char_start, char_end = offsets[start_idx][0], offsets[end_idx][1]
            # 过滤无效或长度为 0 的空白预测
            if char_end - char_start < 1:
                continue

            # 类别索引转换为自然语言标签
            cat_name = self.categories[cat_id]
            entities.append(
                {
                    "text": text[char_start:char_end],
                    "type": self.id2label.get(cat_name, cat_name),
                    "score": float(logits[cat_id, start_idx, end_idx]),
                    "start": char_start,
                    "end": char_end,
                }
            )

        return entities
