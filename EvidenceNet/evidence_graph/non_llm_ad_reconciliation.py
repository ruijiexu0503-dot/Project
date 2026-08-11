from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


COMMERCIAL_TEXT = re.compile(
    r"(?:\b(?:advertisement|register now|registration open|contact|sales|product|products|"
    r"power suppl(?:y|ies)|vacuum|generator|solutions|available|applications)\b|"
    r"www\.|https?://|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)", re.I)


def _text(node: dict[str, Any]) -> str:
    return " ".join((node.get("plain_text") or node.get("original_markdown") or "").split())


def _page(node: dict[str, Any]) -> str:
    return (node.get("page_ids") or ["NO_PAGE"])[0]


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)


def _layout_page_features(path: Path) -> list[float]:
    if not path.exists():
        return [0.0] * 10
    source = json.loads(path.read_text(encoding="utf-8"))
    width = float(source.get("page_width") or 1); height = float(source.get("page_height") or 1)
    area = max(1.0, width * height); counts = defaultdict(int); areas = defaultdict(float)
    for region in source.get("layout_regions") or []:
        label = str(region.get("label") or ""); counts[label] += 1
        bbox = region.get("bbox") or [0, 0, 0, 0]
        if len(bbox) == 4:
            areas[label] += max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1])) / area
    return [math.log1p(counts["text"]), math.log1p(counts["image"]), counts["header"], counts["footer"],
            counts["doc_title"], counts["paragraph_title"], counts["figure_title"],
            min(1.0, areas["image"]), min(1.0, areas["text"]), min(1.0, areas["footer_image"])]


def ad_features(nodes: list[dict[str, Any]], embedding_rows: list[dict[str, Any]],
                aligned_dir: str | Path) -> tuple[np.ndarray, list[str]]:
    """Dense, non-generative features for commercial-vs-editorial node classification."""
    nodes = sorted(nodes, key=lambda row: row["document_order"])
    vector_by_id = {row["node_id"]: row["vector"] for row in embedding_rows}
    embeddings = _normalise_rows(np.asarray([vector_by_id[node["node_id"]] for node in nodes], dtype=np.float32))
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        by_page[_page(node)].append(node)
    page_features = {}
    aligned = Path(aligned_dir)
    for page, members in by_page.items():
        lengths = [len(_text(node)) for node in members]
        page_text = " ".join(_text(node) for node in members)
        lexical = [math.log1p(len(members)), math.log1p(len(page_text)),
                   math.log1p(sum(lengths) / max(1, len(lengths))),
                   sum(length <= 80 for length in lengths) / max(1, len(lengths)),
                   min(1.0, len(COMMERCIAL_TEXT.findall(page_text)) / max(1, len(members)))]
        page_features[page] = lexical + _layout_page_features(aligned / f"{page}.json")
    rows = []
    for node in nodes:
        text = _text(node); words = text.split(); letters = [char for char in text if char.isalpha()]
        surface = [math.log1p(len(text)), math.log1p(len(words)), float(len(words) <= 12),
                   float(len(words) <= 4), float(text.isupper()),
                   sum(char.isupper() for char in letters) / max(1, len(letters)),
                   min(1.0, len(COMMERCIAL_TEXT.findall(text)) / 3)]
        rows.append(np.concatenate([embeddings[len(rows)], np.asarray(surface + page_features[_page(node)], dtype=np.float32)]))
    names = [f"embedding_{index}" for index in range(embeddings.shape[1])]
    names += ["node_length", "node_words", "node_short", "node_very_short", "node_upper",
              "node_upper_ratio", "node_commercial_terms", "page_nodes", "page_chars", "page_mean_chars",
              "page_short_ratio", "page_commercial_terms", "layout_text", "layout_image", "layout_header",
              "layout_footer", "layout_doc_title", "layout_paragraph_title", "layout_figure_title",
              "layout_image_area", "layout_text_area", "layout_footer_image_area"]
    return np.asarray(rows, dtype=np.float32), names


@dataclass
class AdModel:
    feature_names: list[str]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    intercept: float
    bias: float = 1.0
    transition_penalty: float = 1.0

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        values = (features - self.mean) / self.scale
        logits = np.clip(values @ self.weights + self.intercept, -30, 30)
        return 1 / (1 + np.exp(-logits))


def fit_ad_model(feature_names: list[str], feature_sets: list[np.ndarray],
                 label_sets: list[np.ndarray], epochs: int = 260,
                 balance_classes: bool = True) -> AdModel:
    """Fit a CPU linear classifier. Torch is used only as an optimiser, not as an LM."""
    import torch
    torch.manual_seed(17); torch.set_num_threads(min(8, max(1, torch.get_num_threads())))
    features = np.vstack(feature_sets).astype(np.float32); labels = np.concatenate(label_sets).astype(np.float32)
    mean = features.mean(axis=0); scale = features.std(axis=0); scale[scale < 1e-5] = 1.0
    values = torch.from_numpy((features - mean) / scale); targets = torch.from_numpy(labels[:, None])
    layer = torch.nn.Linear(features.shape[1], 1)
    optimiser = torch.optim.AdamW(layer.parameters(), lr=.02, weight_decay=.015)
    positive_weight = torch.tensor((len(labels) - labels.sum()) / max(1.0, labels.sum()))
    for _ in range(epochs):
        optimiser.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(
            layer(values), targets, pos_weight=positive_weight if balance_classes else None)
        loss.backward(); optimiser.step()
    weights = layer.weight.detach().cpu().numpy()[0]
    intercept = float(layer.bias.detach().cpu().numpy()[0])
    return AdModel(feature_names, mean, scale, weights, intercept)


