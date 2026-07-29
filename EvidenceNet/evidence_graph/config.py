from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "input": {"aligned_root": "../parsing/output/hybrid_deepseek_layout_split_render/aligned_json"},
    "output": {"graph_root": "output/evidence_graph"},
    "evidence": {"one_aligned_block_per_node": True, "split_on_single_newline": False,
                 "merge_continuations": False, "keep_incomplete_nodes": True},
    "structure": {"create_previous_edges": True, "detect_continuations": True},
    "validation": {"deepseek_order_conflict_threshold": 3},
    "enrichment": {"enabled": False, "provider": "transformers", "model": None,
                   "dtype": "float32", "max_new_tokens": 2048, "batch_size": 3, "prompt_version": "v1"},
    "embedding": {"enabled": False, "model": None, "input_mode": "original_plus_summary"},
    "candidates": {"structural_window": 3, "embedding_top_k": 8, "shared_entity_top_k": 5,
                   "same_section_top_k": 5, "maximum_candidates_per_node": 15},
    "relations": {"acceptance_threshold": 0.8, "allow_unsupported_relation_review": True, "batch_size": 3},
    "pilot": {"maximum_nodes": 25, "section_count": 2, "include_unsectioned": True, "maximum_candidates": 45},
}


def _merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    raw = path.read_text(encoding="utf-8")
    try:
        import yaml
        supplied = yaml.safe_load(raw) or {}
    except ImportError:
        supplied = json.loads(raw)
    config = _merge(deepcopy(DEFAULT_CONFIG), supplied)
    for group, key in (("input", "aligned_root"), ("output", "graph_root")):
        value = Path(config[group][key])
        if not value.is_absolute():
            value = (path.parent.parent / value).resolve()
        config[group][key] = str(value)
    return config
