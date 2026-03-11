"""
模块名称：神经认知层独立微调脚本 (NER Fine-tuning Pipeline)
功能描述：负责挂载 CMeEE-V2 等中文医疗实体数据集，初始化 MacBERT + GlobalPointer 模型架构，
         执行张量运算、混合精度计算、梯度反向传播、性能评估及最佳权重落盘的全生命周期管理。

执行方式：
    本文件可作为独立脚本运行 `python app/train.py`，产出的模型权重将自动归档至项目 models/ 目录。
"""

import os
import json
import time
import logging
import torch
import torch.nn as nn
import numpy as np
from torch.utils.data import DataLoader, Dataset
from torch.optim import AdamW
from transformers import BertTokenizerFast, BertModel
from tqdm import tqdm

# 配置全局日志记录器
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

os.environ["TOKENIZERS_PARALLELISM"] = "false"


# =====================================================================
# 1. 训练环境与超参数配置 (Training Configuration)
# =====================================================================
class TrainConfig:
    """
    模型训练全局配置类。
    定义了物理路径寻址、算力设备分配、网络超参数与业务实体标签体系。
    """

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data", "cmeee_v2")
    OUTPUT_DIR = os.path.join(BASE_DIR, "models")

    TRAIN_PATH = os.path.join(DATA_DIR, "CMeEE-V2_train.json")
    DEV_PATH = os.path.join(DATA_DIR, "CMeEE-V2_dev.json")

    MODEL_NAME = "hfl/chinese-macbert-base"
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    MAX_LEN = 128
    BATCH_SIZE = 16
    LR = 2e-5
    EPOCHS = 10

    CATEGORIES = ["dis", "sym", "dru", "equ", "pro", "bod", "ite", "mic", "dep"]
    CAT2ID = {c: i for i, c in enumerate(CATEGORIES)}


