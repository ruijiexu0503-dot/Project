"""Create a deterministic, label-free Pilot pair review sheet."""
from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict

from common import load_config, read_jsonl, repo_path, run_dir, write_json


def bucket(pair):
    document = "same_document" if pair["source_document_id"] == pair["target_document_id"] else "cross_document"
    modality = "same_modality" if pair["source_modality"] == pair["target_modality"] else "cross_modality"
    return f"{document}|{modality}|support_{min(int(pair.get('route_support', 0)), 5)}"


def clean(value, limit=700):
    return " ".join(str(value or "").split())[:limit]


def view_text(view):
    """Support both historical representation rows and Stage-1 retrieval views.

    The latter intentionally exposes ``retrieval_text`` rather than
    ``representation_text``.  Falling back makes a missing source field explicit
    instead of silently emitting blank reviewer previews.
    """
    return view.get("representation_text") or view.get("retrieval_text") or view.get("content_text") or ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--sample-size", type=int, default=160)
    args = parser.parse_args()
    config = load_config(args.config)
    out = run_dir(config)
    pairs = list(read_jsonl(out / "pairs.jsonl"))
    views_path = repo_path("DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1/retrieval_views.jsonl")
    views = {row["node_id"]: row for row in read_jsonl(views_path)}
    groups = defaultdict(list)
    for pair in pairs:
        groups[bucket(pair)].append(pair)
    rng, selected, keys = random.Random(int(config["seed"]) + 1), [], sorted(groups)
    while len(selected) < min(args.sample_size, len(pairs)) and any(groups.values()):
        for key in keys:
            if groups[key] and len(selected) < args.sample_size:
                selected.append(groups[key].pop(rng.randrange(len(groups[key]))))
    rows = []
    for pair in selected:
        source, target = views[pair["source_node_id"]], views[pair["target_node_id"]]
        rows.append({
            "pair_id": pair["pair_id"], "sampling_bucket": bucket(pair), "review_status": "UNREVIEWED",
            "relation_label": "", "direction_label": "", "shared_semantics": "", "relation_description": "", "reviewer": "", "review_notes": "",
            "source_node_id": pair["source_node_id"], "source_document_id": pair["source_document_id"], "source_page": pair["source_page"], "source_modality": pair["source_modality"], "source_representation": clean(view_text(source)),
            "target_node_id": pair["target_node_id"], "target_document_id": pair["target_document_id"], "target_page": pair["target_page"], "target_modality": pair["target_modality"], "target_representation": clean(view_text(target)),
            "route_support": pair.get("route_support"), "candidate_origin": ";".join(pair["candidate_origin"]),
        })
    columns = list(rows[0]) if rows else []
    csv_path = out / "pair_review_sheet.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    write_json(out / "review_sheet_manifest.json", {"rows": len(rows), "seed": int(config["seed"]) + 1, "source_pairs": len(pairs), "stratification": "same/cross document × same/cross modality × route support (capped at 5)", "labels": ["SUPPORTED_RELATION", "NO_RELATION", "UNCERTAIN"], "query_used": False, "gold_labels_used": False})
    print(csv_path)


if __name__ == "__main__":
    main()
