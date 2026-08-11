from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .io_utils import read_jsonl, write_json, write_jsonl
from .segmentation_ground_truth import evaluate


RUNNING = re.compile(
    r"^(?:cern\s*courier|volume\s+\d+|january/february|may/june|november/december|"
    r"\d{1,2}\s+(?:cern\s+courier|may/june|november/december))\b", re.I)
FURTHER_READING = re.compile(r"^(?:further reading|references?|doi\b|arxiv\b)", re.I)
BYLINE = re.compile(r"^(?:by|written by|interview by|reviewed by)\s+[A-Z]", re.I)
CAPTION = re.compile(r"^(?:fig(?:ure)?\.?\s*\d*|table\s*\d+|image\b|credit\b|pictured\b)", re.I)
DEPARTMENT = re.compile(
    r"^(?:news analysis|news digest|energy frontiers|field notes|opinion|interview|reviews|"
    r"appointments(?: and awards)?|people|careers|background|astrowatch|policy|"
    r"education and outreach|future circular collider|reports from .+)$", re.I)
ANAPHOR = re.compile(
    r"^(?:this|these|those|such|they|their|it|the former|the latter|following|however|while|"
    r"whereas|and|but|in addition|furthermore)\b", re.I)
ADVERTISING = re.compile(
    r"\b(?:advertisement|register now|registration open|contact us|visit us|apply now|"
    r"www\.|sales@|vacuum solutions|power supply|signal generator)\b", re.I)
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’-]*")

ROLES = (
    "RUNNING_HEADER", "FURTHER_READING", "BYLINE", "CAPTION", "DEPARTMENT_LABEL",
    "TITLE", "ADVERTISEMENT", "BODY",
)


def _text(node: dict[str, Any]) -> str:
    return " ".join((node.get("plain_text") or node.get("original_markdown") or "").split())


def _page(node: dict[str, Any]) -> str:
    return (node.get("page_ids") or ["NO_PAGE"])[0]


def _compact_title(text: str) -> bool:
    words = TOKEN.findall(text)
    if not 2 <= len(words) <= 14 or len(text) > 130 or text.endswith((".", ",", ";", "?", "!")):
        return False
    letters = [char for char in text if char.isalpha()]
    upper = sum(char.isupper() for char in letters) / max(1, len(letters))
    title_case = sum(word[:1].isupper() for word in words) / len(words)
    return upper >= .72 or title_case >= .78


