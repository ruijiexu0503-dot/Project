#!/usr/bin/env python3
"""Shadow-only cross-page continuation ranking; explicit markers are optional."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


CONFIG = {
    "source_order_candidates": 5,
    "source_geometry_candidates": 5,
    "target_order_candidates": 5,
    "target_geometry_candidates": 5,
    "merge_threshold": 0.72,
    "uncertain_threshold": 0.56,
    "weights": {"syntax": 0.60, "geometry": 0.22, "order": 0.10, "role": 0.08},
}
TERMINAL_RE = re.compile(r"[.!?][\]\)}\"'\u2019\u201d]*\s*$")
OPEN_END_RE = re.compile(
    r"(?:[-\u2013\u2014]|\b(?:a|an|the|and|or|but|of|to|in|on|at|for|from|with|by|as|that|which|is|are|was|were|been|be))\s*$",
    re.IGNORECASE,
)
EXCLUDED_ROLES = {"heading", "title", "caption", "figure", "image", "table", "formula", "header", "footer"}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def bbox(block: dict[str, Any]) -> list[float] | None:
    value = block.get("deepseek_bbox") or block.get("bbox")
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return [float(v) for v in value]
    members = block.get("geometry_members") or []
    if len(members) == 1:
        value = members[0].get("pixel_bbox") or members[0].get("bbox")
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return [float(v) for v in value]
    return None


def role(block: dict[str, Any]) -> str:
    return str(block.get("block_type") or block.get("role") or block.get("matched_region_label") or "").lower()


def usable(block: dict[str, Any]) -> bool:
    return len(clean(block.get("text") or block.get("content") or "")) >= 12 and role(block) not in EXCLUDED_ROLES


def syntax_features(source_text: str, target_text: str) -> dict[str, Any]:
    left, right = clean(source_text), clean(target_text)
    source_terminal = bool(TERMINAL_RE.search(left))
    source_hyphen = bool(re.search(r"\w[-\u2010]\s*$", left))
    source_open = bool(OPEN_END_RE.search(left))
    target_lower = bool(re.match(r"^[a-z]", right))
    target_continuation_punct = bool(re.match(r"^[,.;:)\]}\u2013\u2014-]", right))
    if source_hyphen and target_lower:
        score, reason = 1.0, "hyphenated_word_crosses_page"
    elif source_open:
        score, reason = 0.94, "source_has_grammatically_open_ending"
    elif not source_terminal and (target_lower or target_continuation_punct):
        score, reason = 0.86, "nonterminal_source_and_continuation_like_target"
    elif not source_terminal:
        score, reason = 0.48, "nonterminal_source_but_target_not_continuation_like"
    elif target_lower:
        score, reason = 0.38, "complete_source_conflicts_with_lowercase_target"
    else:
        score, reason = 0.05, "closed_sentence_boundary"
    return {
        "source_terminal": source_terminal,
        "source_hyphen": source_hyphen,
        "source_open": source_open,
        "target_lower": target_lower,
        "target_continuation_punctuation": target_continuation_punct,
        "syntax_score": score,
        "syntax_reason": reason,
    }


def geometry_features(
    source: dict[str, Any], target: dict[str, Any], source_page: dict[str, Any], target_page: dict[str, Any]
) -> dict[str, Any]:
    sb, tb = bbox(source), bbox(target)
    if not sb or not tb:
        return {"geometry_available": False, "geometry_score": 0.5, "same_column": None}
    sw, sh = float(source_page.get("page_width") or 1), float(source_page.get("page_height") or 1)
    tw, th = float(target_page.get("page_width") or 1), float(target_page.get("page_height") or 1)
    source_bottom = min(1.0, sb[3] / sh)
    target_top = min(1.0, tb[1] / th)
    sx = (sb[0] + sb[2]) / (2 * sw)
    tx = (tb[0] + tb[2]) / (2 * tw)
    same_column = abs(sx - tx) <= 0.18
    page_edge_score = (source_bottom + (1.0 - target_top)) / 2.0
    score = min(1.0, 0.82 * page_edge_score + (0.18 if same_column else 0.0))
    return {
        "geometry_available": True,
        "source_bottom_norm": round(source_bottom, 5),
        "target_top_norm": round(target_top, 5),
        "source_center_x_norm": round(sx, 5),
        "target_center_x_norm": round(tx, 5),
        "same_column": same_column,
        "geometry_score": round(score, 5),
    }


def candidates(blocks: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    valid = [block for block in blocks if usable(block)]
    if side == "source":
        ordered = valid[-CONFIG["source_order_candidates"] :]
        grounded = sorted((b for b in valid if bbox(b)), key=lambda b: bbox(b)[3], reverse=True)[: CONFIG["source_geometry_candidates"]]
    else:
        ordered = valid[: CONFIG["target_order_candidates"]]
        grounded = sorted((b for b in valid if bbox(b)), key=lambda b: bbox(b)[1])[: CONFIG["target_geometry_candidates"]]
    result, seen = [], set()
    for block in ordered + grounded:
        key = str(block.get("block_id") or block.get("id"))
        if key not in seen:
            seen.add(key)
            result.append(block)
    return result


def marker_index(path: Path | None) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not path or not path.exists():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("status") == "RESOLVED":
            result[(row["logical_page"], str(row.get("source_block_id")), str(row.get("target_block_id")))] = row
    return result


def score_pair(
    source: dict[str, Any], target: dict[str, Any], source_page: dict[str, Any], target_page: dict[str, Any],
    source_rank: int, target_rank: int, marker: dict[str, Any] | None,
) -> dict[str, Any]:
    source_text = clean(source.get("text") or source.get("content") or "")
    target_text = clean(target.get("text") or target.get("content") or "")
    syn = syntax_features(source_text, target_text)
    geo = geometry_features(source, target, source_page, target_page)
    order_score = 1.0 / (1.0 + source_rank + target_rank)
    role_score = 1.0 if role(source) == role(target) else 0.55
    w = CONFIG["weights"]
    combined = w["syntax"] * syn["syntax_score"] + w["geometry"] * geo["geometry_score"] + w["order"] * order_score + w["role"] * role_score
    marker_type = marker.get("continuation_type") if marker else None
    if marker_type == "SENTENCE_CONTINUES":
        combined = max(combined, 0.995)
    elif marker_type == "ARTICLE_CONTINUES":
        combined = min(combined, 0.50)
    strong_syntax = bool(syn["source_hyphen"] or syn["source_open"] or ((not syn["source_terminal"]) and syn["target_lower"]))
    if marker_type == "SENTENCE_CONTINUES":
        decision = "SAME_SENTENCE_MERGE"
    elif combined >= CONFIG["merge_threshold"] and strong_syntax:
        decision = "SAME_SENTENCE_MERGE"
    elif combined >= CONFIG["uncertain_threshold"]:
        decision = "UNRESOLVED"
    else:
        decision = "NO_SENTENCE_MERGE"
    if marker_type == "ARTICLE_CONTINUES":
        decision = "SAME_ARTICLE_NEW_NODE"
    return {
        "source_page": source_page["page"], "target_page": target_page["page"],
        "source_block_id": source.get("block_id") or source.get("id"),
        "target_block_id": target.get("block_id") or target.get("id"),
        "source_text_preview": source_text[-260:], "target_text_preview": target_text[:260],
        "source_role": role(source), "target_role": role(target),
        "source_rank": source_rank, "target_rank": target_rank,
        **syn, **geo, "order_score": round(order_score, 5), "role_score": role_score,
        "marker_present": bool(marker), "marker_type": marker_type,
        "combined_score": round(combined, 5), "decision": decision,
    }


def greedy_one_to_one(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen, used_source, used_target = [], set(), set()
    for row in sorted(rows, key=lambda r: r["combined_score"], reverse=True):
        if row["decision"] not in {"SAME_SENTENCE_MERGE", "SAME_ARTICLE_NEW_NODE"}:
            continue
        source_key = (row["source_page"], row["source_block_id"])
        target_key = (row["target_page"], row["target_block_id"])
        if source_key in used_source or target_key in used_target:
            continue
        used_source.add(source_key); used_target.add(target_key); chosen.append(row)
    return chosen


def read_pages(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(root.glob("page_*.json")):
        page = json.loads(path.read_text(encoding="utf-8"))
        page["page"] = page.get("page") or path.stem
        result.append(page)
    return result


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any], proposals: list[dict[str, Any]], alternatives: list[dict[str, Any]]) -> None:
    def row_html(row: dict[str, Any]) -> str:
        return f"<tr><td>{html.escape(row['source_page'])}<br>{html.escape(str(row['source_block_id']))}</td><td>{html.escape(row['source_text_preview'])}</td><td>{html.escape(row['target_page'])}<br>{html.escape(str(row['target_block_id']))}</td><td>{html.escape(row['target_text_preview'])}</td><td>{row['combined_score']:.3f}<br>{html.escape(row['syntax_reason'])}<br>marker={row['marker_present']}</td><td>{html.escape(row['decision'])}</td></tr>"
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>General cross-page continuation audit</title>"
        "<style>body{font-family:system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px;vertical-align:top}td:nth-child(2),td:nth-child(4){max-width:360px}pre{background:#f4f4f4;padding:12px}</style>"
        f"<h1>General cross-page continuation shadow audit</h1><pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>"
        "<h2>Accepted one-to-one proposals</h2><table><tr><th>Source</th><th>Source text</th><th>Target</th><th>Target text</th><th>Evidence</th><th>Decision</th></tr>"
        + "".join(row_html(row) for row in proposals)
        + "</table><h2>High-scoring unresolved alternatives</h2><table><tr><th>Source</th><th>Source text</th><th>Target</th><th>Target text</th><th>Evidence</th><th>Decision</th></tr>"
        + "".join(row_html(row) for row in alternatives[:150]) + "</table>", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    pages = read_pages(Path(args.aligned_root))
    markers = marker_index(Path(args.marker_links) if args.marker_links else None)
    scored: list[dict[str, Any]] = []
    page_pairs = 0
    for left, right in zip(pages, pages[1:]):
        left_number = int(re.search(r"(\d+)$", left["page"]).group(1))
        right_number = int(re.search(r"(\d+)$", right["page"]).group(1))
        if right_number != left_number + 1:
            continue
        page_pairs += 1
        sources = candidates(left.get("aligned_blocks") or left.get("blocks") or [], "source")
        targets = candidates(right.get("aligned_blocks") or right.get("blocks") or [], "target")
        for si, source in enumerate(reversed(sources)):
            for ti, target in enumerate(targets):
                key = (left["page"], str(source.get("block_id") or source.get("id")), str(target.get("block_id") or target.get("id")))
                scored.append(score_pair(source, target, left, right, si, ti, markers.get(key)))
    proposals = greedy_one_to_one(scored)
    marker_sentence = [row for row in markers.values() if row.get("continuation_type") == "SENTENCE_CONTINUES"]
    recovered_marker_keys = {(p["source_page"], str(p["source_block_id"]), str(p["target_block_id"])) for p in proposals if p["decision"] == "SAME_SENTENCE_MERGE"}
    summary = {
        "document": args.document, "method": "general_cross_page_continuation_shadow_v1",
        "page_pairs": page_pairs, "scored_pairs": len(scored), "accepted_one_to_one": len(proposals),
        "sentence_merge_proposals": sum(p["decision"] == "SAME_SENTENCE_MERGE" for p in proposals),
        "same_article_new_node": sum(p["decision"] == "SAME_ARTICLE_NEW_NODE" for p in proposals),
        "marker_sentence_gold": len(marker_sentence),
        "marker_sentence_recovered": sum((m["logical_page"], str(m.get("source_block_id")), str(m.get("target_block_id"))) in recovered_marker_keys for m in marker_sentence),
        "marker_independent_merge_proposals": sum(p["decision"] == "SAME_SENTENCE_MERGE" and not p["marker_present"] for p in proposals),
        "config": CONFIG, "production_modified": False,
    }
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "cross_page_pair_scores.jsonl", scored)
    write_jsonl(output / "cross_page_merge_proposals.jsonl", proposals)
    alternatives = sorted((r for r in scored if r["decision"] == "UNRESOLVED"), key=lambda r: r["combined_score"], reverse=True)
    write_jsonl(output / "cross_page_unresolved.jsonl", alternatives)
    (output / "cross_page_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(output / "cross_page_report.html", summary, proposals, alternatives)
    return summary


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--document", required=True); p.add_argument("--aligned-root", required=True)
    p.add_argument("--marker-links"); p.add_argument("--output-dir", required=True)
    return p


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), indent=2))
