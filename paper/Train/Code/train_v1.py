import os
import json
import time
import torch
import numpy as np
import matplotlib.pyplot as plt
from torch.utils.data import DataLoader, Dataset
from torch.optim import AdamW
from transformers import (
    BertTokenizerFast,
    BertModel,
    get_linear_schedule_with_warmup,
)  # 修改点1：使用Fast版本

# ==========================================
# 1. 环境修复与全局配置
# ==========================================
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"


class Config:
    INPUT_DIR = "/kaggle/input/cmeee-v2/cmeee_v2/"
    TRAIN_PATH = os.path.join(INPUT_DIR, "CMeEE-V2_train.json")
    DEV_PATH = os.path.join(INPUT_DIR, "CMeEE-V2_dev.json")
    OUTPUT_DIR = "/kaggle/working/"

    MODEL_NAME = "hfl/chinese-macbert-base"
    MAX_LEN = 128
    BATCH_SIZE = 16
    LR = 2e-5
    EPOCHS = 10
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    CATEGORIES = ["dis", "sym", "dru", "equ", "pro", "bod", "ite", "mic", "dep"]
    CAT2ID = {c: i for i, c in enumerate(CATEGORIES)}


# ==========================================
# 2. 数据处理模块 (已修复 Offset Mapping)
# ==========================================
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
        text = item["text"]
        labels = np.zeros(
            (len(self.config.CATEGORIES), self.config.MAX_LEN, self.config.MAX_LEN)
        )

        # Fast Tokenizer 支持 return_offsets_mapping
        tokenized = self.tokenizer(
            text,
            max_length=self.config.MAX_LEN,
            truncation=True,
            padding="max_length",
            return_offsets_mapping=True,
        )

        offsets = tokenized["offset_mapping"]
        for ent in item.get("entities", []):
            start, end, label = ent["start_idx"], ent["end_idx"], ent["type"]
            if label not in self.config.CAT2ID:
                continue

            s_idx, e_idx = -1, -1
            for i, offset in enumerate(offsets):
                # 只有 Fast Tokenizer 能准确返回这些元组
                if offset[0] == start and offset[0] != offset[1]:
                    s_idx = i
                if offset[1] == end and offset[0] != offset[1]:
                    e_idx = i

            if s_idx != -1 and e_idx != -1:
                labels[self.config.CAT2ID[label], s_idx, e_idx] = 1

        return {
            "input_ids": torch.tensor(tokenized["input_ids"]),
            "attention_mask": torch.tensor(tokenized["attention_mask"]),
            "labels": torch.tensor(labels, dtype=torch.float32),
        }


# ==========================================
# 3. 模型定义 (GlobalPointer)
# ==========================================
class GlobalPointer(torch.nn.Module):
    def __init__(self, encoder, ent_type_size, inner_dim=64):
        super().__init__()
        self.encoder = encoder
        self.dense = torch.nn.Linear(
            encoder.config.hidden_size, ent_type_size * inner_dim * 2
        )
        self.inner_dim = inner_dim

    def forward(self, input_ids, attention_mask, token_type_ids=None):
        outputs = self.encoder(input_ids, attention_mask, token_type_ids)
        last_hidden_state = outputs.last_hidden_state
        inputs = self.dense(last_hidden_state)
        inputs = torch.split(inputs, self.inner_dim * 2, dim=-1)
        inputs = torch.stack(inputs, dim=-2)
        qw, kw = inputs[..., : self.inner_dim], inputs[..., self.inner_dim :]
        logits = torch.einsum("bmhd,bnhd->bhmn", qw, kw)
        pad_mask = attention_mask.unsqueeze(1).unsqueeze(1)
        logits = logits * pad_mask - (1 - pad_mask) * 1e12
        return logits / self.inner_dim**0.5