def infer_roles(nodes: list[dict[str, Any]], title_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign one inspectable structural role to every retained Evidence node."""
    contents_pages = {
        row.get("page") for row in title_rows
        if str(row.get("title", "")).strip().lower() == "in this issue"
    }
    explicit_titles = {
        row.get("associated_order")
        for row in title_rows
        if row.get("associated_order")
        and row.get("page") not in contents_pages
        and row.get("detection") == "explicit_heading"
        and row.get("classification") != "SECTION_OR_RUNNING_LABEL"
        and str(row.get("title", "")).strip().lower() != "in this issue"
    }
    rows = []
    for index, node in enumerate(nodes):
        text = _text(node); words = text.split(); reason = "default_prose"
        following = _text(nodes[index + 1]) if index + 1 < len(nodes) and _page(nodes[index + 1]) == _page(node) else ""
        if RUNNING.search(text):
            role, reason = "RUNNING_HEADER", "running_header_pattern"
        elif FURTHER_READING.search(text):
            role, reason = "FURTHER_READING", "reference_pattern"
        elif BYLINE.search(text):
            role, reason = "BYLINE", "byline_pattern"
        elif node.get("evidence_type") in {"visual", "figure", "table"} or CAPTION.search(text):
            role, reason = "CAPTION", "caption_or_visual_pattern"
        elif DEPARTMENT.fullmatch(text) or (
            0 < len(words) <= 6 and len(text) <= 75 and text.isupper()
        ):
            role, reason = "DEPARTMENT_LABEL", "compact_department_pattern"
        elif node.get("document_order") in explicit_titles or (_compact_title(text) and len(following) >= 180):
            role, reason = "TITLE", "source_heading_or_title_form"
        elif ADVERTISING.search(text) and len(text) <= 500:
            role, reason = "ADVERTISEMENT", "commercial_call_to_action"
        else:
            role = "BODY"
        rows.append({"node_id": node["node_id"], "document_order": node["document_order"],
                     "page": _page(node), "role": role, "reason": reason,
                     "text_preview": text[:180]})
    return rows


def build_boundary_zones(nodes: list[dict[str, Any]], roles: list[dict[str, Any]],
                         title_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Represent a title/deck/byline neighborhood without forcing an exact cut."""
    role_by_order = {row["document_order"]: row["role"] for row in roles}
    node_by_order = {node["document_order"]: node for node in nodes}
    contents_pages = {
        row.get("page") for row in title_rows
        if str(row.get("title", "")).strip().lower() == "in this issue"
    }
    candidates: dict[int, list[dict[str, Any]]] = {}
    for title in title_rows:
        order = title.get("associated_order")
        if (not order or title.get("classification") == "SECTION_OR_RUNNING_LABEL"
                or title.get("page") in contents_pages):
            continue
        page = title.get("page")
        page_text = " ".join(_text(node) for node in nodes if _page(node) == page).lower()
        if "in this issue" in page_text:
            continue
        candidates.setdefault(int(order), []).append(title)
    zones = []
    for anchor, titles in sorted(candidates.items()):
        members = []
        for order in range(max(1, anchor - 2), min(len(nodes), anchor + 3) + 1):
            node = node_by_order.get(order)
            if node and _page(node) == _page(node_by_order[anchor]):
                members.append({"document_order": order, "node_id": node["node_id"],
                                "role": role_by_order[order], "text_preview": _text(node)[:120]})
        zones.append({"anchor_order": anchor,
                      "zone_start_order": members[0]["document_order"] if members else anchor,
                      "zone_end_order": members[-1]["document_order"] if members else anchor,
                      "titles": [row.get("title", "") for row in titles],
                      "strong": any(row.get("classification") == "LIKELY_STARTS_NEW_ITEM" for row in titles),
                      "best_context_margin": max(float(row.get("context_margin", 0)) for row in titles),
                      "members": members})
    return zones


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-8)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def extract_features(nodes: list[dict[str, Any]], embedding_rows: list[dict[str, Any]],
                     diagnostics: list[dict[str, Any]], title_rows: list[dict[str, Any]],
                     roles: list[dict[str, Any]]) -> tuple[list[str], np.ndarray, dict[str, Any]]:
    nodes = sorted(nodes, key=lambda row: row["document_order"])
    vector_by_id = {row["node_id"]: row["vector"] for row in embedding_rows}
    vectors = _normalise_rows(np.asarray([vector_by_id[node["node_id"]] for node in nodes], dtype=np.float64))
    diag_by_right = {row.get("right_id"): row for row in diagnostics}
    role_by_id = {row["node_id"]: row["role"] for row in roles}

    page_text = {}
    for node in nodes:
        page_text.setdefault(_page(node), []).append(_text(node).lower())
    contents_pages = {page for page, values in page_text.items() if "in this issue" in " ".join(values)}
    contents_pages.update(
        row.get("page") for row in title_rows
        if str(row.get("title", "")).strip().lower() == "in this issue"
    )

    titles_by_order: dict[int, list[dict[str, Any]]] = {}
    for row in title_rows:
        order = row.get("associated_order")
        if order and row.get("page") not in contents_pages:
            titles_by_order.setdefault(int(order), []).append(row)

    names = [
        "node_similarity", "window_similarity", "prominence", "boundary_score",
        "page_change", "diagnostic_accepted", "diagnostic_title_start", "source_heading_strong",
        "anaphoric_start", "possible_continuation_left", "possible_continuation_right",
        "running_or_placeholder", "left_internal_similarity", "right_internal_similarity",
        "split_gain", "right_length_log", "right_compact", "right_upper_ratio",
        "title_likely_at_0", "title_likely_at_p1", "title_likely_at_m1",
        "title_explicit_at_0", "title_missing_at_0", "title_margin_at_0", "title_following_at_0",
    ]
    names += [f"left_role_{role}" for role in ROLES]
    names += [f"right_role_{role}" for role in ROLES]
    rows = []
    metadata = {"contents_pages": sorted(contents_pages)}
    for index in range(1, len(nodes)):
        left, right = nodes[index - 1], nodes[index]
        diagnostic = diag_by_right.get(right["node_id"], {})
        left_slice = vectors[max(0, index - 3):index]
        right_slice = vectors[index:min(len(nodes), index + 3)]
        left_centroid = np.mean(left_slice, axis=0); left_centroid /= max(np.linalg.norm(left_centroid), 1e-8)
        right_centroid = np.mean(right_slice, axis=0); right_centroid /= max(np.linalg.norm(right_centroid), 1e-8)
        cross = float(vectors[index - 1] @ vectors[index])
        left_internal = float(np.mean(np.sum(left_slice[:-1] * left_slice[1:], axis=1))) if len(left_slice) > 1 else cross
        right_internal = float(np.mean(np.sum(right_slice[:-1] * right_slice[1:], axis=1))) if len(right_slice) > 1 else cross
        split_gain = (left_internal + right_internal) / 2 - float(left_centroid @ right_centroid)
        text = _text(right); letters = [char for char in text if char.isalpha()]
        title_at = titles_by_order.get(index + 1, [])

        def likely(offset: int) -> float:
            return float(any(row.get("classification") == "LIKELY_STARTS_NEW_ITEM"
                             for row in titles_by_order.get(index + 1 + offset, [])))

        values = [
            _safe_float(diagnostic.get("node_similarity", cross)),
            _safe_float(diagnostic.get("window_similarity", left_centroid @ right_centroid)),
            _safe_float(diagnostic.get("prominence", split_gain)),
            _safe_float(diagnostic.get("boundary_score")),
            float(_page(left) != _page(right)), float(bool(diagnostic.get("accepted"))),
            float(bool(diagnostic.get("title_start"))),
            float(bool((diagnostic.get("source_heading") or {}).get("strong"))),
            float(bool(diagnostic.get("anaphoric_start") or ANAPHOR.search(text))),
            float(bool(left.get("possible_continuation"))), float(bool(right.get("possible_continuation"))),
            float(bool(diagnostic.get("running_metadata") or diagnostic.get("placeholder")
                       or role_by_id[right["node_id"]] == "RUNNING_HEADER")),
            left_internal, right_internal, split_gain, math.log1p(len(text)),
            float(len(text) <= 140),
            sum(char.isupper() for char in letters) / max(1, len(letters)),
            likely(0), likely(1), likely(-1),
            float(any(row.get("detection") == "explicit_heading" for row in title_at)),
            float(any(row.get("coverage_status") == "MISSING_FROM_EVIDENCE" for row in title_at)),
            max([_safe_float(row.get("context_margin")) for row in title_at] or [0.0]),
            max([_safe_float(row.get("following_similarity")) for row in title_at] or [0.0]),
        ]
        values += [float(role_by_id[left["node_id"]] == role) for role in ROLES]
        values += [float(role_by_id[right["node_id"]] == role) for role in ROLES]
        rows.append(values)
    return names, np.asarray(rows, dtype=np.float64), metadata


