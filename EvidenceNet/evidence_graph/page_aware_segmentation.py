from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from .boundary_experiments import ANAPHOR, quantile, title_anchors
from .io_utils import read_jsonl, write_json, write_jsonl

RUNNING = re.compile(r"^(?:cern\s*courier|volume\s+\d+|january/february|further reading|references?|"
                     r"interview by |(?:[A-Z][A-Za-z'’-]+\s+){1,5}(?:CERN|University|"
                     r"Laboratory|Institute|PSI|RAL)\.?$)", re.I)
CONTINUATION = re.compile(r"^\s*(?:these|this|those|such|they|it|following|required|using|of\b|and\b|but\b|"
                          r"however\b|while\b|whereas\b|in addition\b|furthermore\b)", re.I)
SECTION_ONLY = re.compile(r"^(?:news analysis|news digest|energy frontiers|field notes|opinion|interview|"
                          r"reviews|departments|background|appointments(?: and awards)?|people|careers)$", re.I)
PLACEHOLDER = re.compile(r"^\s*(?:null|none|n/?a|undefined|\[?blank(?: page)?\]?)?\s*$", re.I)


def _compact_category(text: str) -> bool:
    """Recognise retained category tags without treating prose/sign-offs as titles."""
    value = " ".join(text.split()).strip(" :–—-")
    words = value.split()
    return bool(value and len(value) <= 60 and len(words) <= 5
                and not value.endswith((".", ",", ";", "!", "?"))
                and (value.isupper() or SECTION_ONLY.fullmatch(value)))


def _normalise(vector):
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def _centroid(vectors):
    return _normalise(np.mean(vectors, axis=0))


def _page(node):
    pages = node.get("page_ids") or []
    return pages[0] if pages else "unknown"


def _similarity(a, b): return float(np.dot(a, b))


