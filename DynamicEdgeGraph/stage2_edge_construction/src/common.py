"""Strict IO contract for query-independent Stage 2 E0 runs."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any, Iterable
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
def repo_path(value: str | None) -> Path | None:
    if value is None: return None
    path = Path(value); return path if path.is_absolute() else ROOT / path
def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle: config = json.load(handle)
    required = {"run_id", "dataset_id", "dataset_revision", "node_id_namespace", "baseline_dir", "output_root"}
    absent = sorted(required - config.keys())
    if absent: raise ValueError(f"config missing required fields: {absent}")
    return config
def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if line.strip():
                try: yield json.loads(line)
                except json.JSONDecodeError as exc: raise ValueError(f"invalid JSONL at {path}:{line_no}") from exc
def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True); count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows: handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"); count += 1
    return count
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()
def stable_pair_id(left: str, right: str, namespace: str) -> str:
    if left == right: raise ValueError("self-pairs are not allowed")
    a, b = sorted((left, right)); return "pair_" + hashlib.sha256(f"stage2-pair-v1\0{namespace}\0{a}\0{b}".encode()).hexdigest()[:24]
def stable_edge_id(pair_id: str, source_id: str, target_id: str) -> str:
    return "edge_" + hashlib.sha256(f"stage2-edge-v1\0{pair_id}\0{source_id}\0{target_id}".encode()).hexdigest()[:24]
def run_dir(config: dict[str, Any]) -> Path: return repo_path(config["output_root"]) / config["run_id"]
def load_embeddings(config: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    vector_path, ids_path = repo_path(config.get("embedding_path")), repo_path(config.get("embedding_ids_path"))
    if vector_path is None or ids_path is None: raise ValueError("embedding_path and embedding_ids_path are required; no positional fallback is permitted")
    if not vector_path.is_file() or not ids_path.is_file(): raise FileNotFoundError(f"missing embedding input: vectors={vector_path}, ids={ids_path}")
    vectors = np.load(vector_path, mmap_mode="r")
    if vectors.ndim != 2 or not np.issubdtype(vectors.dtype, np.floating): raise ValueError(f"embedding matrix must be 2D floating point, got {vectors.shape} {vectors.dtype}")
    ids = []
    for row in read_jsonl(ids_path):
        node_id = row.get("node_id")
        if not isinstance(node_id, str) or not node_id: raise ValueError(f"embedding ID record without node_id in {ids_path}")
        ids.append(node_id)
    if len(ids) != vectors.shape[0]: raise ValueError(f"embedding row mismatch: matrix={vectors.shape[0]}, ids={len(ids)}")
    if len(ids) != len(set(ids)): raise ValueError("embedding IDs are not unique")
    if not np.isfinite(vectors).all(): raise ValueError("embedding matrix contains NaN or Inf")
    return vectors, ids
