"""Strict checkpoint I/O for the network build stage."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import torch

from model import DynamicEdgeConfig, DynamicEdgeRanker, NETWORK_VERSION, ROUTE_FEATURE_DIM


CHECKPOINT_SCHEMA_VERSION = "dynamic_edge_checkpoint_v1"
ROUTE_FEATURE_SCHEMA = [
    "semantic",
    "lexical_or_entity",
    "structural",
    "explicit_reference",
    "other",
    "same_document",
    "same_page",
    "signed_page_delta",
    "page_delta_available",
    "inverse_source_rank",
    "source_rank_available",
    "normalized_discovery_depth",
]


def save_checkpoint(
    path: str | Path,
    model: DynamicEdgeRanker,
    *,
    metadata: Mapping[str, Any],
    optimizer: Optional[torch.optim.Optimizer] = None,
    scheduler: Optional[Any] = None,
) -> None:
    """Save architecture and provenance; training state is optional at build time."""
    required = {"encoder_hash", "graph_hash", "data_hash", "random_seed"}
    missing = required.difference(metadata)
    if missing:
        raise ValueError(f"checkpoint metadata missing: {sorted(missing)}")
    payload: Dict[str, Any] = {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "network_version": NETWORK_VERSION,
        "model_config": model.export_config(),
        "route_feature_dim": ROUTE_FEATURE_DIM,
        "route_feature_schema": ROUTE_FEATURE_SCHEMA,
        "model_state": model.state_dict(),
        "metadata": dict(metadata),
        "torch_version": str(torch.__version__),
    }
    if optimizer is not None:
        payload["optimizer_state"] = optimizer.state_dict()
    if scheduler is not None:
        payload["scheduler_state"] = scheduler.state_dict()
    torch.save(payload, Path(path))


def load_checkpoint(
    path: str | Path,
    *,
    map_location: str | torch.device = "cpu",
    optimizer: Optional[torch.optim.Optimizer] = None,
    scheduler: Optional[Any] = None,
) -> tuple[DynamicEdgeRanker, Dict[str, Any]]:
    """Load strictly; version, feature schema, and all tensor shapes must agree."""
    payload = torch.load(Path(path), map_location=map_location)
    if payload.get("checkpoint_schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("checkpoint schema version mismatch")
    if payload.get("network_version") != NETWORK_VERSION:
        raise ValueError("network version mismatch")
    if payload.get("route_feature_dim") != ROUTE_FEATURE_DIM:
        raise ValueError("route feature dimension mismatch")
    if payload.get("route_feature_schema") != ROUTE_FEATURE_SCHEMA:
        raise ValueError("route feature schema mismatch")
    try:
        config = DynamicEdgeConfig(**payload["model_config"])
        model = DynamicEdgeRanker(config=config)
        model.load_state_dict(payload["model_state"], strict=True)
    except (KeyError, TypeError, RuntimeError, ValueError) as exc:
        raise ValueError(f"invalid or incompatible checkpoint: {exc}") from exc
    if optimizer is not None:
        if "optimizer_state" not in payload:
            raise ValueError("checkpoint has no optimizer state")
        optimizer.load_state_dict(payload["optimizer_state"])
    if scheduler is not None:
        if "scheduler_state" not in payload:
            raise ValueError("checkpoint has no scheduler state")
        scheduler.load_state_dict(payload["scheduler_state"])
    return model, payload
