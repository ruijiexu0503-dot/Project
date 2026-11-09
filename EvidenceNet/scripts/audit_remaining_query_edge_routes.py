#!/usr/bin/env python3
"""Create a blinded census of routes not included in the first review sample.

This is a read-only, CPU-only research adapter.  It reuses the frozen
consolidation and card format, never reads Gold, and refuses to overwrite an
existing output directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
PHASE1 = ROOT / "EvidenceNet/output/query_edge_utilization_replay_v1_20261105"
FIRST_REVIEW = ROOT / "EvidenceNet/output/query_edge_utility_manual_review_v1_20261105"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
NAV = ROOT / "EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl"
UNIVERSE = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102/candidate_universe.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/query_edge_utility_remaining_review_v1_20261105"
VERSION = "query-edge-utility-remaining-review-v1-20261105"


def load_review_module():
    path = Path(__file__).with_name("review_query_edge_utility.py")
    spec = importlib.util.spec_from_file_location("query_edge_review", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load review helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, values: Iterable[dict]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_paths() -> list[Path]:
    return [
        PHASE1 / "route_decisions.jsonl",
        NODES,
        NAV,
        UNIVERSE,
        FIRST_REVIEW / "review_cards.jsonl",
    ]


def build_remaining(
    decisions: list[dict],
    navigation: list[dict],
    nodes: dict[str, dict],
    eligible: set[str],
    first_sample_ids: set[str],
    review_module,
    expected_total: int = 34,
    expected_first: int = 12,
    expected_remaining: int = 22,
) -> tuple[list[dict], list[dict]]:
    all_routes = review_module.consolidate(decisions, navigation, nodes, eligible)
    if len(all_routes) != expected_total:
        raise ValueError(f"expected {expected_total} consolidated routes, got {len(all_routes)}")
    all_ids = [row["sample_id"] for row in all_routes]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("duplicate sample_id in consolidated routes")
    if len(first_sample_ids) != expected_first:
        raise ValueError(f"expected {expected_first} first-review sample IDs, got {len(first_sample_ids)}")
    if not first_sample_ids <= set(all_ids):
        missing = sorted(first_sample_ids - set(all_ids))
        raise ValueError(f"first-review sample IDs not in frozen census: {missing}")
    remaining = [row for row in all_routes if row["sample_id"] not in first_sample_ids]
    if len(remaining) != expected_remaining:
        raise ValueError(f"expected {expected_remaining} remaining routes, got {len(remaining)}")
    return all_routes, remaining


def audit(
    decisions_path: Path,
    nodes_path: Path,
    nav_path: Path,
    universe_path: Path,
    first_cards_path: Path,
    out: Path,
) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite: {out}")
    review = load_review_module()
    nodes = {str(row["id"]): row for row in read_jsonl(nodes_path)}
    navigation = read_jsonl(nav_path)
    eligible = {
        str(row["entity_id"])
        for row in read_jsonl(universe_path)
        if row.get("primary_eligible") is True
    }
    first_cards = read_jsonl(first_cards_path)
    first_ids = [str(row.get("sample_id", "")) for row in first_cards]
    if any(not sample_id for sample_id in first_ids):
        raise ValueError("first-review cards contain an empty sample_id")
    if len(first_ids) != len(set(first_ids)):
        raise ValueError("first-review cards contain duplicate sample_id")
    all_routes, remaining = build_remaining(
        read_jsonl(decisions_path), navigation, nodes, eligible, set(first_ids), review
    )
    out.mkdir(parents=True)
    (out / "audit_only").mkdir()
    write_jsonl(
        out / "review_cards.jsonl",
        (review.review_card(row, nodes) for row in remaining),
    )
    write_jsonl(
        out / "annotation_template.jsonl",
        (
            {
                "sample_id": row["sample_id"],
                "relation_validity": None,
                "query_applicability": None,
                "marginal_utility": None,
                "opportunity_cost": None,
                "notes": "",
            }
            for row in remaining
        ),
    )
    # Private reconciliation is deliberately separate from the blinded cards.
    write_jsonl(
        out / "audit_only/private_index.jsonl",
        (
            {
                "sample_id": row["sample_id"],
                "question_id": row["question_id"],
                "edge_id": row["route"]["edge_id"],
                "route_id": row["route"]["route_id"],
                "source_id": row["route"]["oriented_source_id"],
                "target_id": row["route"]["oriented_target_id"],
                "source_dense_rank": row["source_dense_rank"],
                "target_dense_rank": row["target_dense_rank"],
                "novel_page": row["novel_page"],
                "outside_dense20": row["outside_dense20"],
                "stratum": row["stratum"],
                "source_kind": review.source_kind(row["route"]),
                "eligibility": row["route"]["eligibility"],
                "arm_actions": row["arm_actions"],
            }
            for row in remaining
        ),
    )
    hashes = {str(path): file_hash(path) for path in input_paths()}
    summary = {
        "version": VERSION,
        "all_consolidated_routes": len(all_routes),
        "first_review_routes": len(first_ids),
        "remaining_routes": len(remaining),
        "remaining_unique_queries": len({row["question_id"] for row in remaining}),
        "remaining_strata": dict(sorted(Counter(row["stratum"] for row in remaining).items())),
        "first_sample_ids_sha256": hashlib.sha256(
            "\n".join(sorted(first_ids)).encode("utf-8")
        ).hexdigest(),
        "inputs_sha256": hashes,
        "gold_read": False,
        "llm_calls": 0,
        "gpu_used": False,
        "selection": "census set difference; no ranking or utility label used",
    }
    with (out / "selection_summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    (out / "README.md").write_text(
        f"""# Remaining Query–Edge review census

Version: `{VERSION}`.

This directory contains the 22-route set difference between the frozen 34
consolidated `(question_id, oriented route_id)` records and the 12 first-review
sample IDs. It is a blind review package: Gold, arm actions, eligibility and
source class are kept only in `audit_only/private_index.jsonl`.

The command was CPU-only and read no Gold. It refuses to overwrite an existing
directory. Re-run from the repository root with:

```bash
python EvidenceNet/scripts/audit_remaining_query_edge_routes.py
```
""",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    summary = audit(PHASE1 / "route_decisions.jsonl", NODES, NAV, UNIVERSE,
                    FIRST_REVIEW / "review_cards.jsonl", args.out)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
