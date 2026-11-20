"""Create a blinded, source-grounded relation-review panel from frozen Pilot pairs.

This is review material, not a source of labels.  It never calls a model, query,
or relevance Gold data.  The blind packet excludes retrieval score, route support,
candidate origin and existing cluster ID so that a reviewer cannot simply ratify
the current clustering geometry.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

try:  # supports both ``python -m ...`` and the repository's script-style calls
    from .common import read_jsonl, write_json
except ImportError:  # pragma: no cover - exercised by Slurm script execution
    from common import read_jsonl, write_json


def clean(value: object) -> str:
    return "\n".join(line.rstrip() for line in str(value or "").strip().splitlines() if line.strip())


def split_representation(value: str) -> tuple[str, str]:
    """Keep source content separate from title/headings used by retrieval."""
    value = clean(value)
    if "[CONTENT]" not in value:
        return "", value
    context, content = value.split("[CONTENT]", 1)
    return clean(context.removeprefix("[PAGE_CONTEXT]")), clean(content)


def read_sheet(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("no review rows")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-sheet", type=Path, required=True)
    parser.add_argument("--views", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source_rows = read_sheet(args.review_sheet)
    views = {str(row["node_id"]): row for row in read_jsonl(args.views)}
    missing = sorted({row[side] for row in source_rows for side in ("source_node_id", "target_node_id")} - set(views))
    if missing:
        raise ValueError(f"review nodes absent from frozen views: {missing[:5]}")

    packet, trace = [], []
    for number, row in enumerate(source_rows, 1):
        source, target = views[row["source_node_id"]], views[row["target_node_id"]]
        source_context, source_content = split_representation(str(source.get("retrieval_text") or source.get("representation_text") or ""))
        target_context, target_content = split_representation(str(target.get("retrieval_text") or target.get("representation_text") or ""))
        if not source_content or not target_content:
            raise ValueError(f"empty source-grounded content for {row['pair_id']}")
        packet.append({
            "review_item_id": f"relation_review_{number:03d}",
            "review_status": "UNREVIEWED",
            "relation_supported": "",  # YES / NO / INSUFFICIENT_CONTEXT / UNCERTAIN
            "source_role": "", "target_role": "", "connection_mechanism": "",
            "conditions_or_scope": "", "source_evidence_quote": "", "target_evidence_quote": "",
            "reviewer": "", "review_notes": "",
            "source_modality": row["source_modality"], "source_content": source_content,
            "target_modality": row["target_modality"], "target_content": target_content,
        })
        trace.append({
            "review_item_id": f"relation_review_{number:03d}", "pair_id": row["pair_id"],
            "source_node_id": row["source_node_id"], "target_node_id": row["target_node_id"],
            "source_document_id": row["source_document_id"], "target_document_id": row["target_document_id"],
            "source_page": row["source_page"], "target_page": row["target_page"],
            "source_context": source_context, "target_context": target_context,
            "sampling_bucket": row["sampling_bucket"],
        })
    write_csv(args.out / "relation_review_blind_packet.csv", packet)
    write_csv(args.out / "relation_review_trace.csv", trace)
    write_json(args.out / "relation_review_manifest.json", {
        "items": len(packet), "source_review_sheet": str(args.review_sheet.resolve()),
        "frozen_views": str(args.views.resolve()), "query_used": False, "gold_labels_used": False,
        "model_predictions_used": False,
        "blind_packet_excludes": ["pair_id", "document_id", "page", "route_support", "route_scores", "candidate_origin", "cluster_id"],
        "review_outcomes": ["YES", "NO", "INSUFFICIENT_CONTEXT", "UNCERTAIN"],
        "contract": "Human review must cite evidence from both content fields; blank outcomes are not labels.",
    })
    print(json.dumps({"items": len(packet), "out": str(args.out)}, sort_keys=True))


if __name__ == "__main__":
    main()
