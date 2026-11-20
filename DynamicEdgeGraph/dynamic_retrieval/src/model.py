"""Query/state-conditioned directed-edge ranker for network_v2_build_20261117.

There are no node, document, or edge ID embeddings. The model consumes frozen
representations and legal routes prepared by the caller; Gold labels are never
model inputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import torch
from torch import Tensor, nn


NETWORK_VERSION = "network_v2_build_20261117"
ROUTE_FEATURE_DIM = 12


@dataclass(frozen=True)
class DynamicEdgeConfig:
    """Serializable architecture configuration."""

    input_dim: int
    context_dim: Optional[int] = None
    dim: int = 256
    hidden: int = 512
    dropout: float = 0.1
    output_k: int = 5
    edge_feature_dim: int = ROUTE_FEATURE_DIM
    enable_a_head: bool = False
    enable_e_head: bool = False
    view_mode: str = "split_views"
    network_version: str = NETWORK_VERSION

    def __post_init__(self) -> None:
        if self.input_dim <= 0 or (self.context_dim is not None and self.context_dim <= 0):
            raise ValueError("input dimensions must be positive")
        if self.dim <= 0 or self.hidden <= 0 or self.output_k <= 0:
            raise ValueError("dim, hidden, and output_k must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.edge_feature_dim != ROUTE_FEATURE_DIM:
            raise ValueError(f"route features must use the frozen {ROUTE_FEATURE_DIM}-D schema")
        if self.view_mode not in {"split_views", "joint_legacy"}:
            raise ValueError("view_mode must be split_views or joint_legacy")
        if self.network_version != NETWORK_VERSION:
            raise ValueError(f"unsupported network version: {self.network_version}")

    @property
    def resolved_context_dim(self) -> int:
        return self.input_dim if self.context_dim is None else self.context_dim


def _mlp(in_dim: int, hidden: int, out_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(in_dim, hidden), nn.GELU(), nn.Dropout(dropout), nn.Linear(hidden, out_dim)
    )


def _require_bool(name: str, value: Tensor, shape: torch.Size) -> None:
    if value.dtype != torch.bool:
        raise TypeError(f"{name} must be bool")
    if value.shape != shape:
        raise ValueError(f"{name} has shape {tuple(value.shape)}, expected {tuple(shape)}")


def _require_finite(name: str, value: Tensor, mask: Optional[Tensor] = None) -> None:
    inspected = value if mask is None else value[mask]
    if inspected.numel() and not torch.isfinite(inspected).all():
        raise ValueError(f"{name} contains non-finite values in an effective position")


class DynamicEdgeRanker(nn.Module):
    """Small directed-edge scorer with query and selected-set conditioning."""

    def __init__(
        self,
        input_dim: Optional[int] = None,
        edge_feature_dim: int = ROUTE_FEATURE_DIM,
        dim: int = 256,
        hidden: int = 512,
        dropout: float = 0.1,
        *,
        context_dim: Optional[int] = None,
        output_k: int = 5,
        enable_a_head: bool = False,
        enable_e_head: bool = False,
        view_mode: str = "split_views",
        config: Optional[DynamicEdgeConfig] = None,
    ) -> None:
        super().__init__()
        if config is None:
            if input_dim is None:
                raise ValueError("input_dim or config is required")
            config = DynamicEdgeConfig(
                input_dim=input_dim,
                context_dim=context_dim,
                dim=dim,
                hidden=hidden,
                dropout=dropout,
                output_k=output_k,
                edge_feature_dim=edge_feature_dim,
                enable_a_head=enable_a_head,
                enable_e_head=enable_e_head,
                view_mode=view_mode,
            )
        elif input_dim is not None:
            raise ValueError("pass either config or input_dim, not both")
        self.config = config
        self.dim = config.dim
        self.edge_feature_dim = config.edge_feature_dim

        # P is shared by query, selected content, targets, and route sources.
        self.content_project = nn.Sequential(
            nn.Linear(config.input_dim, config.dim), nn.LayerNorm(config.dim)
        )
        self.context_project = nn.Sequential(
            nn.Linear(config.resolved_context_dim, config.dim), nn.LayerNorm(config.dim)
        )
        self.empty_state = nn.Parameter(torch.zeros(config.dim))
        self.state_mlp = _mlp(2 * config.dim + 1, config.hidden, config.dim, config.dropout)
        self.state_norm = nn.LayerNorm(config.dim)
        self.edge_base = _mlp(
            4 * config.dim + config.edge_feature_dim,
            config.hidden,
            config.dim,
            config.dropout,
        )
        self.state_to_edge = nn.Linear(config.dim, config.dim, bias=False)
        self.edge_update = _mlp(3 * config.dim, config.hidden, config.dim, config.dropout)
        self.edge_norm = nn.LayerNorm(config.dim)
        self.rank_mlp = _mlp(7 * config.dim + 4, config.hidden, 1, config.dropout)
        self.a_head = nn.Linear(config.hidden, 3) if config.enable_a_head else None
        self.e_head = nn.Linear(config.hidden, 4) if config.enable_e_head else None

    @property
    def project(self) -> nn.Sequential:
        """Compatibility alias for the shared content projection P."""
        return self.content_project

    def export_config(self) -> Dict[str, Any]:
        return asdict(self.config)

    def _project_packed(self, values: Tensor, mask: Tensor, projection: nn.Module) -> Tensor:
        """Apply a projection only to effective rows; masked garbage is untouched."""
        out = values.new_zeros((*values.shape[:-1], self.dim))
        if mask.any():
            out[mask] = projection(values[mask])
        return out

    def encode_state(
        self,
        query_embedding: Tensor,
        selected_content: Tensor,
        selected_mask: Tensor,
        selected_fraction: Tensor,
    ) -> tuple[Tensor, Tensor, Tensor]:
        """Return projected query, state, and projected selected content."""
        if query_embedding.ndim != 2 or query_embedding.shape[-1] != self.config.input_dim:
            raise ValueError("query_embedding must have shape [B,input_dim]")
        batch = query_embedding.shape[0]
        if selected_content.ndim != 3 or selected_content.shape[0] != batch:
            raise ValueError("selected_content must have shape [B,S,input_dim]")
        if selected_content.shape[-1] != self.config.input_dim:
            raise ValueError("selected_content input dimension mismatch")
        _require_bool("selected_mask", selected_mask, selected_content.shape[:2])
        if selected_fraction.shape != (batch, 1):
            raise ValueError("selected_fraction must have shape [B,1]")
        _require_finite("query_embedding", query_embedding)
        _require_finite("selected_content", selected_content, selected_mask)
        _require_finite("selected_fraction", selected_fraction)
        if ((selected_fraction < 0) | (selected_fraction > 1)).any():
            raise ValueError("selected_fraction must be in [0,1]")
        expected = selected_mask.sum(1, keepdim=True).to(selected_fraction.dtype) / self.config.output_k
        if not torch.allclose(selected_fraction, expected, atol=1e-6, rtol=0):
            raise ValueError("selected_fraction must equal selected_count/output_k")

        zq = self.content_project(query_embedding)
        zs = self._project_packed(selected_content, selected_mask, self.content_project)
        count = selected_mask.sum(1, keepdim=True)
        selected_mean = zs.sum(1) / count.clamp_min(1).to(zs.dtype)
        selected_mean = torch.where(
            count.eq(0), self.empty_state.unsqueeze(0).expand(batch, -1), selected_mean
        )
        state_input = torch.cat([zq, selected_mean, selected_fraction.to(zq.dtype)], dim=-1)
        state = self.state_norm(self.state_mlp(state_input))
        return zq, state, zs

    def forward(
        self,
        query_embedding: Tensor,
        selected_content: Tensor,
        selected_mask: Tensor,
        target_content: Tensor,
        source_content: Tensor,
        route_features: Tensor,
        route_mask: Tensor,
        *,
        target_context: Optional[Tensor] = None,
        context_mask: Optional[Tensor] = None,
        candidate_mask: Optional[Tensor] = None,
        dense_similarity: Optional[Tensor] = None,
        dense_similarity_mask: Optional[Tensor] = None,
        selected_fraction: Optional[Tensor] = None,
        no_edge: bool = False,
        disable_context: bool = False,
        disable_dense_similarity: bool = False,
        return_diagnostics: bool = True,
    ) -> Dict[str, Any]:
        """Score unique candidates with up to R legal directed routes."""
        if target_content.ndim != 3 or target_content.shape[-1] != self.config.input_dim:
            raise ValueError("target_content must have shape [B,C,input_dim]")
        batch, candidates = target_content.shape[:2]
        if query_embedding.shape[0] != batch:
            raise ValueError("batch dimension mismatch")
        if source_content.ndim != 4 or source_content.shape[:2] != (batch, candidates):
            raise ValueError("source_content must have shape [B,C,R,input_dim]")
        if source_content.shape[-1] != self.config.input_dim:
            raise ValueError("source_content input dimension mismatch")
        routes = source_content.shape[2]
        if route_features.shape != (batch, candidates, routes, self.edge_feature_dim):
            raise ValueError(f"route_features must have shape [B,C,R,{self.edge_feature_dim}]")
        _require_bool("route_mask", route_mask, source_content.shape[:3])

        device = target_content.device
        if candidate_mask is None:
            candidate_mask = torch.ones((batch, candidates), dtype=torch.bool, device=device)
        _require_bool("candidate_mask", candidate_mask, target_content.shape[:2])
        if (route_mask & ~candidate_mask.unsqueeze(-1)).any():
            raise ValueError("a valid route cannot point to an invalid candidate")

        if target_context is None:
            target_context = target_content.new_zeros((batch, candidates, self.config.resolved_context_dim))
        if target_context.shape != (batch, candidates, self.config.resolved_context_dim):
            raise ValueError("target_context dimension mismatch")
        if context_mask is None:
            context_mask = torch.zeros((batch, candidates), dtype=torch.bool, device=device)
        _require_bool("context_mask", context_mask, target_content.shape[:2])
        if self.config.view_mode == "joint_legacy" and context_mask.any():
            raise ValueError("joint_legacy mode requires an all-false context_mask")
        if (context_mask & ~candidate_mask).any():
            raise ValueError("context cannot be available for an invalid candidate")

        if dense_similarity is None:
            dense_similarity = target_content.new_zeros((batch, candidates))
        if dense_similarity.shape != (batch, candidates):
            raise ValueError("dense_similarity must have shape [B,C]")
        if dense_similarity_mask is None:
            dense_similarity_mask = torch.zeros((batch, candidates), dtype=torch.bool, device=device)
        _require_bool("dense_similarity_mask", dense_similarity_mask, target_content.shape[:2])
        if (dense_similarity_mask & ~candidate_mask).any():
            raise ValueError("dense similarity cannot be available for an invalid candidate")

        if selected_fraction is None:
            selected_fraction = selected_mask.sum(1, keepdim=True).to(query_embedding.dtype) / self.config.output_k
        zq, state, _ = self.encode_state(
            query_embedding, selected_content, selected_mask, selected_fraction
        )

        _require_finite("target_content", target_content, candidate_mask)
        effective_context_mask = context_mask & candidate_mask
        if disable_context:
            effective_context_mask = torch.zeros_like(effective_context_mask)
        _require_finite("target_context", target_context, effective_context_mask)
        effective_dense_mask = dense_similarity_mask & candidate_mask
        if disable_dense_similarity:
            effective_dense_mask = torch.zeros_like(effective_dense_mask)
        _require_finite("dense_similarity", dense_similarity, effective_dense_mask)
        effective_route_mask = route_mask & candidate_mask.unsqueeze(-1)
        if no_edge:
            effective_route_mask = torch.zeros_like(effective_route_mask)
        _require_finite("source_content", source_content, effective_route_mask)
        _require_finite("route_features", route_features, effective_route_mask)

        zt = self._project_packed(target_content, candidate_mask, self.content_project)
        xctx = self._project_packed(target_context, effective_context_mask, self.context_project)
        e0 = target_content.new_zeros((batch, candidates, routes, self.dim))
        dynamic_edge = torch.zeros_like(e0)
        if effective_route_mask.any():
            route_index = effective_route_mask.nonzero(as_tuple=True)
            zs = self.content_project(source_content[route_index])
            route_batch, route_candidate, _ = route_index
            zt_route = zt[route_batch, route_candidate]
            base_input = torch.cat(
                [zs, zt_route, zt_route - zs, zs * zt_route, route_features[route_index]], dim=-1
            )
            valid_e0 = self.edge_base(base_input)
            route_state = state[route_batch]
            valid_dynamic = self.edge_norm(
                valid_e0
                + self.edge_update(
                    torch.cat(
                        [valid_e0, route_state, valid_e0 * self.state_to_edge(route_state)], dim=-1
                    )
                )
            )
            e0[route_index] = valid_e0
            dynamic_edge[route_index] = valid_dynamic

        route_count = effective_route_mask.sum(2, keepdim=True)
        pooled_edge = dynamic_edge.sum(2) / route_count.clamp_min(1).to(dynamic_edge.dtype)
        has_route = route_count.squeeze(-1).gt(0) & candidate_mask
        scores = target_content.new_zeros((batch, candidates))
        hidden = target_content.new_zeros((batch, candidates, self.config.hidden))
        if candidate_mask.any():
            candidate_index = candidate_mask.nonzero(as_tuple=True)
            cb, _ = candidate_index
            dense_value = torch.where(
                effective_dense_mask[candidate_index],
                dense_similarity[candidate_index],
                torch.zeros_like(dense_similarity[candidate_index]),
            )
            rank_input = torch.cat(
                [
                    zq[cb], state[cb], zt[candidate_index], pooled_edge[candidate_index],
                    zq[cb] * zt[candidate_index], state[cb] * zt[candidate_index],
                    xctx[candidate_index], has_route[candidate_index].to(zt.dtype).unsqueeze(-1),
                    effective_context_mask[candidate_index].to(zt.dtype).unsqueeze(-1),
                    dense_value.unsqueeze(-1), effective_dense_mask[candidate_index].to(zt.dtype).unsqueeze(-1),
                ], dim=-1,
            )
            hidden_valid = self.rank_mlp[2](self.rank_mlp[1](self.rank_mlp[0](rank_input)))
            score_valid = self.rank_mlp[3](hidden_valid).squeeze(-1)
            scores[candidate_index] = score_valid
            hidden[candidate_index] = hidden_valid

        _require_finite("scores", scores, candidate_mask)
        result: Dict[str, Any] = {
            "scores": scores,
            "score": scores,
            "candidate_mask": candidate_mask,
            "pooled_edge": pooled_edge,
            "state": state,
            "has_route": has_route,
            "route_mask": effective_route_mask,
            "work_counts": {
                "target_scores": int(candidate_mask.sum().item()),
                "route_base_computations": int(effective_route_mask.sum().item()),
                "route_updates": int(effective_route_mask.sum().item()),
                "target_tensor_rows": int(candidate_mask.sum().item()),
                "route_tensor_rows": int(effective_route_mask.sum().item()),
                "cache_hits": 0,
            },
            "aux_status": {
                "A": "enabled" if self.a_head is not None else "disabled",
                "E": "enabled" if self.e_head is not None else "disabled",
            },
        }
        if return_diagnostics:
            result.update({"e0": e0, "dynamic_edge": dynamic_edge, "rank_hidden": hidden})
        if self.a_head is not None:
            result["a_logits"] = self.a_head(hidden)
        if self.e_head is not None:
            result["e_logits"] = self.e_head(hidden)
        return result
