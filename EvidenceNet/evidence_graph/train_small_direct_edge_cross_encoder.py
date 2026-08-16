from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _text(node: dict) -> str:
    return str(node.get("original_markdown") or node.get("plain_text") or "").strip()


def _load_document(nodes_path: str, truth_path: str, label_field: str) -> list[dict]:
    nodes = {row["node_id"]: row for row in read_jsonl(nodes_path)}
    rows = []
    for truth in read_jsonl(truth_path):
        a, b = truth["node_a"], truth["node_b"]
        if a not in nodes or b not in nodes:
            raise ValueError(f"GT endpoint missing from nodes: {a}, {b}")
        if label_field == "gold_label":
            label = truth["gold_label"] == "RELATION"
        else:
            label = bool(truth[label_field])
        rows.append({
            "pair_id": "||".join(_pair(a, b)), "node_a": a, "node_b": b,
            "text_a": _text(nodes[a]), "text_b": _text(nodes[b]), "label": int(label),
        })
    return rows


def _calibration_split(rows: list[dict], fraction: float = 0.2) -> tuple[list[dict], list[dict]]:
    train, calibration = [], []
    by_label = {0: [], 1: []}
    for row in rows:
        by_label[row["label"]].append(row)
    for label_rows in by_label.values():
        ordered = sorted(
            label_rows,
            key=lambda row: hashlib.sha256(f"small-edge-v1|{row['pair_id']}".encode()).hexdigest(),
        )
        count = max(1, round(len(ordered) * fraction))
        calibration.extend(ordered[:count])
        train.extend(ordered[count:])
    return sorted(train, key=lambda row: row["pair_id"]), sorted(calibration, key=lambda row: row["pair_id"])


def _metrics(rows: list[dict], scores: list[float], threshold: float) -> dict:
    predicted = [score >= threshold for score in scores]
    tp = sum(bool(row["label"]) and pred for row, pred in zip(rows, predicted))
    fp = sum(not bool(row["label"]) and pred for row, pred in zip(rows, predicted))
    fn = sum(bool(row["label"]) and not pred for row, pred in zip(rows, predicted))
    tn = sum(not bool(row["label"]) and not pred for row, pred in zip(rows, predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": round(threshold, 6), "true_positive": tp, "false_positive": fp,
        "false_negative": fn, "true_negative": tn, "precision": round(precision, 4),
        "recall": round(recall, 4), "f1": round(f1, 4),
    }


def _best_threshold(rows: list[dict], scores: list[float]) -> tuple[float, dict]:
    candidates = sorted(set([0.0, 1.0] + scores))
    candidates += [(a + b) / 2 for a, b in zip(candidates, candidates[1:])]
    ranked = []
    for threshold in candidates:
        metrics = _metrics(rows, scores, threshold)
        ranked.append((metrics["f1"], metrics["precision"], metrics["recall"], threshold, metrics))
    _, _, _, threshold, metrics = max(ranked)
    return threshold, metrics


def _collate(tokenizer, max_length: int):
    def collate(rows: list[dict]) -> dict:
        encoded = tokenizer(
            [row["text_a"] for row in rows], [row["text_b"] for row in rows],
            padding=True, truncation="longest_first", max_length=max_length, return_tensors="pt",
        )
        encoded["labels"] = torch.tensor([row["label"] for row in rows], dtype=torch.long)
        return encoded
    return collate


@torch.inference_mode()
def _pair_scores(model, tokenizer, rows: list[dict], device: torch.device,
                 batch_size: int, max_length: int) -> list[float]:
    model.eval()
    scores_by_orientation = []
    for reverse in (False, True):
        oriented = [
            {**row, "text_a": row["text_b"], "text_b": row["text_a"]} if reverse else row
            for row in rows
        ]
        loader = DataLoader(oriented, batch_size=batch_size, shuffle=False,
                            collate_fn=_collate(tokenizer, max_length))
        scores = []
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items() if key != "labels"}
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits = model(**batch).logits
            scores.extend(torch.softmax(logits.float(), dim=-1)[:, 1].cpu().tolist())
        scores_by_orientation.append(scores)
    return [(forward + reverse) / 2 for forward, reverse in zip(*scores_by_orientation)]


