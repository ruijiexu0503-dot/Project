"""Trainable sparse QKV interfaces; no training loop or Pilot fitting here."""
from __future__ import annotations
import math
import torch
from torch import nn


class SparseEdgeSetAttention(nn.Module):
    """Residual Edge-Edge attention over caller-supplied legal neighborhoods."""
    def __init__(self, edge_dim=2048, hidden_dim=128):
        super().__init__()
        self.input = nn.Linear(edge_dim, hidden_dim, bias=False)
        self.q = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.k = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.v = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.output = nn.Linear(hidden_dim, edge_dim, bias=False)
        self.gate = nn.Sequential(nn.Linear(hidden_dim, 1), nn.Sigmoid())
        self.norm = nn.LayerNorm(hidden_dim)

    def forward(self, edges, neighbor_edges, neighbor_mask):
        """edges [B,D], neighbor_edges [B,N,D], mask [B,N] bool."""
        z = self.norm(self.input(edges)); nz = self.norm(self.input(neighbor_edges))
        logits = (self.q(z).unsqueeze(1) * self.k(nz)).sum(-1) / math.sqrt(z.shape[-1])
        logits = logits.masked_fill(~neighbor_mask, float('-inf'))
        weights = torch.softmax(logits, dim=1)
        # A caller must supply at least one legal neighbor (self can be added).
        context = (weights.unsqueeze(-1) * self.v(nz)).sum(1)
        return edges + self.gate(z) * self.output(context), weights


class QueryEdgeRouter(nn.Module):
    """Q from query/source; K,V from updated edge/target; explicit NO_EXPAND."""
    def __init__(self, node_dim=1024, edge_dim=2048, hidden_dim=128):
        super().__init__()
        self.query = nn.Sequential(nn.Linear(3 * node_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.GELU())
        self.key = nn.Sequential(nn.Linear(edge_dim + node_dim, hidden_dim), nn.LayerNorm(hidden_dim))
        self.value = nn.Sequential(nn.Linear(edge_dim + node_dim, hidden_dim), nn.LayerNorm(hidden_dim))
        self.no_expand_key = nn.Parameter(torch.zeros(hidden_dim))
        self.no_expand_value = nn.Parameter(torch.zeros(hidden_dim))

    def forward(self, query, source, edges, targets, valid_mask):
        """Return edge logits, attention weights incl. NO_EXPAND, and values."""
        q = self.query(torch.cat((query, source, query - source), dim=-1))
        features = torch.cat((edges, targets), dim=-1)
        keys, values = self.key(features), self.value(features)
        logits = (q.unsqueeze(1) * keys).sum(-1) / math.sqrt(q.shape[-1])
        logits = logits.masked_fill(~valid_mask, float('-inf'))
        no_expand = (q * self.no_expand_key).sum(-1, keepdim=True) / math.sqrt(q.shape[-1])
        all_logits = torch.cat((logits, no_expand), dim=1)
        attention = torch.softmax(all_logits, dim=1)
        return logits, attention, values


def marginal_page_retrieval_loss(edge_logits, valid_mask, target_is_gold):
    """Listwise page supervision with a NO_EXPAND target for no-gold pools.

    `target_is_gold` must be derived only from an isolated training split.
    """
    no_expand = torch.zeros((edge_logits.shape[0], 1), device=edge_logits.device, dtype=edge_logits.dtype)
    all_logits = torch.cat((edge_logits.masked_fill(~valid_mask, float('-inf')), no_expand), dim=1)
    denom = torch.logsumexp(all_logits, dim=1)
    positives = edge_logits.masked_fill(~(valid_mask & target_is_gold), float('-inf'))
    has_gold = (valid_mask & target_is_gold).any(dim=1)
    numerator = torch.where(has_gold, torch.logsumexp(positives, dim=1), no_expand.squeeze(1))
    return (denom - numerator).mean()
