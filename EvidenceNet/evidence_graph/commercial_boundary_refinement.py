from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from .non_llm_ad_reconciliation import COMMERCIAL_TEXT


END_SIGNAL = re.compile(
    r"(?:www\.|https?://|\bemail\b|\bcontact\b|\bsales@|\btel\.?\b|\bphone\b|"
    r"volume\s+\d+|cern\s*courier)", re.I)
COMPANY_HEADING = re.compile(
    r"(?:\b(?:inc\.?|ltd\.?|gmbh|b\.v\.|corporation|company|technologies|systems|"
    r"products?|solutions?|instruments?|power supplies|modules?|conference|careers?|magnetics)\b|"
    r"www\.|\.com\b)", re.I)
EXPLICIT_AD_START = re.compile(
    r"^(?:what if you could be the next to work at|career opportunities for|"
    r"mass spectrometers for|.*international conference on high energy physics)", re.I)


def _text(node: dict[str, Any]) -> str:
    return " ".join((node.get("plain_text") or node.get("original_markdown") or "").split())


def _page(node: dict[str, Any]) -> str:
    return (node.get("page_ids") or ["NO_PAGE"])[0]


def _block_number(value: Any) -> int | None:
    try:
        return int(str(value).rsplit("_", 1)[1])
    except (TypeError, ValueError, IndexError):
        return None