# ==========================================
# 4. 损失函数与评估
# ==========================================
def global_pointer_loss(y_pred, y_true):
    shape = y_pred.shape
    y_true = y_true.view(shape[0] * shape[1], -1)
    y_pred = y_pred.view(shape[0] * shape[1], -1)
    y_pred = (1 - 2 * y_true) * y_pred
    y_pred_neg = y_pred - y_true * 1e12
    y_pred_pos = y_pred - (1 - y_true) * 1e12
    zeros = torch.zeros_like(y_pred[..., :1])
    neg_loss = torch.logsumexp(torch.cat([y_pred_neg, zeros], dim=-1), dim=-1)
    pos_loss = torch.logsumexp(torch.cat([y_pred_pos, zeros], dim=-1), dim=-1)
    return (neg_loss + pos_loss).mean()


def evaluate(model, loader):
    model.eval()
    tp, fp, fn = 0, 0, 0
    with torch.no_grad():
        for b in loader:
            ids, mask, y_true = (
                b["input_ids"].to(Config.DEVICE),
                b["attention_mask"].to(Config.DEVICE),
                b["labels"].to(Config.DEVICE),
            )
            y_pred = model(ids, mask)
            y_pred = (y_pred > 0).float()
            tp += (y_pred * y_true).sum().item()
            fp += (y_pred * (1 - y_true)).sum().item()
            fn += ((1 - y_pred) * y_true).sum().item()
    p = tp / (tp + fp + 1e-10)
    r = tp / (tp + fn + 1e-10)
    f1 = 2 * p * r / (p + r + 1e-10)
    return p, r, f1


# ==========================================
# 5. 执行训练
# ==========================================
# 修改点2：使用 Fast 分词器
tokenizer = BertTokenizerFast.from_pretrained(Config.MODEL_NAME)
train_dataset = CMeEEDataset(Config.TRAIN_PATH, tokenizer, Config)
dev_dataset = CMeEEDataset(Config.DEV_PATH, tokenizer, Config)

train_loader = DataLoader(train_dataset, batch_size=Config.BATCH_SIZE, shuffle=True)
dev_loader = DataLoader(dev_dataset, batch_size=Config.BATCH_SIZE)

bert = BertModel.from_pretrained(Config.MODEL_NAME)
model = GlobalPointer(bert, len(Config.CATEGORIES)).to(Config.DEVICE)
optimizer = AdamW(model.parameters(), lr=Config.LR)

best_f1 = 0.0
history = {"loss": [], "f1": []}  # 用于绘图

print(f"[{time.ctime()}] 开始训练流程...")

for epoch in range(Config.EPOCHS):
    model.train()
    epoch_loss = 0
    for step, batch in enumerate(train_loader):
        optimizer.zero_grad()
        ids = batch["input_ids"].to(Config.DEVICE)
        mask = batch["attention_mask"].to(Config.DEVICE)
        labels = batch["labels"].to(Config.DEVICE)

        outputs = model(ids, mask)
        loss = global_pointer_loss(outputs, labels)
        loss.backward()
        optimizer.step()
        epoch_loss += loss.item()

        if step % 100 == 0:
            print(f"  Step {step} | Current Loss: {loss.item():.4f}")

    p, r, f1 = evaluate(model, dev_loader)
    avg_loss = epoch_loss / len(train_loader)
    history["loss"].append(avg_loss)
    history["f1"].append(f1)

    print(f"\n>>> Epoch {epoch+1} 总结:")
    print(f"    平均损失: {avg_loss:.4f}")
    print(f"    精确率: {p:.4f} | 召回率: {r:.4f} | F1得分: {f1:.4f}")
    print("-" * 30)

    if f1 > best_f1:
        best_f1 = f1
        torch.save(
            model.state_dict(), os.path.join(Config.OUTPUT_DIR, "best_ner_model.pt")
        )
        print(f"*** 模型性能提升，已保存最佳权重 ***\n")

print(f"训练圆满完成。最高F1: {best_f1:.4f}")