# (后续类 GlobalPointer, CMeEEDataset, train_loop 与之前完全一致，此处已优化标准缩进)
# =====================================================================
class GlobalPointer(nn.Module):
    def __init__(self, encoder, ent_type_size, inner_dim=64):
        super().__init__()
        self.encoder = encoder
        self.ent_type_size = ent_type_size
        self.inner_dim = inner_dim
        self.hidden_size = encoder.config.hidden_size
        self.dense = nn.Linear(self.hidden_size, ent_type_size * inner_dim * 2)
        nn.init.xavier_uniform_(self.dense.weight)

    def sinusoidal_position_embedding(self, batch_size, seq_len, output_dim):
        position_ids = torch.arange(0, seq_len, dtype=torch.float).unsqueeze(-1)
        indices = torch.arange(0, output_dim // 2, dtype=torch.float)
        indices = torch.pow(10000, -2 * indices / output_dim)
        embeddings = position_ids * indices
        embeddings = torch.stack([torch.sin(embeddings), torch.cos(embeddings)], dim=-1)
        return embeddings.view(1, seq_len, output_dim).to(TrainConfig.DEVICE)

    def forward(self, input_ids, attention_mask):
        context_outputs = self.encoder(input_ids, attention_mask)
        last_hidden_state = context_outputs.last_hidden_state
        batch_size, seq_len = last_hidden_state.size(0), last_hidden_state.size(1)
        outputs = self.dense(last_hidden_state)
        outputs = torch.split(outputs, self.inner_dim * 2, dim=-1)
        outputs = torch.stack(outputs, dim=-2)
        qw, kw = outputs[..., : self.inner_dim], outputs[..., self.inner_dim :]
        pos_emb = self.sinusoidal_position_embedding(
            batch_size, seq_len, self.inner_dim
        )
        cos_pos = pos_emb[..., 1::2].repeat_interleave(2, dim=-1).unsqueeze(-2)
        sin_pos = pos_emb[..., ::2].repeat_interleave(2, dim=-1).unsqueeze(-2)

        def rotate_half(x):
            x1, x2 = x[..., : self.inner_dim // 2], x[..., self.inner_dim // 2 :]
            return torch.cat((-x2, x1), dim=-1)

        qw = (qw * cos_pos) + (rotate_half(qw) * sin_pos)
        kw = (kw * cos_pos) + (rotate_half(kw) * sin_pos)
        logits = torch.einsum("bmhd,bnhd->bhmn", qw, kw)
        logits = logits / self.inner_dim**0.5
        pad_mask = attention_mask.unsqueeze(1).unsqueeze(1)
        logits = logits * pad_mask - (1 - pad_mask) * 1e4
        mask = torch.triu(torch.ones_like(logits), diagonal=0)
        logits = logits - (1 - mask) * 1e4
        return logits


class CMeEEDataset(Dataset):
    def __init__(self, path, tokenizer, config):
        with open(path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.tokenizer = tokenizer
        self.config = config

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]
        tokenized = self.tokenizer(
            item["text"],
            max_length=self.config.MAX_LEN,
            truncation=True,
            padding="max_length",
            return_offsets_mapping=True,
        )
        input_ids = torch.tensor(tokenized["input_ids"])
        attention_mask = torch.tensor(tokenized["attention_mask"])
        offsets = tokenized["offset_mapping"]
        labels = np.zeros(
            (len(self.config.CATEGORIES), self.config.MAX_LEN, self.config.MAX_LEN)
        )
        for ent in item.get("entities", []):
            if ent["type"] not in self.config.CAT2ID:
                continue
            s_idx = next(
                (i for i, o in enumerate(offsets) if o[0] <= ent["start_idx"] < o[1]),
                -1,
            )
            e_idx = next(
                (i for i, o in enumerate(offsets) if o[0] <= ent["end_idx"] < o[1]), -1
            )
            if s_idx != -1 and e_idx != -1 and s_idx <= e_idx:
                if attention_mask[s_idx] == 1 and attention_mask[e_idx] == 1:
                    labels[self.config.CAT2ID[ent["type"]], s_idx, e_idx] = 1
        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "labels": torch.tensor(labels, dtype=torch.float32),
        }


def global_pointer_loss(y_pred, y_true):
    shape = y_pred.shape
    y_true = y_true.view(shape[0] * shape[1], -1)
    y_pred = y_pred.view(shape[0] * shape[1], -1)
    y_pred = (1 - 2 * y_true) * y_pred
    y_pred_neg = y_pred - y_true * 1e4
    y_pred_pos = y_pred - (1 - y_true) * 1e4
    zeros = torch.zeros_like(y_pred[..., :1])
    neg_loss = torch.logsumexp(torch.cat([y_pred_neg, zeros], dim=-1), dim=-1)
    pos_loss = torch.logsumexp(torch.cat([y_pred_pos, zeros], dim=-1), dim=-1)
    return (neg_loss + pos_loss).mean()


def evaluate(model, loader):
    model.eval()
    tp, fp, fn = 0, 0, 0
    with torch.no_grad():
        for b in loader:
            ids = b["input_ids"].to(TrainConfig.DEVICE)
            mask = b["attention_mask"].to(TrainConfig.DEVICE)
            y_t = b["labels"].to(TrainConfig.DEVICE)
            y_p = (model(ids, mask) > 0).float()
            tp += (y_p * y_t).sum().item()
            fp += (y_p * (1 - y_t)).sum().item()
            fn += ((1 - y_p) * y_t).sum().item()
    p = tp / (tp + fp + 1e-10)
    r = tp / (tp + fn + 1e-10)
    f1 = 2 * p * r / (p + r + 1e-10)
    return p, r, f1


def start_training():
    logger.info("=" * 50)
    logger.info(f"初始化医疗 NER 神经认知微调管线")
    logger.info(
        f"分配算力设备: {TrainConfig.DEVICE} | Batch Size: {TrainConfig.BATCH_SIZE}"
    )
    logger.info("=" * 50)

    os.makedirs(TrainConfig.OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(TrainConfig.TRAIN_PATH):
        logger.error(f"训练集缺失，请检查路径: {TrainConfig.TRAIN_PATH}")
        return

    logger.info("正在挂载 Tokenizer 与切分数据集...")
    tokenizer = BertTokenizerFast.from_pretrained(TrainConfig.MODEL_NAME)
    train_loader = DataLoader(
        CMeEEDataset(TrainConfig.TRAIN_PATH, tokenizer, TrainConfig),
        batch_size=TrainConfig.BATCH_SIZE,
        shuffle=True,
    )
    dev_loader = DataLoader(
        CMeEEDataset(TrainConfig.DEV_PATH, tokenizer, TrainConfig),
        batch_size=TrainConfig.BATCH_SIZE,
    )

    logger.info("正在装载 MacBERT 预训练基座与 GlobalPointer 头部特征...")
    bert = BertModel.from_pretrained(TrainConfig.MODEL_NAME)
    model = GlobalPointer(bert, len(TrainConfig.CATEGORIES)).to(TrainConfig.DEVICE)
    optimizer = AdamW(model.parameters(), lr=TrainConfig.LR)

    best_f1 = 0.0
    logger.info(f"🚀 开始全新微调流转...")

    for epoch in range(TrainConfig.EPOCHS):
        model.train()
        total_loss = 0
        pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{TrainConfig.EPOCHS}")

        for batch in pbar:
            optimizer.zero_grad()
            ids = batch["input_ids"].to(TrainConfig.DEVICE)
            mask = batch["attention_mask"].to(TrainConfig.DEVICE)
            lbls = batch["labels"].to(TrainConfig.DEVICE)

            y_pred = model(ids, mask)
            loss = global_pointer_loss(y_pred, lbls)

            if torch.isnan(loss) or loss > 1e6:
                logger.warning(f"跳过不稳定张量批次, 当前 Loss: {loss.item()}")
                continue

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item()
            pbar.set_postfix({"loss": f"{loss.item():.4f}"})

        avg_loss = total_loss / len(train_loader)
        p, r, f1 = evaluate(model, dev_loader)

        logger.info(
            f"✅ Epoch {epoch+1} 总结: 平均 Loss: {avg_loss:.4f} | 精确率(P): {p:.4f} | 召回率(R): {r:.4f} | F1: {f1:.4f}"
        )

        if f1 > best_f1:
            best_f1 = f1
            save_path = os.path.join(TrainConfig.OUTPUT_DIR, "ner_model.pt")
            torch.save(model.state_dict(), save_path)
            logger.info(f"🌟 检测到性能提升！已保存最新权重至: {save_path}")

    logger.info("=" * 50)
    logger.info(f"🎉 管线微调完毕！历史最高 F1 阈值: {best_f1:.4f}")


if __name__ == "__main__":
    start_training()
