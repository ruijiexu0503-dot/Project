from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .commercial_boundary_refinement import (
    extract_commercial_boundary_features,
    refine_commercial_boundaries,
)
from .io_utils import read_jsonl, write_json, write_jsonl
from .magazine_ground_truth import evaluate_items
from .non_llm_ad_reconciliation import ad_features, fit_ad_model
from .non_llm_magazine_experiment import DOCS, _labels, _reference, _score, _spec
from .structural_span_segmentation import fit_boundary_model_from_labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Held-out non-LLM commercial boundary refinement")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--aligned-root", default="../parsing/output/hybrid_deepseek_layout_split_render/aligned_json")
    parser.add_argument("--page-experiment", default="output/non_llm_page_ad_experiment")
    parser.add_argument("--experiment-dir", default="output/non_llm_commercial_experiment")
    parser.add_argument("--add-threshold", type=float, default=.82)
    parser.add_argument("--remove-threshold", type=float, default=.18)
    parser.add_argument("--ad-threshold", type=float, default=.58)
    args = parser.parse_args()
    output = Path(args.output_root); aligned = Path(args.aligned_root)
    page_experiment = Path(args.page_experiment); experiment = Path(args.experiment_dir)
    experiment.mkdir(parents=True, exist_ok=True)

    data = {}
    for doc in DOCS:
        spec = _spec(output, doc)
        nodes = sorted(read_jsonl(output / "evidence_graph" / doc / "evidence_nodes.jsonl"),
                       key=lambda row: row["document_order"])
        embeddings = read_jsonl(spec["embeddings"])
        features, feature_names = ad_features(nodes, embeddings, aligned / doc)
        reference_rows, reference_tuples = _reference(doc, nodes)
        data[doc] = {
            "nodes": nodes, "embeddings": embeddings, "node_features": features,
            "node_feature_names": feature_names, "node_labels": _labels(reference_tuples, len(nodes)),
            "reference": reference_rows, "reference_tuples": reference_tuples,
            "baseline": read_jsonl(page_experiment / doc / "assignments.jsonl"),
        }

    reports = []
    for held_out in DOCS:
        training = [doc for doc in DOCS if doc != held_out]
        ad_model = fit_ad_model(
            data[held_out]["node_feature_names"],
            [data[doc]["node_features"] for doc in training],
            [data[doc]["node_labels"] for doc in training], epochs=320, balance_classes=True)
        for doc in DOCS:
            data[doc]["node_probabilities"] = ad_model.probabilities(data[doc]["node_features"])
            names, features, metadata = extract_commercial_boundary_features(
                data[doc]["nodes"], data[doc]["embeddings"], data[doc]["node_probabilities"],
                data[doc]["baseline"], aligned / doc)
            data[doc]["boundary_names"] = names
            data[doc]["boundary_features"] = features
            data[doc]["boundary_metadata"] = metadata
            starts = {int(row[0]) for row in data[doc]["reference_tuples"][1:]}
            data[doc]["boundary_labels"] = np.asarray(
                [float(order in starts) for order in range(2, len(data[doc]["nodes"]) + 1)])
        train_features = np.vstack([data[doc]["boundary_features"] for doc in training])
        train_labels = np.concatenate([data[doc]["boundary_labels"] for doc in training])
        boundary_model = fit_boundary_model_from_labels(
            data[held_out]["boundary_names"], train_features, train_labels, l2=2.5)
        target = data[held_out]
        boundary_probabilities = boundary_model.probabilities(target["boundary_features"])
        assignments, changes = refine_commercial_boundaries(
            target["nodes"], target["baseline"], target["node_probabilities"],
            boundary_probabilities, target["boundary_metadata"],
            add_threshold=args.add_threshold, remove_threshold=args.remove_threshold,
            ad_threshold=args.ad_threshold)
        # Detailed rows make threshold and failure analysis reproducible. The
        # reference flag is evaluation-only and is never passed to the decoder.
        from .commercial_boundary_refinement import assignment_boundaries
        existing_boundaries = assignment_boundaries(target["nodes"], target["baseline"])
        reference_boundaries = {int(row[0]) for row in target["reference_tuples"][1:]}
        diagnostics = []
        for index, (probability, metadata) in enumerate(
                zip(boundary_probabilities, target["boundary_metadata"]), start=1):
            diagnostics.append({**metadata, "boundary_probability": round(float(probability), 6),
                                "left_ad_probability": round(float(target["node_probabilities"][index - 1]), 6),
                                "right_ad_probability": round(float(target["node_probabilities"][index]), 6),
                                "baseline_boundary": metadata["start_document_order"] in existing_boundaries,
                                "reference_boundary": metadata["start_document_order"] in reference_boundaries})
        baseline_exact = _score(target["reference"], target["nodes"], target["baseline"], 0)
        baseline_tolerance = _score(target["reference"], target["nodes"], target["baseline"], 1)
        exact = _score(target["reference"], target["nodes"], assignments, 0)
        tolerance = _score(target["reference"], target["nodes"], assignments, 1)
        _, baseline_items = evaluate_items(target["reference"], target["nodes"], target["baseline"])
        item_rows, items = evaluate_items(target["reference"], target["nodes"], assignments)
        report = {
            "doc_id": held_out, "method": "non_llm_commercial_boundary_refinement_v1",
            "uses_llm_or_vlm": False, "training_docs": training,
            "thresholds": {"add": args.add_threshold, "remove": args.remove_threshold,
                           "ad": args.ad_threshold, "fitted_boundary": boundary_model.threshold},
            "changes": {"added": sum(row["action"] == "add" for row in changes),
                        "removed": sum(row["action"] == "remove" for row in changes)},
            "baseline_exact": baseline_exact, "exact": exact,
            "baseline_tolerance_1": baseline_tolerance, "tolerance_1": tolerance,
            "baseline_item_summary": baseline_items, "item_summary": items,
        }
        target_dir = experiment / held_out; target_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(target_dir / "assignments.jsonl", assignments)
        write_jsonl(target_dir / "boundary_changes.jsonl", changes)
        write_jsonl(target_dir / "boundary_diagnostics.jsonl", diagnostics)
        write_jsonl(target_dir / "item_evaluation.jsonl", item_rows)
        write_json(target_dir / "evaluation.json", report)
        reports.append(report)
        print(json.dumps({"doc_id": held_out, "baseline_ads": baseline_items["commercial"]["clean"],
                          "new_ads": items["commercial"]["clean"],
                          "baseline_f1": baseline_exact["f1"], "new_f1": exact["f1"]}), flush=True)
    comparison = {"method": "non_llm_commercial_boundary_refinement_v1",
                  "evaluation": "leave-one-magazine-out", "uses_llm_or_vlm": False,
                  "documents": reports}
    write_json(experiment / "comparison.json", comparison)
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
