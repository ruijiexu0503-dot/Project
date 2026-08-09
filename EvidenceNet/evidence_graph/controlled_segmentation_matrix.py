from __future__ import annotations

import argparse
import json
from pathlib import Path

from .embeddings import generate_document_embeddings
from .io_utils import read_jsonl, write_json, write_jsonl
from .page_aware_segmentation import segment
from .segmentation_ground_truth import evaluate, materialize


def run_cell(label, nodes, embedding_model, aligned_dir, output_root, reference):
    target = output_root / label
    target.mkdir(parents=True, exist_ok=True)
    selected = {node["node_id"] for node in nodes}
    vectors, metadata = generate_document_embeddings(
        nodes, selected, mode="original_plus_summary", model_path=embedding_model)
    assignments, segments, diagnostics, standalone, resumptions = segment(
        nodes, vectors, str(aligned_dir))
    order_by_id = {node["node_id"]: node["document_order"] for node in nodes}
    scored = [{**row, "document_order": order_by_id[row["node_id"]]} for row in assignments]
    result = {
        "label": label,
        "embedding": metadata,
        "nodes": len(nodes),
        "segments": len(segments),
        "logical_items": len({row["content_item_id"] for row in assignments}),
        "exact": evaluate(reference, scored, 0),
        "tolerance_1": evaluate(reference, scored, 1),
        "tolerance_2": evaluate(reference, scored, 2),
        "whole_page_interruptions": standalone,
        "resumptions": resumptions,
    }
    write_jsonl(target / "embedding_vectors.jsonl", vectors)
    write_json(target / "embedding_metadata.json", metadata)
    write_jsonl(target / "assignments.jsonl", assignments)
    write_jsonl(target / "segments.jsonl", segments)
    write_jsonl(target / "boundary_diagnostics.jsonl", diagnostics)
    write_json(target / "evaluation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Controlled 2x2 enrichment/embedding segmentation comparison")
    parser.add_argument("--qwen25-nodes", required=True)
    parser.add_argument("--qwen35-nodes", required=True)
    parser.add_argument("--bge-model", required=True)
    parser.add_argument("--aligned-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    variants = {
        "qwen2.5_tfidf": read_jsonl(args.qwen25_nodes),
        "qwen3.5_tfidf": read_jsonl(args.qwen35_nodes),
        "qwen2.5_bge_m3": read_jsonl(args.qwen25_nodes),
        "qwen3.5_bge_m3": read_jsonl(args.qwen35_nodes),
    }
    baseline_ids = [row["node_id"] for row in variants["qwen2.5_tfidf"]]
    for label, nodes in variants.items():
        if [row["node_id"] for row in nodes] != baseline_ids:
            raise ValueError(f"{label} does not contain the identical ordered Evidence-node scaffold")
    reference = materialize(variants["qwen2.5_tfidf"])
    write_jsonl(output / "ground_truth_items.jsonl", reference)

    results = []
    for label, nodes in variants.items():
        model = args.bge_model if label.endswith("bge_m3") else None
        result = run_cell(label, nodes, model, Path(args.aligned_dir), output, reference)
        results.append(result)
        print(json.dumps({"completed": label, "exact_f1": result["exact"]["f1"],
                          "tolerance_1_f1": result["tolerance_1"]["f1"]}), flush=True)

    report = {
        "design": "2x2 controlled comparison",
        "fixed": ["Evidence node IDs and order", "original text", "layout inputs",
                  "segmentation algorithm and thresholds", "ground truth"],
        "varied": ["enrichment model", "embedding method"],
        "embedding_input_mode": "original_plus_summary",
        "reference_items": len(reference),
        "results": [{"label": row["label"], "segments": row["segments"],
                     "exact": {k: row["exact"][k] for k in ("precision", "recall", "f1", "matched")},
                     "tolerance_1": {k: row["tolerance_1"][k] for k in ("precision", "recall", "f1", "matched")}}
                    for row in results],
    }
    write_json(output / "comparison.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
