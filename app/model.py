"""
模块名称：神经网络架构模块
功能描述：定义用于命名实体识别 (NER) 的核心 PyTorch 模型结构。
         本模块实现了基于 RoPE (旋转位置编码) 的 GlobalPointer 网络，
         专门用于解决医疗文本中常见的实体嵌套问题。
"""

import torch
import torch.nn as nn


class GlobalPointer(nn.Module):
    """
    GlobalPointer 实体识别解码头。

    通过计算输入序列中任意两个 Token 之间的关联概率，直接预测实体的起始和终止位置。
    内置 RoPE 旋转位置编码以增强模型对相对位置的感知能力。
    """

    def __init__(
        self,
        encoder: nn.Module,
        ent_type_size: int,
        inner_dim: int = 64,
        device: str = "cpu",
    ):
        """
        初始化 GlobalPointer 网络。

        Args:
            encoder (nn.Module): 预训练的语言模型编码器（如 MacBERT）。
            ent_type_size (int): 需要识别的实体类别总数。
            inner_dim (int): 内部投影的维度大小，默认为 64。
            device (str): 运行设备标识 ('cpu' 或 'cuda')。
        """
        super().__init__()
        self.encoder = encoder
        self.ent_type_size = ent_type_size
        self.inner_dim = inner_dim
        self.device = device
        self.hidden_size = encoder.config.hidden_size

        # 将 BERT 的隐藏层输出映射到 Query 和 Key 所需的维度
        self.dense = nn.Linear(self.hidden_size, ent_type_size * inner_dim * 2)

    def sinusoidal_position_embedding(
        self, batch_size: int, seq_len: int, output_dim: int
    ) -> torch.Tensor:
        """
        生成正弦绝对位置编码。

        Args:
            batch_size (int): 批次大小。
            seq_len (int): 序列长度。
            output_dim (int): 输出维度。

        Returns:
            torch.Tensor: 形状为 (1, seq_len, output_dim) 的位置编码张量。
        """
        position_ids = torch.arange(0, seq_len, dtype=torch.float).unsqueeze(-1)
        indices = torch.arange(0, output_dim // 2, dtype=torch.float)
        indices = torch.pow(10000, -2 * indices / output_dim)
        embeddings = position_ids * indices
        embeddings = torch.stack([torch.sin(embeddings), torch.cos(embeddings)], dim=-1)
        return embeddings.view(1, seq_len, output_dim).to(self.device)

    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        """
        模型前向传播。

        Args:
            input_ids (torch.Tensor): 输入序列的 Token ID。
            attention_mask (torch.Tensor): 注意力掩码，区分有效文本与 Padding。

        Returns:
            torch.Tensor: 形状为 (batch_size, ent_type_size, seq_len, seq_len) 的打分矩阵 (Logits)。
        """
        context_outputs = self.encoder(input_ids, attention_mask)
        last_hidden_state = context_outputs.last_hidden_state
        batch_size, seq_len = last_hidden_state.size(0), last_hidden_state.size(1)

        outputs = self.dense(last_hidden_state)
        outputs = torch.split(outputs, self.inner_dim * 2, dim=-1)
        outputs = torch.stack(outputs, dim=-2)
        qw, kw = outputs[..., : self.inner_dim], outputs[..., self.inner_dim :]

        # 注入 RoPE 旋转位置编码
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

        # 计算内积，得到任意两点间的关联得分
        logits = torch.einsum("bmhd,bnhd->bhmn", qw, kw)
        logits = logits / self.inner_dim**0.5

        # 排除 Padding 部分的干扰
        pad_mask = attention_mask.unsqueeze(1).unsqueeze(1)
        logits = logits * pad_mask - (1 - pad_mask) * 1e4

        # 排除下三角部分的无效计算（实体的终点坐标必须大于等于起点坐标）
        mask = torch.triu(torch.ones_like(logits), diagonal=0)

        return logits - (1 - mask) * 1e4