def aggregate_page_features(nodes: list[dict[str, Any]], node_features: np.ndarray,
                            feature_names: list[str]) -> tuple[np.ndarray, list[str], list[dict[str, Any]]]:
    """Aggregate node evidence into conservative whole-page classification rows."""
    indices: dict[str, list[int]] = defaultdict(list)
    for index, node in enumerate(nodes):
        indices[_page(node)].append(index)
    rows = []; metadata = []
    for page, members in indices.items():
        values = node_features[members]
        rows.append(np.concatenate([values.mean(axis=0), values.std(axis=0)]))
        metadata.append({"page": page, "node_indices": members,
                         "start_document_order": nodes[members[0]]["document_order"],
                         "end_document_order": nodes[members[-1]]["document_order"]})
    names = [f"mean_{name}" for name in feature_names] + [f"std_{name}" for name in feature_names]
    return np.asarray(rows, dtype=np.float32), names, metadata


def select_high_precision_threshold(model: AdModel, feature_sets: list[np.ndarray],
                                    label_sets: list[np.ndarray], minimum_precision: float = .9) -> float:
    probabilities = np.concatenate([model.probabilities(features) for features in feature_sets])
    labels = np.concatenate(label_sets).astype(bool); best = (-1.0, -1.0, .99)
    for threshold in np.linspace(.10, .99, 90):
        predicted = probabilities >= threshold; true_positive = int(np.sum(predicted & labels))
        precision = true_positive / max(1, int(np.sum(predicted)))
        recall = true_positive / max(1, int(np.sum(labels)))
        candidate = (recall if precision >= minimum_precision else -1.0, precision, float(threshold))
        if candidate > best:
            best = candidate
    return best[-1]


def page_labels_to_nodes(page_predictions: np.ndarray, page_metadata: list[dict[str, Any]],
                         node_count: int) -> np.ndarray:
    labels = np.zeros(node_count, dtype=bool)
    for predicted, page in zip(page_predictions, page_metadata):
        if predicted:
            labels[page["node_indices"]] = True
    return labels


def filter_full_page_ad_predictions(nodes: list[dict[str, Any]], page_predictions: np.ndarray,
                                    page_metadata: list[dict[str, Any]],
                                    maximum_long_prose_nodes: int = 2) -> np.ndarray:
    """Keep only pages safe to rewrite as whole-page adverts.

    A singleton is commonly a cover line, figure caption, or OCR residue, while
    several long text blocks are strong evidence that editorial prose occupies at
    least part of the page. Rejected pages retain the baseline segmentation.
    """
    filtered = np.asarray(page_predictions, dtype=bool).copy()
    for index, page in enumerate(page_metadata):
        if not filtered[index]:
            continue
        members = page["node_indices"]
        match = re.search(r"(\d+)$", str(page.get("page") or ""))
        page_number = int(match.group(1)) if match else None
        long_prose = sum(len(_text(nodes[member])) > 240 for member in members)
        if page_number is not None and page_number <= 2:
            filtered[index] = False
        elif len(members) < 2:
            filtered[index] = False
        elif long_prose > maximum_long_prose_nodes:
            filtered[index] = False
    return filtered


def smooth_ad_labels(probabilities: np.ndarray, pages: list[str], bias: float,
                     transition_penalty: float) -> np.ndarray:
    """Two-state Viterbi smoothing, with transitions easier at page boundaries."""
    logits = np.log(np.maximum(probabilities, 1e-7) / np.maximum(1 - probabilities, 1e-7)) - bias
    count = len(logits); scores = np.zeros((count, 2)); previous = np.zeros((count, 2), dtype=np.int8)
    scores[0] = [0.0, logits[0]]
    for index in range(1, count):
        penalty = transition_penalty * (.35 if pages[index] != pages[index - 1] else 1.0)
        for state in (0, 1):
            options = scores[index - 1] - penalty * np.asarray([0 if old == state else 1 for old in (0, 1)])
            previous[index, state] = int(np.argmax(options))
            scores[index, state] = options[previous[index, state]] + (logits[index] if state else 0.0)
    labels = np.zeros(count, dtype=bool); labels[-1] = bool(np.argmax(scores[-1]))
    for index in range(count - 1, 0, -1):
        labels[index - 1] = bool(previous[index, int(labels[index])])
    return labels