@torch.inference_mode()
def _cosine_scores(model, tokenizer, rows: list[dict], device: torch.device,
                   batch_size: int, max_length: int) -> list[float]:
    base = model.base_model
    base.eval()
    texts = {}
    for row in rows:
        texts[row["node_a"]] = row["text_a"]
        texts[row["node_b"]] = row["text_b"]
    node_ids, vectors = sorted(texts), {}
    for start in range(0, len(node_ids), batch_size):
        ids = node_ids[start:start + batch_size]
        encoded = tokenizer([texts[node_id] for node_id in ids], padding=True, truncation=True,
                            max_length=max_length, return_tensors="pt").to(device)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            hidden = base(**encoded).last_hidden_state[:, 0]
        hidden = F.normalize(hidden.float(), dim=-1).cpu()
        vectors.update({node_id: vector for node_id, vector in zip(ids, hidden)})
    return [float(torch.dot(vectors[row["node_a"]], vectors[row["node_b"]])) for row in rows]


def _unfreeze_last_layers(model, count: int) -> None:
    for parameter in model.base_model.parameters():
        parameter.requires_grad = False
    encoder = model.base_model.encoder.layer
    for layer in encoder[-count:]:
        for parameter in layer.parameters():
            parameter.requires_grad = True
    for parameter in model.classifier.parameters():
        parameter.requires_grad = True


