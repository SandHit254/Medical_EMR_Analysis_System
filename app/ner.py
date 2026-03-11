"""
模块名称：命名实体识别 (NER) 推理引擎模块
功能描述：负责加载预训练的 BERT 语言模型与 GlobalPointer 权重，
         对输入的切片文本进行张量特征编码与实体解码。
"""

import torch
import os
import logging
from transformers import BertTokenizerFast, BertModel
from app.model import GlobalPointer
from app.config_manager import ConfigManager
from app.exceptions import NERModelError

logger = logging.getLogger(__name__)


class NEREngine:
    """医疗实体抽取推理核心类"""

    def __init__(self):
        """
        初始化 NER 引擎。
        从配置管理中心读取硬件调度策略、模型参数、标签映射字典，并完成权重加载至指定算力设备。

        Raises:
            NERModelError: 当模型权重文件缺失或格式不匹配时抛出。
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

        # 寻址绝对路径
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.isabs(model_path):
            model_path = os.path.join(base_dir, model_path)

        if not os.path.exists(model_path):
            raise NERModelError(
                f"严重阻断：NER 权重文件缺失 [{model_path}]，请先运行 train.py 进行微调。"
            )

        try:
            self.tokenizer = BertTokenizerFast.from_pretrained(bert_path)
            bert = BertModel.from_pretrained(bert_path)
            self.model = GlobalPointer(bert, len(self.categories), device=self.device)
            self.model.load_state_dict(
                torch.load(model_path, map_location=self.device, weights_only=True)
            )
            self.model.to(self.device)
            self.model.eval()
        except Exception as e:
            raise NERModelError(f"模型装载失败，张量或架构不匹配: {str(e)}")

    def predict_chunk(self, text: str) -> list:
        """
        对单一切片文本进行实体提取推理。

        Args:
            text (str): 长度不超过 max_len 的待推理中文字符串。

        Returns:
            list: 包含提取出实体的字典列表，结构如：
                  [{"text": "高血压", "type": "疾病", "start": 0, "end": 3, "score": 0.98}, ...]
        """
        # 【算力优化】：空文本短路拦截
        if not text or not text.strip():
            return []

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

        # 冻结梯度进行推理，释放显存
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

            cat_name = self.id2label.get(
                self.categories[cat_id], self.categories[cat_id]
            )
            entities.append(
                {
                    "text": text[char_start:char_end],
                    "type": cat_name,
                    "start": char_start,
                    "end": char_end,
                    "score": round(logits[cat_id, start_idx, end_idx].item(), 4),
                }
            )

        return entities