def promote_ad_pages(nodes: list[dict[str, Any]], labels: np.ndarray, probabilities: np.ndarray,
                     minimum_fraction: float = .4, minimum_mean_probability: float = .85) -> np.ndarray:
    """Fill high-confidence full-page ads while excluding covers and contents pages."""
    promoted = labels.copy(); indices: dict[str, list[int]] = defaultdict(list)
    for index, node in enumerate(nodes):
        indices[_page(node)].append(index)
    for page, members in indices.items():
        number_match = re.search(r"(\d+)$", page)
        page_number = int(number_match.group(1)) if number_match else 0
        page_text = " ".join(_text(nodes[index]).lower() for index in members)
        if page_number <= 2 or "in this issue" in page_text:
            continue
        if (float(np.mean(labels[members])) >= minimum_fraction
                and float(np.mean(probabilities[members])) >= minimum_mean_probability):
            promoted[members] = True
    return promoted


def filter_ad_runs(labels: np.ndarray, probabilities: np.ndarray, minimum_nodes: int = 2,
                   minimum_mean_probability: float = .65) -> np.ndarray:
    """Discard isolated low-confidence commercial fragments."""
    filtered = labels.copy(); start = None
    for index, is_ad in enumerate(np.r_[labels, False]):
        if is_ad and start is None:
            start = index
        elif not is_ad and start is not None:
            if (index - start < minimum_nodes
                    or float(np.mean(probabilities[start:index])) < minimum_mean_probability):
                filtered[start:index] = False
            start = None
    return filtered


def _assignment_boundaries(nodes: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> set[int]:
    order_by_id = {node["node_id"]: node["document_order"] for node in nodes}
    ordered = sorted(assignments, key=lambda row: order_by_id[row["node_id"]])
    boundaries = set(); prior = None
    for row in ordered:
        item = row.get("content_item_id") or row.get("segment_id")
        order = order_by_id[row["node_id"]]
        if prior is not None and item != prior:
            boundaries.add(order)
        prior = item
    return boundaries


def reconcile_ad_spans(nodes: list[dict[str, Any]], baseline_assignments: list[dict[str, Any]],
                       ad_labels: np.ndarray, probabilities: np.ndarray, snap_radius: int = 2,
                       unsnapped_min_probability: float = .9) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Protect predicted ad spans while preserving strong page-level splits between adjacent ads."""
    nodes = sorted(nodes, key=lambda row: row["document_order"]); pages = [_page(node) for node in nodes]
    boundaries = _assignment_boundaries(nodes, baseline_assignments)
    spans = []; start = None
    for index, is_ad in enumerate(np.r_[ad_labels, False]):
        if is_ad and start is None:
            start = index
        elif not is_ad and start is not None:
            spans.append((start, index - 1)); start = None
    protected = set(); removed = set(); span_rows = []
    def snap(order: int) -> int | None:
        choices = [(abs(order - value), value) for value in boundaries if abs(order - value) <= snap_radius]
        return min(choices)[1] if choices else None

    for start, end in spans:
        start_order, end_order = start + 1, end + 1
        mean_probability = float(np.mean(probabilities[start:end + 1]))
        # A detected full-page advert has an exact structural edge. Do not move
        # that edge to a merely nearby baseline valley (the old behaviour could
        # turn a correct page boundary into an off-by-one error).
        at_page_start = start == 0 or pages[start] != pages[start - 1]
        snapped_start = start_order if at_page_start else snap(start_order)
        if snapped_start is None and (start == 0 or pages[start] != pages[start - 1]
                                      or mean_probability >= unsnapped_min_probability):
            snapped_start = start_order
        if snapped_start is not None and snapped_start > 1:
            protected.add(snapped_start)
        snapped_end = None
        if end_order < len(nodes):
            at_page_end = pages[end] != pages[end + 1]
            snapped_end = end_order + 1 if at_page_end else snap(end_order + 1)
            if snapped_end is None and (pages[end] != pages[end + 1]
                                        or mean_probability >= unsnapped_min_probability):
                snapped_end = end_order + 1
            if snapped_end is not None:
                protected.add(snapped_end)
        preserved_inside = []
        for order in range(start_order + 1, end_order + 1):
            if order not in boundaries:
                continue
            # Adjacent full-page ads should remain separate items. Same-page
            # internal cuts are almost always OCR fragments of one advert.
            if order in {snapped_start, snapped_end} or pages[order - 1] != pages[order - 2]:
                preserved_inside.append(order); protected.add(order)
            else:
                removed.add(order)
        span_rows.append({"start_document_order": start_order, "end_document_order": end_order,
                          "pages": list(dict.fromkeys(pages[start:end + 1])),
                          "node_count": end - start + 1,
                          "mean_probability": round(mean_probability, 6),
                          "snapped_start_order": snapped_start, "snapped_end_order": snapped_end,
                          "preserved_internal_page_boundaries": preserved_inside})
    final_boundaries = (boundaries - removed) | {order for order in protected if order > 1}
    assignments = []; item = 1
    for index, node in enumerate(nodes):
        if node["document_order"] in final_boundaries:
            item += 1
        assignments.append({"node_id": node["node_id"], "segment_id": f"SEGMENT_{item:04d}",
                            "content_item_id": f"ITEM_{item:04d}",
                            "content_kind": "advertisement" if ad_labels[index] else "editorial"})
    return assignments, span_rows