def assignment_boundaries(nodes: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> set[int]:
    order = {node["node_id"]: node["document_order"] for node in nodes}
    rows = sorted(assignments, key=lambda row: order[row["node_id"]])
    boundaries: set[int] = set(); prior = None
    for row in rows:
        item = row.get("content_item_id") or row.get("segment_id")
        node_order = order[row["node_id"]]
        if prior is not None and item != prior:
            boundaries.add(node_order)
        prior = item
    return boundaries


def assignments_from_boundaries(nodes: list[dict[str, Any]], boundaries: set[int]) -> list[dict[str, Any]]:
    rows = []; item = 1
    for node in sorted(nodes, key=lambda row: row["document_order"]):
        if node["document_order"] in boundaries:
            item += 1
        item_id = f"NON_LLM_COMMERCIAL_{item:04d}"
        rows.append({"node_id": node["node_id"], "segment_id": item_id,
                     "content_item_id": item_id})
    return rows


def _gap_metadata(nodes: list[dict[str, Any]], aligned_dir: str | Path) -> list[dict[str, Any]]:
    aligned = Path(aligned_dir); cache: dict[str, dict[str, Any]] = {}
    rows = []
    for index in range(1, len(nodes)):
        left, right = nodes[index - 1], nodes[index]
        metadata = {"gap_blocks": 0, "gap_headings": 0, "heading_text": ""}
        page = _page(right)
        if page not in cache:
            path = aligned / f"{page}.json"
            cache[page] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        left_id = _block_number((left.get("source_members") or [{}])[-1].get("block_id"))
        right_id = _block_number((right.get("source_members") or [{}])[0].get("block_id"))
        if right_id is not None:
            between = []
            for block in cache[page].get("aligned_blocks") or []:
                block_id = _block_number(block.get("block_id"))
                if block_id is None:
                    continue
                if (_page(left) == page and left_id is not None and left_id < block_id < right_id):
                    between.append(block)
                elif _page(left) != page and block_id < right_id:
                    between.append(block)
            headings = [str(block.get("text") or "").lstrip("# ").strip()
                        for block in between if block.get("block_type") == "heading"]
            metadata = {"gap_blocks": len(between), "gap_headings": len(headings),
                        "heading_text": " ".join(headings)}
        rows.append(metadata)
    return rows


def extract_commercial_boundary_features(
        nodes: list[dict[str, Any]], embedding_rows: list[dict[str, Any]],
        node_ad_probabilities: np.ndarray, baseline_assignments: list[dict[str, Any]],
        aligned_dir: str | Path) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
    """Build inspectable adjacent-node features, including omitted OCR headings."""
    nodes = sorted(nodes, key=lambda row: row["document_order"])
    vectors = {row["node_id"]: np.asarray(row["vector"], dtype=np.float64) for row in embedding_rows}
    matrix = np.asarray([vectors[node["node_id"]] for node in nodes])
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
    baseline = assignment_boundaries(nodes, baseline_assignments)
    gaps = _gap_metadata(nodes, aligned_dir)
    page_members: dict[str, list[int]] = {}
    for index, node in enumerate(nodes):
        page_members.setdefault(_page(node), []).append(index)
    position = {}
    for members in page_members.values():
        for offset, index in enumerate(members):
            position[index] = offset / max(1, len(members) - 1)
    names = [
        "similarity", "window_similarity", "page_change", "baseline_boundary",
        "left_ad_probability", "right_ad_probability", "minimum_ad_probability",
        "maximum_ad_probability", "left_ad_window", "right_ad_window", "ad_reset",
        "gap_blocks", "gap_headings", "gap_commercial_heading", "gap_heading_upper",
        "left_end_signal", "right_commercial_signal", "left_commercial_signal",
        "left_length", "right_length", "left_short", "right_short",
        "left_upper", "right_upper", "right_page_position", "left_page_position",
        "right_null", "left_running_header", "right_running_header",
    ]
    feature_rows = []; metadata = []
    for index in range(1, len(nodes)):
        left, right = nodes[index - 1], nodes[index]
        left_text, right_text = _text(left), _text(right)
        heading = gaps[index - 1]["heading_text"]
        heading_letters = [char for char in heading if char.isalpha()]
        left_letters = [char for char in left_text if char.isalpha()]
        right_letters = [char for char in right_text if char.isalpha()]
        left_window = float(np.mean(node_ad_probabilities[max(0, index - 3):index]))
        right_window = float(np.mean(node_ad_probabilities[index:min(len(nodes), index + 3)]))
        left_centroid = matrix[max(0, index - 3):index].mean(axis=0)
        right_centroid = matrix[index:min(len(nodes), index + 3)].mean(axis=0)
        left_centroid /= max(np.linalg.norm(left_centroid), 1e-8)
        right_centroid /= max(np.linalg.norm(right_centroid), 1e-8)
        values = [
            float(matrix[index - 1] @ matrix[index]), float(left_centroid @ right_centroid),
            float(_page(left) != _page(right)), float(right["document_order"] in baseline),
            float(node_ad_probabilities[index - 1]), float(node_ad_probabilities[index]),
            float(min(node_ad_probabilities[index - 1], node_ad_probabilities[index])),
            float(max(node_ad_probabilities[index - 1], node_ad_probabilities[index])),
            left_window, right_window, right_window - left_window,
            math.log1p(gaps[index - 1]["gap_blocks"]), float(gaps[index - 1]["gap_headings"] > 0),
            float(bool(COMPANY_HEADING.search(heading))),
            sum(char.isupper() for char in heading_letters) / max(1, len(heading_letters)),
            float(bool(END_SIGNAL.search(left_text))), float(bool(COMMERCIAL_TEXT.search(right_text))),
            float(bool(COMMERCIAL_TEXT.search(left_text))), math.log1p(len(left_text)),
            math.log1p(len(right_text)), float(len(left_text) <= 100), float(len(right_text) <= 100),
            sum(char.isupper() for char in left_letters) / max(1, len(left_letters)),
            sum(char.isupper() for char in right_letters) / max(1, len(right_letters)),
            position[index], position[index - 1], float(right_text.lower() in {"null", ""}),
            float(bool(re.search(r"(?:cern\s*courier|volume\s+\d+)", left_text, re.I))),
            float(bool(re.search(r"(?:cern\s*courier|volume\s+\d+)", right_text, re.I))),
        ]
        feature_rows.append(values)
        metadata.append({"start_document_order": right["document_order"], "page": _page(right),
                         **gaps[index - 1]})
    return names, np.asarray(feature_rows, dtype=np.float64), metadata


def refine_commercial_boundaries(
        nodes: list[dict[str, Any]], baseline_assignments: list[dict[str, Any]],
        node_ad_probabilities: np.ndarray, boundary_probabilities: np.ndarray,
        boundary_metadata: list[dict[str, Any]], add_threshold: float = .82,
        remove_threshold: float = .18, ad_threshold: float = .58) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Add commercial edges and remove only high-confidence within-ad fragments."""
    nodes = sorted(nodes, key=lambda row: row["document_order"])
    boundaries = assignment_boundaries(nodes, baseline_assignments)
    changes = []
    contents_pages = {
        _page(node) for node in nodes
        if "in this issue" in _text(node).lower()
    }
    for index, (probability, metadata) in enumerate(zip(boundary_probabilities, boundary_metadata), start=1):
        order = metadata["start_document_order"]
        left_ad, right_ad = node_ad_probabilities[index - 1], node_ad_probabilities[index]
        heading = metadata["heading_text"]
        heading_letters = [char for char in heading if char.isalpha()]
        heading_upper = sum(char.isupper() for char in heading_letters) / max(1, len(heading_letters))
        left_text, right_text = _text(nodes[index - 1]), _text(nodes[index])
        left_end = bool(END_SIGNAL.search(left_text))
        commercial_heading = bool(metadata["gap_headings"] and COMPANY_HEADING.search(heading))
        heading_words = heading.split()
        branded_heading = commercial_heading and (
            left_end or left_ad <= .35
            or (heading_upper >= .8 and len(heading_words) <= 8 and probability >= .2)
            or bool(re.search(r"physicsworld\s+careers", heading, re.I)))
        strong_heading = right_ad >= .95 and branded_heading and _page(nodes[index]) not in contents_pages
        explicit_start = right_ad >= .9 and bool(EXPLICIT_AD_START.search(right_text))
        domain_match = re.search(r"(?:www\.|https?://)([a-z0-9-]{4,})", left_text, re.I)
        domain = domain_match.group(1).lower() if domain_match else ""
        same_brand = any(len(word) >= 4 and word.lower() in domain
                         for word in re.findall(r"[A-Za-z]{4,}", right_text))
        url_brand_reset = (right_ad >= .95 and probability < .2 and len(left_text) <= 60
                           and bool(domain) and not same_brand
                           and not END_SIGNAL.search(right_text) and len(right_text) <= 80)
        page_brand_start = (_page(nodes[index - 1]) != _page(nodes[index])
                            and min(left_ad, right_ad) >= .9 and 2 <= len(right_text.split()) <= 5
                            and right_text.lower() not in {"null", "cerncourier"})
        should_add = strong_heading or explicit_start or url_brand_reset or page_brand_start
        if order not in boundaries and should_add:
            boundaries.add(order)
            changes.append({"order": order, "action": "add", "probability": round(float(probability), 6),
                            "reason": ("commercial_heading" if strong_heading else "explicit_ad_start"
                                       if explicit_start else "url_brand_reset" if url_brand_reset
                                       else "page_brand_start")})
            continue
        same_page = _page(nodes[index - 1]) == _page(nodes[index])
        blank_continuation = right_text.lower() in {"", "null"} and left_ad >= ad_threshold
        same_commercial_run = (min(left_ad, right_ad) >= .9 and same_page and not strong_heading
                               and (probability < .93 or left_text.lower() == "advertisement"))
        if order in boundaries and (same_commercial_run or blank_continuation):
            boundaries.remove(order)
            changes.append({"order": order, "action": "remove", "probability": round(float(probability), 6),
                            "reason": "blank_continuation" if blank_continuation else "within_ad_fragment"})
    return assignments_from_boundaries(nodes, boundaries), changes
