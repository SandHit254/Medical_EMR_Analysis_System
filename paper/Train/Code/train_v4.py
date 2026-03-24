import os
import json
import time
import torch
import torch.nn as nn
import numpy as np
from torch.utils.data import DataLoader, Dataset
from torch.optim import AdamW
from transformers import BertTokenizerFast, BertModel
from tqdm import tqdm


# ==========================================
# 1. 统一配置 (Config)
# ==========================================
class Config:
    INPUT_DIR = "/kaggle/input/cmeee-v2/cmeee_v2/"
    TRAIN_PATH = os.path.join(INPUT_DIR, "CMeEE-V2_train.json")
    DEV_PATH = os.path.join(INPUT_DIR, "CMeEE-V2_dev.json")
    OUTPUT_DIR = "/kaggle/working/"

    MODEL_NAME = "hfl/chinese-macbert-base"
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    MAX_LEN = 128
    BATCH_SIZE = 16
    LR = 2e-5
    EPOCHS = 10

    CATEGORIES = ["dis", "sym", "dru", "equ", "pro", "bod", "ite", "mic", "dep"]
    CAT2ID = {c: i for i, c in enumerate(CATEGORIES)}


os.environ["TOKENIZERS_PARALLELISM"] = "false"


# ==========================================
# 2. 稳定版 GlobalPointer (带 RoPE)
# ==========================================
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
        return embeddings.view(1, seq_len, output_dim).to(Config.DEVICE)

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


# ==========================================
# 3. 数据处理 (🔥修复了吞尾Bug🔥)
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

            # 🔥 修复点：只要字符索引落在 offset 区间内即可，完美解决左闭右开问题
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


# ==========================================
# 4. 损失函数与评估函数 (补全版)
# ==========================================
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
            ids, mask, y_t = (
                b["input_ids"].to(Config.DEVICE),
                b["attention_mask"].to(Config.DEVICE),
                b["labels"].to(Config.DEVICE),
            )
            y_p = (model(ids, mask) > 0).float()
            tp += (y_p * y_t).sum().item()
            fp += (y_p * (1 - y_t)).sum().item()
            fn += ((1 - y_p) * y_t).sum().item()
    p = tp / (tp + fp + 1e-10)
    r = tp / (tp + fn + 1e-10)
    f1 = 2 * p * r / (p + r + 1e-10)
    return p, r, f1


# ==========================================
# 5. 训练循环
# ==========================================
if __name__ == "__main__":
    print(">>> 正在初始化模型与数据...")
    tokenizer = BertTokenizerFast.from_pretrained(Config.MODEL_NAME)
    train_loader = DataLoader(
        CMeEEDataset(Config.TRAIN_PATH, tokenizer, Config),
        batch_size=Config.BATCH_SIZE,
        shuffle=True,
    )
    dev_loader = DataLoader(
        CMeEEDataset(Config.DEV_PATH, tokenizer, Config), batch_size=Config.BATCH_SIZE
    )

    bert = BertModel.from_pretrained(Config.MODEL_NAME)
    model = GlobalPointer(bert, len(Config.CATEGORIES)).to(Config.DEVICE)
    optimizer = AdamW(model.parameters(), lr=Config.LR)

    best_f1 = 0.0
    print(f"[{time.ctime()}] 🚀 开始全新训练 (修复数据对齐Bug版)...")

    for epoch in range(Config.EPOCHS):
        model.train()
        total_loss = 0
        pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}")

        for batch in pbar:
            optimizer.zero_grad()
            ids, mask, lbls = (
                batch["input_ids"].to(Config.DEVICE),
                batch["attention_mask"].to(Config.DEVICE),
                batch["labels"].to(Config.DEVICE),
            )

            y_pred = model(ids, mask)
            loss = global_pointer_loss(y_pred, lbls)

            if torch.isnan(loss) or loss > 1e6:
                print(f"Skipping unstable batch, Loss: {loss.item()}")
                continue

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item()
            pbar.set_postfix({"loss": f"{loss.item():.2f}"})

        # 跑完一个Epoch后评估
        avg_loss = total_loss / len(train_loader)
        p, r, f1 = evaluate(model, dev_loader)

        print(f"\n✅ Epoch {epoch+1} 总结:")
        print(f"   平均 Loss: {avg_loss:.4f}")
        print(f"   精确率(P): {p:.4f} | 召回率(R): {r:.4f} | F1得分: {f1:.4f}")

        # 保存最佳模型
        if f1 > best_f1:
            best_f1 = f1
            torch.save(
                model.state_dict(),
                os.path.join(Config.OUTPUT_DIR, "best_ner_model2.pt"),
            )
            print(f"   🌟 性能提升！已保存新权重: best_ner_model2.pt")
        print("-" * 40)

    print(f"\n🎉 训练完毕！最高 F1: {best_f1:.4f}")