def _train_fold(name: str, train_document: list[dict], test_document: list[dict],
                model_path: str, output: Path, args) -> dict:
    random.seed(args.seed); torch.manual_seed(args.seed); torch.cuda.manual_seed_all(args.seed)
    device = torch.device("cuda")
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path, num_labels=2, local_files_only=True,
    ).to(device)
    _unfreeze_last_layers(model, args.train_last_n_layers)
    train_rows, calibration_rows = _calibration_split(train_document)
    baseline_rows = calibration_rows + test_document
    baseline_scores = _cosine_scores(
        model, tokenizer, baseline_rows, device, args.eval_batch_size, args.max_length
    )
    cosine_calibration = baseline_scores[:len(calibration_rows)]
    cosine_test = baseline_scores[len(calibration_rows):]
    cosine_threshold, cosine_calibration_metrics = _best_threshold(calibration_rows, cosine_calibration)

    augmented = []
    for row in train_rows:
        augmented.extend([row, {**row, "text_a": row["text_b"], "text_b": row["text_a"]}])
    random.shuffle(augmented)
    counts = [sum(row["label"] == label for row in train_rows) for label in (0, 1)]
    weights = torch.tensor([
        len(train_rows) / (2 * max(1, counts[0])), len(train_rows) / (2 * max(1, counts[1]))
    ], device=device)
    loader = DataLoader(augmented, batch_size=args.batch_size, shuffle=True,
                        collate_fn=_collate(tokenizer, args.max_length))
    backbone = [parameter for parameter in model.base_model.parameters() if parameter.requires_grad]
    classifier = list(model.classifier.parameters())
    optimizer = torch.optim.AdamW([
        {"params": backbone, "lr": args.learning_rate},
        {"params": classifier, "lr": args.classifier_learning_rate},
    ], weight_decay=args.weight_decay)
    training_log = []
    for epoch in range(1, args.epochs + 1):
        model.train(); total_loss = 0.0
        for batch in loader:
            labels = batch.pop("labels").to(device)
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits = model(**batch).logits
                loss = F.cross_entropy(logits.float(), labels, weight=weights, label_smoothing=0.03)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step(); total_loss += float(loss.detach())
        calibration_scores = _pair_scores(
            model, tokenizer, calibration_rows, device, args.eval_batch_size, args.max_length
        )
        threshold, calibration_metrics = _best_threshold(calibration_rows, calibration_scores)
        training_log.append({"epoch": epoch, "loss": round(total_loss / len(loader), 6),
                             "threshold": threshold, "calibration": calibration_metrics})

    calibration_scores = _pair_scores(
        model, tokenizer, calibration_rows, device, args.eval_batch_size, args.max_length
    )
    threshold, calibration_metrics = _best_threshold(calibration_rows, calibration_scores)
    test_scores = _pair_scores(model, tokenizer, test_document, device, args.eval_batch_size, args.max_length)
    predictions = [{
        **{key: row[key] for key in ("pair_id", "node_a", "node_b", "label")},
        "score": round(score, 8), "predicted": score >= threshold,
    } for row, score in zip(test_document, test_scores)]
    fold = {
        "name": name, "train_pairs": len(train_rows), "calibration_pairs": len(calibration_rows),
        "test_pairs": len(test_document), "train_label_counts": {"negative": counts[0], "positive": counts[1]},
        "cross_encoder": {
            "calibration": calibration_metrics, "test": _metrics(test_document, test_scores, threshold),
        },
        "cosine_similarity_baseline": {
            "calibration": cosine_calibration_metrics,
            "test": _metrics(test_document, cosine_test, cosine_threshold),
        },
        "training_log": training_log,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "summary.json", fold)
    write_jsonl(output / "test_predictions.jsonl", predictions)
    del model, optimizer
    torch.cuda.empty_cache()
    return fold


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a small direct-edge pair cross-encoder")
    parser.add_argument("--model", required=True)
    parser.add_argument("--gw-nodes", required=True)
    parser.add_argument("--gw-ground-truth", required=True)
    parser.add_argument("--detr-nodes", required=True)
    parser.add_argument("--detr-ground-truth", required=True)
    parser.add_argument("--a-tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--eval-batch-size", type=int, default=12)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--train-last-n-layers", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--classifier-learning-rate", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required for the cross-encoder pilot")

    gw = _load_document(args.gw_nodes, args.gw_ground_truth, "gold_label")
    detr = _load_document(args.detr_nodes, args.detr_ground_truth, "semantic_exists")
    output = Path(args.output)
    detr_to_gw = _train_fold("DETR_to_GW150914", detr, gw, args.model, output / "detr_to_gw", args)
    gw_to_detr = _train_fold("GW150914_to_DETR", gw, detr, args.model, output / "gw_to_detr", args)

    gw_predictions = {
        row["pair_id"]: row for row in read_jsonl(output / "detr_to_gw" / "test_predictions.jsonl")
    }
    a_predictions = []
    for task in read_jsonl(args.a_tasks):
        row = gw_predictions[task["pair_id"]]
        keep = bool(row["predicted"])
        a_predictions.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"], "valid": True,
            "verdict": "KEEP_EDGE" if keep else "REJECT_EDGE",
            "directness": "SMALL_CROSS_ENCODER_KEEP" if keep else "SMALL_CROSS_ENCODER_REJECT",
            "confidence": row["score"], "model": str(Path(args.model).resolve()),
            "prompt_version": "bge-m3-direct-edge-cross-encoder-v1",
        })
    write_jsonl(output / "gw_a_edge_predictions.jsonl", a_predictions)
    report = {
        "method": "BGE-M3 pair cross-encoder with symmetric training and document-held-out testing",
        "model": str(Path(args.model).resolve()), "folds": [detr_to_gw, gw_to_detr],
        "gw_a_edges": len(a_predictions), "uses_generative_llm": False,
        "warning": (
            "DETR audit pairs are selection-biased toward positives; this is a proof-of-concept, not a production "
            "generalization estimate."
        ),
        "production_graph_modified": False,
    }
    write_json(output / "summary.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
