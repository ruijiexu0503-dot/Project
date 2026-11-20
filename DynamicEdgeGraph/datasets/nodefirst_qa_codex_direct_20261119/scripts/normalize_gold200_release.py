#!/usr/bin/env python3
"""Normalize Gold-200 final-gate metadata without changing the frozen source."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "qa_gold_codex_direct_cumulative_200.jsonl"
POOLS = (
    ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/snapshot_A_canonical_nodes.jsonl",
    ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/snapshot_B_short_canonical_nodes.jsonl",
    ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/snapshot_C_canonical_nodes.jsonl",
    ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261119_snapshot_d/snapshot_D_formal_canonical_nodes.jsonl",
    ROOT / "DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/nodes.jsonl",
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def node_id(row: dict) -> str | None:
    return row.get("canonical_node_id") or row.get("node_id") or row.get("id")


def document_id(row: dict) -> str | None:
    return row.get("document_id") or row.get("doc_id")


def page_number(row: dict) -> int | None:
    value = row.get("page_number")
    if value is not None:
        return int(value)
    page = str(row.get("page_id") or "")
    if page.startswith("page_") and page[5:].isdigit():
        return int(page[5:])
    return None


def build_index() -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    for pool in POOLS:
        for row in read_jsonl(pool):
            identifier = node_id(row)
            if identifier:
                index[identifier].append(row)
    return index


def review_pass(row: dict) -> bool:
    statuses = {
        row.get("review", {}).get("status"),
        row.get("direct_codex_review", {}).get("status"),
        row.get("upstream_review_status"),
        row.get("final_gate", {}).get("status"),
    }
    accepted = {
        "FINAL_ACCEPT_AUTOMATIC",
        "DIRECT_REVIEW_ACCEPT",
        "DIRECT_GOLD_ACCEPT",
    }
    return bool(statuses & accepted) and row.get("review", {}).get("human_approval_required") is not True


def validate(row: dict, index: dict[str, list[dict]]) -> list[str]:
    failures: list[str] = []
    evidence = row.get("gold_evidence_draft") or []
    if not evidence:
        failures.append("NO_GOLD_EVIDENCE")
    if not review_pass(row):
        failures.append("AUTOMATIC_REVIEW_NOT_ACCEPTED")

    for position, item in enumerate(evidence):
        identifier = item.get("canonical_node_id")
        candidates = index.get(identifier, [])
        mapped = [candidate for candidate in candidates
                  if document_id(candidate) == item.get("document_id")
                  and page_number(candidate) == int(item.get("page_number"))]
        if not candidates:
            failures.append(f"E{position}:NODE_ID_NOT_FOUND")
        elif not mapped:
            failures.append(f"E{position}:DOCUMENT_PAGE_MISMATCH")

    claims = row.get("answer_claims") or []
    if not claims:
        failures.append("NO_ANSWER_CLAIMS")
    for claim in claims:
        supports = claim.get("supporting_evidence_indices") or []
        if not supports:
            failures.append(f"{claim.get('claim_id')}:NO_SUPPORT")
        for span in claim.get("evidence_spans") or []:
            idx = span.get("evidence_index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(evidence):
                failures.append(f"{claim.get('claim_id')}:BAD_EVIDENCE_INDEX")
                continue
            if span.get("canonical_node_id") != evidence[idx].get("canonical_node_id"):
                failures.append(f"{claim.get('claim_id')}:SPAN_NODE_MISMATCH")
            text = str(evidence[idx].get("evidence_text") or "")
            start, end = span.get("char_start"), span.get("char_end")
            if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
                failures.append(f"{claim.get('claim_id')}:BAD_SPAN_OFFSETS")
            elif text[start:end] != span.get("text"):
                failures.append(f"{claim.get('claim_id')}:SPAN_TEXT_MISMATCH")

    necessity = row.get("generation_node_necessity") or []
    necessary_ids = set()
    for item in necessity:
        identifier = item.get("canonical_node_id")
        if identifier is None:
            idx = item.get("evidence_index")
            if isinstance(idx, int) and 0 <= idx < len(evidence):
                identifier = evidence[idx].get("canonical_node_id")
        if identifier is not None:
            necessary_ids.add(identifier)
    evidence_ids = {item.get("canonical_node_id") for item in evidence}
    if necessary_ids != evidence_ids:
        failures.append("NECESSITY_COVERAGE_MISMATCH")
    return sorted(set(failures))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "release_20261120")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    index = build_index()
    normalized, issues = [], []
    for row in read_jsonl(args.source):
        failures = validate(row, index)
        updated = dict(row)
        updated["normalized_release_gate"] = {
            "status": "FINAL_ACCEPT_AUTOMATIC" if not failures else "RELEASE_BLOCKED",
            "source_integrity": "PASS" if not any("NODE_ID" in item for item in failures) else "FAIL",
            "canonical_mapping": "PASS" if not any(
                "NODE_ID" in item or "DOCUMENT_PAGE" in item for item in failures
            ) else "FAIL",
            "claim_grounding": "PASS" if not any(
                "CLAIM" in item or "SPAN" in item or "SUPPORT" in item for item in failures
            ) else "FAIL",
            "node_necessity": "PASS" if "NECESSITY_COVERAGE_MISMATCH" not in failures else "FAIL",
            "independent_review": "PASS" if review_pass(row) else "FAIL",
            "human_approval_required": False,
            "normalizer": "normalize_gold200_release_v1",
            "failures": failures,
        }
        normalized.append(updated)
        if failures:
            issues.append({"draft_id": row.get("draft_id"), "failures": failures})

    target = args.output_dir / "qa_gold200_normalized.jsonl"
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in normalized))
    (args.output_dir / "normalization_issues.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in issues)
    )
    counts = Counter(row["normalized_release_gate"]["status"] for row in normalized)
    (args.output_dir / "normalization_summary.json").write_text(json.dumps({
        "source": str(args.source),
        "source_overwritten": False,
        "records": len(normalized),
        "status_counts": dict(sorted(counts.items())),
        "issue_records": len(issues),
        "canonical_pool_count": len(index),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"records": len(normalized), "statuses": counts, "issues": len(issues)}))


if __name__ == "__main__":
    main()
