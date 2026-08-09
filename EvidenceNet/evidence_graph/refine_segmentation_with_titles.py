from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl
from .segmentation_ground_truth import evaluate, materialize


def main():
    parser = argparse.ArgumentParser(description="Conservative recovered-title segmentation refinement")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--assignments", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--title-audit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-margin", type=float, default=.15)
    parser.add_argument("--min-following-similarity", type=float, default=.75)
    parser.add_argument("--min-boundary-score", type=float, default=.45)
    parser.add_argument("--skip-reference-evaluation", action="store_true")
    args = parser.parse_args()
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    nodes = sorted(read_jsonl(args.nodes), key=lambda row: row["document_order"])
    order_by_id = {row["node_id"]: row["document_order"] for row in nodes}
    diagnostics = read_jsonl(args.diagnostics)
    diagnostic_by_order = {order_by_id[row["right_id"]]: row for row in diagnostics}
    original = sorted(read_jsonl(args.assignments), key=lambda row: order_by_id[row["node_id"]])

    existing = set(); previous = None
    for row in original:
        item = row.get("content_item_id") or row.get("segment_id")
        if previous is not None and item != previous: existing.add(order_by_id[row["node_id"]])
        previous = item
    additions = []
    for title in read_jsonl(args.title_audit):
        order = title.get("associated_order"); diagnostic = diagnostic_by_order.get(order)
        if not order or order in existing or not diagnostic: continue
        accepted = (title.get("detection") == "explicit_heading"
                    and title.get("coverage_status") == "MISSING_FROM_EVIDENCE"
                    and title.get("classification") == "LIKELY_STARTS_NEW_ITEM"
                    and title.get("context_margin", -1) >= args.min_margin
                    and title.get("following_similarity", -1) >= args.min_following_similarity
                    and diagnostic.get("boundary_score", -1) >= args.min_boundary_score
                    and not diagnostic.get("anaphoric_start"))
        if accepted:
            existing.add(order)
            additions.append({"start_document_order": order, "node_id": nodes[order - 1]["node_id"],
                              "title": title["title"], "title_context_margin": title["context_margin"],
                              "following_similarity": title["following_similarity"],
                              "boundary_score": diagnostic["boundary_score"],
                              "reasons": ["explicit_source_heading_missing_from_evidence",
                                          "title_favors_following_context",
                                          "independent_change_point_support"]})

    assignments = []; segment = 0
    for node in nodes:
        if node["document_order"] == 1 or node["document_order"] in existing: segment += 1
        assignments.append({"node_id": node["node_id"], "segment_id": f"SEGMENT_{segment:04d}",
                            "content_item_id": f"ITEM_{segment:04d}"})
    report = {"method": "conservative_recovered_title_refinement_v1",
              "thresholds": {"min_margin": args.min_margin,
                             "min_following_similarity": args.min_following_similarity,
                             "min_boundary_score": args.min_boundary_score},
              "added_boundaries": additions, "added_count": len(additions),
              "segments": len(existing) + 1}
    if not args.skip_reference_evaluation:
        reference = materialize(nodes)
        scored = [{**row, "document_order": order_by_id[row["node_id"]]} for row in assignments]
        report.update(exact=evaluate(reference, scored, 0), tolerance_1=evaluate(reference, scored, 1),
                      tolerance_2=evaluate(reference, scored, 2))
    write_jsonl(output / "assignments.jsonl", assignments)
    write_jsonl(output / "added_boundaries.jsonl", additions)
    write_json(output / "evaluation.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