@dataclass
class BoundaryModel:
    feature_names: list[str]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    threshold: float

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        standard = (features - self.mean) / self.scale
        design = np.column_stack([np.ones(len(standard)), standard])
        logits = np.clip(design @ self.weights, -35, 35)
        return 1 / (1 + np.exp(-logits))

    def as_json(self) -> dict[str, Any]:
        return {"method": "structural-role-boundary-model-v1", "feature_names": self.feature_names,
                "mean": self.mean.tolist(), "scale": self.scale.tolist(),
                "weights": self.weights.tolist(), "threshold": self.threshold}


def _f1(y: np.ndarray, predicted: np.ndarray) -> float:
    tp = int(np.sum((y == 1) & predicted)); fp = int(np.sum((y == 0) & predicted))
    fn = int(np.sum((y == 1) & ~predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def fit_boundary_model_from_labels(feature_names: list[str], features: np.ndarray,
                                   labels: np.ndarray, l2: float = 1.5) -> BoundaryModel:
    """Fit a small deterministic logistic model without an external ML dependency."""
    y = np.asarray(labels, dtype=np.float64)
    mean = features.mean(axis=0); scale = features.std(axis=0); scale[scale < 1e-8] = 1.0
    x = (features - mean) / scale; design = np.column_stack([np.ones(len(x)), x])
    weights = np.zeros(design.shape[1], dtype=np.float64)
    positive_weight = max(1.0, float(np.sum(y == 0)) / max(1.0, float(np.sum(y == 1))))
    sample_weight = np.where(y == 1, positive_weight, 1.0)
    regularizer = np.eye(design.shape[1]) * l2; regularizer[0, 0] = 0.0
    for _ in range(60):
        logits = np.clip(design @ weights, -30, 30); probability = 1 / (1 + np.exp(-logits))
        variance = sample_weight * probability * (1 - probability) + 1e-6
        gradient = design.T @ (sample_weight * (probability - y)) + regularizer @ weights
        hessian = design.T @ (design * variance[:, None]) + regularizer
        step = np.linalg.solve(hessian, gradient)
        weights -= step
        if float(np.linalg.norm(step)) < 1e-7:
            break
    provisional = BoundaryModel(feature_names, mean, scale, weights, .5)
    probabilities = provisional.probabilities(features)
    candidates = sorted(set(np.round(probabilities, 6).tolist() + [.5]))
    threshold = max(candidates, key=lambda value: (_f1(y, probabilities >= value), value))
    provisional.threshold = float(threshold)
    return provisional


def fit_boundary_model(feature_names: list[str], features: np.ndarray,
                       boundary_orders: set[int], l2: float = 1.5) -> BoundaryModel:
    labels = np.asarray([float(order in boundary_orders) for order in range(2, len(features) + 2)])
    return fit_boundary_model_from_labels(feature_names, features, labels, l2)


def decode_spans(nodes: list[dict[str, Any]], embedding_rows: list[dict[str, Any]],
                 probabilities: np.ndarray, threshold: float, max_span_nodes: int = 140,
                 coherence_weight: float = .18) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Globally decode coherent spans while using learned boundary odds as start evidence."""
    vector_by_id = {row["node_id"]: row["vector"] for row in embedding_rows}
    matrix = _normalise_rows(np.asarray([vector_by_id[node["node_id"]] for node in nodes], dtype=np.float64))
    prefix = np.vstack([np.zeros((1, matrix.shape[1])), np.cumsum(matrix, axis=0)])
    n = len(nodes); dp = np.full(n + 1, np.inf); previous = np.full(n + 1, -1, dtype=int); dp[0] = 0.0
    threshold_logit = math.log(max(threshold, 1e-6) / max(1 - threshold, 1e-6))
    logits = np.log(np.maximum(probabilities, 1e-8) / np.maximum(1 - probabilities, 1e-8))
    for end in range(1, n + 1):
        for start in range(max(0, end - max_span_nodes), end):
            length = end - start; total = prefix[end] - prefix[start]
            dispersion = max(0.0, length - float(total @ total) / length) / max(1, length)
            if start == 0:
                boundary_cost = 0.0
            else:
                boundary_cost = threshold_logit - logits[start - 1]
            cost = dp[start] + boundary_cost + coherence_weight * dispersion
            if cost < dp[end]:
                dp[end], previous[end] = cost, start
    cuts = []; end = n
    while end > 0:
        start = int(previous[end])
        if start > 0:
            cuts.append(start + 1)
        end = start
    cut_set = set(cuts); assignments = []; segment = 1
    for node in nodes:
        if node["document_order"] in cut_set:
            segment += 1
        assignments.append({"node_id": node["node_id"], "segment_id": f"SEGMENT_{segment:04d}",
                            "content_item_id": f"ITEM_{segment:04d}"})
    boundary_rows = []
    for order, probability in enumerate(probabilities, 2):
        boundary_rows.append({"start_document_order": order, "probability": round(float(probability), 6),
                              "accepted": order in cut_set})
    return assignments, boundary_rows


def reference_rows(doc_id: str, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if doc_id in {"CERNCourier2022NovDec-digitaledition", "CERNCourier2026MayJun-digitaledition"}:
        from .magazine_ground_truth import materialize
        return materialize(doc_id, nodes)
    if doc_id == "CERNCourier2025JanFeb-digitaledition":
        from .segmentation_ground_truth import materialize
        return materialize(nodes)
    raise ValueError(f"No magazine boundary reference registered for {doc_id}")


def run_document(doc_id: str, nodes: list[dict[str, Any]], embeddings: list[dict[str, Any]],
                 diagnostics: list[dict[str, Any]], titles: list[dict[str, Any]], model: BoundaryModel,
                 output: Path) -> dict[str, Any]:
    nodes = sorted(nodes, key=lambda row: row["document_order"])
    roles = infer_roles(nodes, titles); zones = build_boundary_zones(nodes, roles, titles)
    feature_names, features, feature_metadata = extract_features(nodes, embeddings, diagnostics, titles, roles)
    if feature_names != model.feature_names:
        raise ValueError("Prediction feature schema differs from the fitted model")
    probabilities = model.probabilities(features)
    assignments, boundaries = decode_spans(nodes, embeddings, probabilities, model.threshold)
    order_by_id = {node["node_id"]: node["document_order"] for node in nodes}
    scored = [{**row, "document_order": order_by_id[row["node_id"]]} for row in assignments]
    reference = reference_rows(doc_id, nodes)
    report = {"doc_id": doc_id, "method": "structural-role-zone-semi-markov-v1",
              "training_ground_truth_used_for_this_document": False,
              "nodes": len(nodes), "roles": {role: sum(row["role"] == role for row in roles) for role in ROLES},
              "boundary_zones": len(zones), "segments": len({row["content_item_id"] for row in assignments}),
              "threshold": model.threshold, "feature_metadata": feature_metadata,
              "exact": evaluate(reference, scored, 0), "tolerance_1": evaluate(reference, scored, 1),
              "tolerance_2": evaluate(reference, scored, 2)}
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "node_roles.jsonl", roles); write_jsonl(output / "boundary_zones.jsonl", zones)
    write_jsonl(output / "boundary_probabilities.jsonl", boundaries)
    write_jsonl(output / "assignments.jsonl", assignments); write_json(output / "evaluation.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Structural-role boundary-zone span segmentation experiment")
    parser.add_argument("--train-doc-id", required=True); parser.add_argument("--train-nodes", required=True)
    parser.add_argument("--train-embeddings", required=True); parser.add_argument("--train-diagnostics", required=True)
    parser.add_argument("--train-title-audit", required=True); parser.add_argument("--doc-id", required=True)
    parser.add_argument("--nodes", required=True); parser.add_argument("--embeddings", required=True)
    parser.add_argument("--diagnostics", required=True); parser.add_argument("--title-audit", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    train_nodes = sorted(read_jsonl(args.train_nodes), key=lambda row: row["document_order"])
    train_titles = read_jsonl(args.train_title_audit)
    train_roles = infer_roles(train_nodes, train_titles)
    feature_names, train_features, _ = extract_features(
        train_nodes, read_jsonl(args.train_embeddings), read_jsonl(args.train_diagnostics),
        train_titles, train_roles)
    train_reference = reference_rows(args.train_doc_id, train_nodes)
    train_boundaries = {row["start_document_order"] for row in train_reference[1:]}
    model = fit_boundary_model(feature_names, train_features, train_boundaries)

    output = Path(args.output_dir)
    report = run_document(args.doc_id, read_jsonl(args.nodes), read_jsonl(args.embeddings),
                          read_jsonl(args.diagnostics), read_jsonl(args.title_audit), model, output)
    report["training_doc_id"] = args.train_doc_id
    report["training_ground_truth_used_for_this_document"] = args.doc_id == args.train_doc_id
    write_json(output / "model.json", model.as_json()); write_json(output / "evaluation.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
