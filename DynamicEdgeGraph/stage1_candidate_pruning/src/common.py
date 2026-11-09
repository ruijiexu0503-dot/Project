"""Shared, deterministic Stage 1 input and output helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List


ROOT = Path(__file__).resolve().parents[3]


def load_config(path: str) -> Dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml
        value = yaml.safe_load(text)
    except ImportError:
        value = {}
        for line in text.splitlines():
            if ":" not in line or line.lstrip().startswith("#"):
                continue
            key, raw = line.split(":", 1)
            raw = raw.strip()
            if raw.startswith("["):
                raw = [x.strip() for x in raw[1:-1].split(",") if x.strip()]
            elif raw.isdigit():
                raw = int(raw)
            value[key.strip()] = raw
    if not isinstance(value, dict):
        raise ValueError("configuration must be a mapping")
    # Slurm sensitivity arrays use isolated run IDs without modifying configs.
    if os.environ.get("STAGE1_RUN_ID"):
        value["run_id"] = os.environ["STAGE1_RUN_ID"]
    if os.environ.get("STAGE1_TOP_K"):
        value["top_k"] = int(os.environ["STAGE1_TOP_K"])
    return value


def repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def resolve_hf_file(config: Dict[str, Any], key: str) -> Path:
    """Resolve a subset file locally, downloading only that named file."""
    configured = repo_path(str(config[key]))
    if configured.exists():
        return configured
    if "/" in str(config[key]) or not config.get("hf_repo_id"):
        return configured
    destination = repo_path(str(config.get("hf_cache_dir", ".cache/huggingface")))
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / str(config[key])
    if target.exists():
        return target
    try:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(
            repo_id=str(config["hf_repo_id"]), filename=str(config[key]),
            revision=str(config.get("hf_revision", "main")),
            repo_type="dataset", local_dir=str(destination),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Unable to access gated Hugging Face file {config['hf_repo_id']}/{config[key]}; "
            "authenticate in the existing HF environment before retrying."
        ) from exc
    return Path(downloaded)


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def node_text(row: Dict[str, Any]) -> str:
    pieces = [str(row.get("text", row.get("retrieval_text", row.get("quote", ""))))]
    for member in row.get("members", []) or []:
        if isinstance(member, dict):
            pieces.append(str(member.get("text", "")))
    return " ".join(x for x in pieces if x).strip()


def node_record(row: Dict[str, Any], index: int) -> Dict[str, Any]:
    node_id = row.get("node_id", row.get("id"))
    if not node_id:
        raise ValueError(f"node at index {index} has no id")
    node_id = str(node_id)
    document = row.get("document_id", row.get("document", row.get("article_id", "")))
    page = row.get("page_number", row.get("page", row.get("original_pdf_page")))
    if page is None:
        match = re.search(r"_page_(\d+)", node_id)
        page = int(match.group(1)) if match else None
    if not document:
        document = node_id.split("_page_", 1)[0]
    return {
        "node_id": str(node_id), "document_id": str(document),
        "page_number": page, "modality": row.get("modality", row.get("node_type", row.get("kind", row.get("unit_type", "unknown")))),
        "text": node_text(row), "reading_order": row.get("min_order", row.get("order")),
    }


def run_dir(config: Dict[str, Any]) -> Path:
    return repo_path(str(config["output_root"])) / str(config["run_id"])


def tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9][a-z0-9_'-]*", text.lower())