def _source_heading_hints(nodes, aligned_dir: str | None, direct_sims):
    if not aligned_dir:
        return {}, set()
    directory = Path(aligned_dir); hints = {}; department_pages = set()
    nodes_by_page = {}
    for node in nodes:
        page = _page(node); nodes_by_page.setdefault(page, []).append(node)
    for page, page_nodes in nodes_by_page.items():
        path = directory / f"{page}.json"
        if not path.exists():
            continue
        source = json.loads(path.read_text(encoding="utf-8")); blocks = source.get("aligned_blocks", [])
        headings = []; department_page = False
        for block in blocks:
            markdown = (block.get("markdown") or "").strip()
            match = re.match(r"^(#{1,3})\s+(.+)", markdown, re.S)
            if match:
                text = " ".join(match.group(2).split())
                department_page = department_page or bool(SECTION_ONLY.fullmatch(text))
                if not RUNNING.search(text) and not SECTION_ONLY.fullmatch(text):
                    headings.append((block.get("block_id", ""), len(match.group(1)), text))
        is_contents = any("in this issue" in (block.get("markdown") or "").lower() for block in blocks)
        lengths = sorted(len(node.get("plain_text", "")) for node in page_nodes)
        median_length = lengths[len(lengths)//2] if lengths else 0
        compact_department = department_page and len(headings) >= 2 and not is_contents
        if compact_department:
            department_pages.add(page)
        node_blocks = []
        for node in page_nodes:
            ids = [member.get("block_id", "") for member in node.get("source_members", [])]
            ranks = [int(value.rsplit("_", 1)[-1]) for value in ids if value.rsplit("_", 1)[-1].isdigit()]
            if ranks:
                node_blocks.append((min(ranks), node))
        for block_id, level, text in headings:
            suffix = block_id.rsplit("_", 1)[-1]
            if not suffix.isdigit():
                continue
            rank = int(suffix); following = [item for item in node_blocks if item[0] >= rank]
            if not following:
                continue
            following_rank, node = min(following, key=lambda item:item[0])
            # Parsers often retain a short category label immediately before a
            # dropped article title (for example ATLAS or ASTROWATCH). Treat
            # that label as the item start rather than splitting title/body.
            preceding = [(node_rank, candidate) for node_rank, candidate in node_blocks
                         if rank - 3 <= node_rank < rank
                         and _compact_category(candidate.get("plain_text", ""))]
            if preceding:
                node = min(preceding, key=lambda item:item[0])[1]
            index = next((i for i, candidate in enumerate(nodes) if candidate["node_id"] == node["node_id"]), 0)
            low_transition = index > 0 and direct_sims[index - 1] <= quantile(direct_sims, .15)
            strong = ((level == 1 and len(text) <= 140) or compact_department)
            current = hints.get(node["node_id"])
            if current is None or (strong and not current["strong"]):
                hints[node["node_id"]] = {"text": text, "level": level, "strong": strong,
                                           "compact_department": compact_department}
    return hints, department_pages


def segment(nodes, embedding_rows, aligned_dir: str | None = None):
    nodes = sorted(nodes, key=lambda node: node["document_order"])
    vector_by_id = {row["node_id"]: row["vector"] for row in embedding_rows}
    vectors = np.asarray([vector_by_id[node["node_id"]] for node in nodes], dtype=np.float32)
    vectors = np.asarray([_normalise(vector) for vector in vectors])
    pages = [_page(node) for node in nodes]
    node_sims = [_similarity(vectors[i], vectors[i + 1]) for i in range(len(nodes) - 1)]
    window_sims = []
    prominence = []
    for i in range(len(nodes) - 1):
        left = _centroid(vectors[max(0, i - 2):i + 1])
        right = _centroid(vectors[i + 1:min(len(nodes), i + 4)])
        window_sims.append(_similarity(left, right))
        nearby = node_sims[max(0, i - 3):i] + node_sims[i + 1:min(len(node_sims), i + 4)]
        prominence.append((sum(nearby) / len(nearby) - node_sims[i]) if nearby else 0.0)

    node_q10, node_q40 = quantile(node_sims, .10), quantile(node_sims, .40)
    win_q10, win_q40 = quantile(window_sims, .10), quantile(window_sims, .40)
    prom_q80, prom_q95 = quantile(prominence, .80), quantile(prominence, .95)
    titles = title_anchors(nodes)
    source_hints, department_pages = _source_heading_hints(nodes, aligned_dir, node_sims)

    def scaled_low(value, low, high):
        return max(0.0, min(1.0, (high - value) / max(.001, high - low)))

    def scaled_high(value, low, high):
        return max(0.0, min(1.0, (value - low) / max(.001, high - low)))

    diagnostics = []
    boundaries = set()
    for i in range(len(nodes) - 1):
        page_change = pages[i] != pages[i + 1]
        hint = source_hints.get(nodes[i + 1]["node_id"])
        right_text = nodes[i + 1].get("plain_text", "")
        raw_right = nodes[i + 1].get("original_markdown", "")
        lines = [line.strip(" #\t") for line in raw_right.splitlines() if line.strip(" #\t")]
        lead_title = (pages[i + 1] in department_pages and len(lines) >= 2 and len(lines[0]) <= 85
                      and len(" ".join(lines[1:])) >= 100
                      and not lines[0].endswith((".", ";", "?")) and not RUNNING.search(lines[0]))
        strong_source_title = bool(hint and hint["strong"])
        title_start = i in titles or strong_source_title or lead_title
        anaphoric = bool(ANAPHOR.search(right_text) or CONTINUATION.search(right_text))
        incomplete = bool(nodes[i].get("possible_continuation"))
        running = bool(RUNNING.search(right_text.strip()))
        placeholder = bool(PLACEHOLDER.fullmatch(right_text))
        score = (.32 * scaled_low(node_sims[i], node_q10, node_q40)
                 + .30 * scaled_low(window_sims[i], win_q10, win_q40)
                 + .20 * scaled_high(prominence[i], prom_q80, prom_q95)
                 + (.14 if page_change else 0.0) + (.32 if title_start else 0.0)
                 - (.28 if anaphoric else 0.0) - (.10 if incomplete and not title_start else 0.0)
                 - (.45 if running else 0.0))
        accepted = ((page_change and score >= .55)
                    or (strong_source_title and score >= .15)
                    or (lead_title and score >= .15)
                    or (title_start and score >= .62)
                    or (not page_change and not title_start and score >= .72
                        and prominence[i] >= prom_q95)) and not running and not placeholder
        if accepted:
            boundaries.add(i)
        diagnostics.append({"left_id": nodes[i]["node_id"], "right_id": nodes[i + 1]["node_id"],
                            "left_page": pages[i], "right_page": pages[i + 1],
                            "node_similarity": round(node_sims[i], 6),
                            "window_similarity": round(window_sims[i], 6),
                            "prominence": round(prominence[i], 6), "boundary_score": round(score, 6),
                            "page_change": page_change, "title_start": title_start,
                            "lead_title": lead_title,
                            "source_heading": hint, "running_metadata": running,
                            "placeholder": placeholder,
                            "anaphoric_start": anaphoric, "accepted": accepted,
                            "reasons": (["page_change"] if page_change else [])
                                       + (["title_start"] if title_start else [])
                                       + (["local_embedding_valley"] if prominence[i] >= prom_q80 else [])})

    # Generic whole-page A-X-A interruption: X is a normal segment, not an ad class.
    page_order = list(dict.fromkeys(pages))
    indices_by_page = {page: [i for i, value in enumerate(pages) if value == page] for page in page_order}
    page_vectors = {page: _centroid(vectors[indices_by_page[page]]) for page in page_order}
    adjacent_page_sims = [_similarity(page_vectors[a], page_vectors[b]) for a, b in zip(page_order, page_order[1:])]
    page_low = quantile(adjacent_page_sims, .30)
    page_reconnect = max(.45, quantile(adjacent_page_sims, .70))
    standalone_pages = []
    for p in range(1, len(page_order) - 1):
        before, current, after = page_order[p - 1:p + 2]
        left = _similarity(page_vectors[before], page_vectors[current])
        right = _similarity(page_vectors[current], page_vectors[after])
        across = _similarity(page_vectors[before], page_vectors[after])
        if left <= page_low and right <= page_low and across >= page_reconnect:
            before_cut = max(indices_by_page[before]); current_cut = max(indices_by_page[current])
            boundaries.update((before_cut, current_cut))
            standalone_pages.append({"page": current, "previous_page": before, "next_page": after,
                                     "previous_similarity": round(left, 6),
                                     "next_similarity": round(right, 6),
                                     "across_similarity": round(across, 6)})

    segments = []
    start = 0
    for number, cut in enumerate(sorted(boundaries) + [len(nodes) - 1], 1):
        ids = [node["node_id"] for node in nodes[start:cut + 1]]
        segment_pages = list(dict.fromkeys(pages[start:cut + 1]))
        segments.append({"segment_id": f"SEGMENT_{number:04d}", "node_ids": ids,
                         "pages": segment_pages, "start_order": nodes[start]["document_order"],
                         "end_order": nodes[cut]["document_order"]})
        start = cut + 1

    # Reconnect only the high-confidence A-X-A pattern where X occupies one page.
    segment_vectors = [_centroid(np.asarray([vector_by_id[node_id] for node_id in segment["node_ids"]],
                                            dtype=np.float32)) for segment in segments]
    logical_ids = [f"ITEM_{i + 1:04d}" for i in range(len(segments))]
    resumptions = []
    for i in range(1, len(segments) - 1):
        if len(segments[i]["pages"]) != 1:
            continue
        left = _similarity(segment_vectors[i - 1], segment_vectors[i])
        right = _similarity(segment_vectors[i], segment_vectors[i + 1])
        across = _similarity(segment_vectors[i - 1], segment_vectors[i + 1])
        if left <= page_low and right <= page_low and across >= page_reconnect:
            logical_ids[i + 1] = logical_ids[i - 1]
            resumptions.append({"interrupted_item": logical_ids[i - 1],
                                "standalone_segment": segments[i]["segment_id"],
                                "resumed_segment": segments[i + 1]["segment_id"],
                                "across_similarity": round(across, 6)})
    assignments = []
    for segment, item_id in zip(segments, logical_ids):
        segment["content_item_id"] = item_id
        assignments.extend({"node_id": node_id, "segment_id": segment["segment_id"],
                            "content_item_id": item_id} for node_id in segment["node_ids"])
    return assignments, segments, diagnostics, standalone_pages, resumptions


def main():
    parser = argparse.ArgumentParser(description="Non-VLM page-aware content-item segmentation")
    parser.add_argument("--nodes", required=True); parser.add_argument("--embeddings", required=True)
    parser.add_argument("--output-dir", required=True); parser.add_argument("--label", required=True)
    parser.add_argument("--aligned-dir")
    args = parser.parse_args(); output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    assignments, segments, diagnostics, standalone, resumptions = segment(
        read_jsonl(args.nodes), read_jsonl(args.embeddings), args.aligned_dir)
    write_jsonl(output / "assignments.jsonl", assignments)
    write_jsonl(output / "segments.jsonl", segments)
    write_jsonl(output / "boundary_diagnostics.jsonl", diagnostics)
    report = {"label": args.label, "nodes": len(assignments), "segments": len(segments),
              "logical_items": len({row["content_item_id"] for row in assignments}),
              "boundaries": sum(row["accepted"] for row in diagnostics),
              "whole_page_interruptions": standalone, "resumptions": resumptions,
              "method": "page-aware-change-point-v1", "uses_vlm": False}
    write_json(output / "summary.json", report); print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
