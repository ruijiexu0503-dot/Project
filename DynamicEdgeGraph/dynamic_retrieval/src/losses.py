"""Masked, query-grouped losses for dynamic retrieval."""
from __future__ import annotations

from typing import Any, Dict, Optional

import torch
import torch.nn.functional as F
from torch import Tensor


def _bool_mask(name: str, value: Tensor, shape: torch.Size) -> None:
    if value.dtype != torch.bool:
        raise TypeError(f"{name} must be bool")
    if value.shape != shape:
        raise ValueError(f"{name} has shape {tuple(value.shape)}, expected {tuple(shape)}")


def multi_positive_ranking_loss(
    scores: Tensor,
    positive_mask: Tensor,
    negative_mask: Tensor,
    temperature: float = 1.0,
    *,
    candidate_mask: Optional[Tensor] = None,
    query_group_id: Optional[Tensor] = None,
) -> tuple[Tensor, Dict[str, Any]]:
    """Compute per-positive loss, averaged by state and then query group.

    Empty P/N states return differentiable zero and are excluded; they never
    create an implicit stop or NO_EXPAND target.
    """
    if scores.ndim != 2:
        raise ValueError("scores must have shape [B,C]")
    _bool_mask("positive_mask", positive_mask, scores.shape)
    _bool_mask("negative_mask", negative_mask, scores.shape)
    if not isinstance(temperature, (int, float)) or temperature <= 0:
        raise ValueError("temperature must be a finite positive number")
    if not torch.isfinite(torch.tensor(float(temperature))):
        raise ValueError("temperature must be a finite positive number")
    if (positive_mask & negative_mask).any():
        raise ValueError("positive_mask and negative_mask must be disjoint")

    if candidate_mask is None:
        candidate_mask = torch.ones_like(positive_mask)
    _bool_mask("candidate_mask", candidate_mask, scores.shape)
    if ((positive_mask | negative_mask) & ~candidate_mask).any():
        raise ValueError("P/N labels must be subsets of candidate_mask")
    if scores[candidate_mask].numel() and not torch.isfinite(scores[candidate_mask]).all():
        raise ValueError("scores contain non-finite values for valid candidates")

    batch = scores.shape[0]
    if query_group_id is None:
        query_group_id = torch.arange(batch, device=scores.device)
    if query_group_id.ndim != 1 or query_group_id.shape[0] != batch:
        raise ValueError("query_group_id must have shape [B]")

    has_p = positive_mask.any(-1)
    has_n = negative_mask.any(-1)
    valid = has_p & has_n
    if not valid.any():
        zero = scores[candidate_mask].sum() * 0.0
        return zero, {
            "valid_states": 0,
            "skipped_states": batch,
            "skipped_no_positive": int((~has_p).sum().item()),
            "skipped_no_negative": int((~has_n).sum().item()),
            "valid_query_groups": 0,
            "optimizer_step_allowed": False,
        }

    scaled = scores / float(temperature)
    neg_lse = torch.logsumexp(scaled.masked_fill(~negative_mask, -torch.inf), dim=-1)
    # Do not evaluate arithmetic on padding/unknown scores: NaN * 0 is still NaN.
    positive_scores = torch.where(positive_mask, scaled, torch.zeros_like(scaled))
    per_positive = torch.logaddexp(
        torch.zeros_like(positive_scores), neg_lse.unsqueeze(-1) - positive_scores
    )
    state_loss = (per_positive * positive_mask.to(per_positive.dtype)).sum(-1)
    state_loss = state_loss / positive_mask.sum(-1).clamp_min(1)

    valid_losses = state_loss[valid]
    valid_groups = query_group_id[valid]
    group_losses = []
    for group in torch.unique(valid_groups, sorted=True):
        group_losses.append(valid_losses[valid_groups == group].mean())
    loss = torch.stack(group_losses).mean()
    return loss, {
        "valid_states": int(valid.sum().item()),
        "skipped_states": int((~valid).sum().item()),
        "skipped_no_positive": int((~has_p).sum().item()),
        "skipped_no_negative": int((~has_n).sum().item()),
        "valid_query_groups": len(group_losses),
        "optimizer_step_allowed": True,
    }


def masked_auxiliary_cross_entropy(
    logits: Tensor, labels: Tensor, label_mask: Tensor
) -> tuple[Tensor, Dict[str, int]]:
    """Cross entropy where unknown auxiliary labels are truly absent."""
    if logits.ndim != 3 or labels.shape != logits.shape[:2]:
        raise ValueError("expected logits [B,C,K] and labels [B,C]")
    _bool_mask("label_mask", label_mask, labels.shape)
    if label_mask.any():
        selected_logits = logits[label_mask]
        selected_labels = labels[label_mask]
        if (selected_labels < 0).any() or (selected_labels >= logits.shape[-1]).any():
            raise ValueError("auxiliary label out of range")
        if not torch.isfinite(selected_logits).all():
            raise ValueError("effective auxiliary logits must be finite")
        return F.cross_entropy(selected_logits, selected_labels), {
            "valid_labels": int(label_mask.sum().item())
        }
    return logits.sum() * 0.0, {"valid_labels": 0}
