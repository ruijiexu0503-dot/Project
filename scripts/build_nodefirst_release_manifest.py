#!/usr/bin/env python3
"""Build deterministic manifests for the GitHub Node-first QA release."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FROZEN_GOLD = ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_codex_direct_20261119/qa_gold_codex_direct_cumulative_200.jsonl"
GOLD = ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_codex_direct_20261119/release_20261120/qa_gold200_normalized.jsonl"
CORE_ROOTS = (
    ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_codex_direct_20261119",
    ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117",
    ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261119_snapshot_d",
    ROOT / "DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113",
    ROOT / "DynamicEdgeGraph/dynamic_retrieval",
)
PDF_ROOTS = (
    ROOT / "DynamicEdgeGraph/datasets/real_documents_v1_20261113",
    ROOT / "data",
)
EXCLUDED_NAMES = {
    "sampled_seeds_snapshot_C.jsonl",
    "sampled_seeds_snapshot_D.jsonl",
    "sampled_seeds_snapshot_D_generation_v2.jsonl",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def file_record(path: Path) -> dict:
    return {"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "release_manifests")
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    gold = rows(GOLD)
    evidence = [item for row in gold for item in row.get("gold_evidence_draft", [])]
    summary = {
        "release": "nodefirst_gold200_20261120",
        "gold_path": relative(GOLD),
        "frozen_source_path": relative(FROZEN_GOLD),
        "qa_count": len(gold),
        "category_counts": dict(sorted(Counter(row.get("qa_category") for row in gold).items())),
        "document_count": len({item.get("document_id") for item in evidence}),
        "canonical_node_count": len({item.get("canonical_node_id") for item in evidence}),
        "final_gate_counts": dict(sorted(Counter(
            row.get("normalized_release_gate", {}).get("status", "MISSING") for row in gold
        ).items())),
    }
    (output / "gold200_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    core_files: list[Path] = []
    for root in CORE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name in EXCLUDED_NAMES:
                continue
            if any(part in {"__pycache__", "logs", "checkpoints"} for part in path.parts):
                continue
            if path.suffix.lower() not in {".json", ".jsonl", ".md", ".py", ".sbatch"}:
                continue
            core_files.append(path)
    core_records = [file_record(path) for path in sorted(set(core_files))]
    (output / "core_files.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in core_records)
    )

    pdf_files = sorted({
        path for root in PDF_ROOTS if root.exists()
        for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"
    })
    pdf_records = [file_record(path) for path in pdf_files]
    (output / "pdf_sources.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in pdf_records)
    )
    (output / "manifest_summary.json").write_text(json.dumps({
        "core_file_count": len(core_records),
        "core_bytes": sum(record["bytes"] for record in core_records),
        "pdf_file_count": len(pdf_records),
        "pdf_bytes": sum(record["bytes"] for record in pdf_records),
        "pdf_payload_in_git": False,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
