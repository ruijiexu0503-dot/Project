from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .io_utils import read_jsonl, write_json, write_jsonl
from .magazine_ground_truth import REFERENCE as OTHER_REFERENCE, evaluate_items, materialize as other_materialize
from .non_llm_ad_reconciliation import (
    ad_features,
    aggregate_page_features,
    filter_full_page_ad_predictions,
    fit_ad_model,
    page_labels_to_nodes,
    reconcile_ad_spans,
    select_high_precision_threshold,
)
from .segmentation_ground_truth import REFERENCE as REFERENCE_2025
from .segmentation_ground_truth import evaluate, materialize as materialize_2025


DOCS = (
    "CERNCourier2022NovDec-digitaledition",
    "CERNCourier2025JanFeb-digitaledition",
    "CERNCourier2026MayJun-digitaledition",
)


def _spec(output: Path, doc: str) -> dict[str, Path]:
    comparison = output / "segmentation_comparisons" / doc
    if doc == DOCS[1]:
        variant = comparison / "controlled_2x2" / "qwen2.5_bge_m3"
        return {"embeddings": variant / "embedding_vectors.jsonl",
                "baseline": variant / "assignments.jsonl"}
    current = comparison / "current_pipeline"
    return {"embeddings": current / "embedding_vectors.jsonl",
            "baseline": current / "global_merge" / "assignments.jsonl"}


def _reference(doc: str, nodes: list[dict]) -> tuple[list[dict], list[tuple]]:
    if doc == DOCS[1]:
        return materialize_2025(nodes), REFERENCE_2025
    return other_materialize(doc, nodes), OTHER_REFERENCE[doc]


def _labels(reference: list[tuple], count: int) -> np.ndarray:
    kinds = {}
    for index, (start, _, kind) in enumerate(reference):
        end = reference[index + 1][0] - 1 if index + 1 < len(reference) else count
        for order in range(start, end + 1):
            kinds[order] = kind
    return np.asarray([kinds[order] == "commercial" for order in range(1, count + 1)])


def _score(reference: list[dict], nodes: list[dict], assignments: list[dict], tolerance: int) -> dict:
    order = {node["node_id"]: node["document_order"] for node in nodes}
    scored = [{**row, "document_order": order[row["node_id"]]} for row in assignments]
    return evaluate(reference, scored, tolerance)


def main() -> None:
    parser = argparse.ArgumentParser(description="Leave-one-magazine-out non-LLM full-page ad reconciliation")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--aligned-root", default="../parsing/output/hybrid_deepseek_layout_split_render/aligned_json")
    parser.add_argument("--experiment-dir", default="output/non_llm_page_ad_experiment")
    args = parser.parse_args(); output = Path(args.output_root); aligned = Path(args.aligned_root)
    experiment = Path(args.experiment_dir); experiment.mkdir(parents=True, exist_ok=True)

    data = {}
    for doc in DOCS:
        paths = _spec(output, doc)
        nodes = sorted(read_jsonl(output / "evidence_graph" / doc / "evidence_nodes.jsonl"),
                       key=lambda row: row["document_order"])
        node_features, node_names = ad_features(nodes, read_jsonl(paths["embeddings"]), aligned / doc)
        page_features, page_names, page_metadata = aggregate_page_features(nodes, node_features, node_names)
        reference_rows, reference_tuples = _reference(doc, nodes)
        node_labels = _labels(reference_tuples, len(nodes))
        page_labels = np.asarray([bool(np.all(node_labels[row["node_indices"]])) for row in page_metadata])
        data[doc] = {"nodes": nodes, "features": page_features, "feature_names": page_names,
                     "page_metadata": page_metadata, "page_labels": page_labels,
                     "baseline": read_jsonl(paths["baseline"]), "reference": reference_rows}

    reports = []
    for held_out in DOCS:
        training = [doc for doc in DOCS if doc != held_out]
        model = fit_ad_model(data[held_out]["feature_names"],
                             [data[doc]["features"] for doc in training],
                             [data[doc]["page_labels"] for doc in training],
                             epochs=300, balance_classes=False)
        threshold = select_high_precision_threshold(
            model, [data[doc]["features"] for doc in training],
            [data[doc]["page_labels"] for doc in training])
        target = data[held_out]; probabilities = model.probabilities(target["features"])
        raw_page_predictions = probabilities >= threshold
        page_predictions = filter_full_page_ad_predictions(
            target["nodes"], raw_page_predictions, target["page_metadata"])
        node_predictions = page_labels_to_nodes(page_predictions, target["page_metadata"], len(target["nodes"]))
        # Whole-page predictions have a uniform page confidence. Reconciliation
        # snaps their edges to nearby structural cuts and leaves mixed pages alone.
        node_probabilities = np.zeros(len(target["nodes"]), dtype=np.float64)
        page_rows = []
        for probability, raw_predicted, predicted, truth, page in zip(
                probabilities, raw_page_predictions, page_predictions,
                target["page_labels"], target["page_metadata"]):
            node_probabilities[page["node_indices"]] = probability
            page_rows.append({k: v for k, v in page.items() if k != "node_indices"})
            page_rows[-1].update(probability=round(float(probability), 6),
                                 raw_predicted_ad=bool(raw_predicted), predicted_ad=bool(predicted),
                                 reference_pure_ad=bool(truth))
        assignments, spans = reconcile_ad_spans(
            target["nodes"], target["baseline"], node_predictions, node_probabilities, snap_radius=1)
        baseline_exact = _score(target["reference"], target["nodes"], target["baseline"], 0)
        baseline_tolerance_1 = _score(
            target["reference"], target["nodes"], target["baseline"], 1)
        exact = _score(target["reference"], target["nodes"], assignments, 0)
        tolerance_1 = _score(target["reference"], target["nodes"], assignments, 1)
        _, baseline_item_summary = evaluate_items(
            target["reference"], target["nodes"], target["baseline"])
        item_rows, item_summary = evaluate_items(target["reference"], target["nodes"], assignments)
        page_tp = int(np.sum(page_predictions & target["page_labels"]))
        report = {"doc_id": held_out, "method": "non_llm_high_precision_full_page_ad_reconciliation_v1",
                  "uses_llm_or_vlm": False, "training_docs": training, "threshold": threshold,
                  "pure_ad_page_precision": round(page_tp / max(1, int(np.sum(page_predictions))), 4),
                  "pure_ad_page_recall": round(page_tp / max(1, int(np.sum(target["page_labels"]))), 4),
                  "predicted_ad_pages": int(np.sum(page_predictions)), "predicted_ad_spans": len(spans),
                  "baseline_exact": baseline_exact, "baseline_tolerance_1": baseline_tolerance_1,
                  "exact": exact, "tolerance_1": tolerance_1,
                  "baseline_item_summary": baseline_item_summary, "item_summary": item_summary}
        target_dir = experiment / held_out; target_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(target_dir / "assignments.jsonl", assignments)
        write_jsonl(target_dir / "page_ad_predictions.jsonl", page_rows)
        write_jsonl(target_dir / "ad_spans.jsonl", spans)
        write_jsonl(target_dir / "item_evaluation.jsonl", item_rows)
        write_json(target_dir / "evaluation.json", report); reports.append(report)
        print(json.dumps({"doc_id": held_out, "baseline_f1": baseline_exact["f1"],
                          "new_f1": exact["f1"]}), flush=True)
    comparison = {"method": "non_llm_high_precision_full_page_ad_reconciliation_v1",
                  "evaluation": "leave-one-magazine-out", "uses_llm_or_vlm": False,
                  "documents": reports}
    write_json(experiment / "comparison.json", comparison)
    print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
