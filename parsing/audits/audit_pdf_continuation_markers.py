#!/usr/bin/env python3
"""Shadow audit for cross-page continuation markers in born-digital PDFs.

The detector deliberately does not know what a continuation marker looks like or
what character it maps to.  It discovers recurrent, compact symbol-font glyphs
that occur immediately after prose near a logical page's trailing area, maps
them through the split-page manifest, and proposes (but does not apply) links.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


SYMBOL_FONT_HINTS = ("ding", "symbol", "wing", "icon", "glyph", "ornament")
TERMINAL_RE = re.compile(r"[.!?][\]\)}\"'\u2019\u201d]*\s*$")


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def is_symbol_font(font: str) -> bool:
    name = (font or "").lower()
    return any(hint in name for hint in SYMBOL_FONT_HINTS)


def bbox_center(bbox: Iterable[float]) -> tuple[float, float]:
    x0, y0, x1, y1 = [float(v) for v in bbox]
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def classify_continuation(preceding_text: str, following_text: str) -> tuple[str, list[str]]:
    """Classify marker semantics without trusting OCR-invented punctuation."""
    before = normalized_text(preceding_text)
    after = normalized_text(following_text)
    reasons: list[str] = []
    starts_lower = bool(re.match(r"^[a-z]", after))
    has_terminal = bool(TERMINAL_RE.search(before))
    ends_open = bool(
        re.search(
            r"(?:[-\u2013\u2014]|\b(?:a|an|the|and|or|but|of|to|in|on|for|with|from|by|were|was|is|are))\s*$",
            before,
            flags=re.IGNORECASE,
        )
    )
    if starts_lower:
        reasons.append("next_page_starts_lowercase")
    if not has_terminal:
        reasons.append("source_pdf_line_has_no_terminal_punctuation")
    if ends_open:
        reasons.append("source_pdf_line_has_open_ending")
    # An open grammatical ending is sufficient even when the next token is a
    # capitalized proper noun (e.g. "University of" -> "Liverpool").
    if ends_open or (starts_lower and not has_terminal):
        return "SENTENCE_CONTINUES", reasons
    return "ARTICLE_CONTINUES", reasons or ["marker_repeats_but_sentence_boundary_is_complete"]


def map_bbox_to_logical_page(
    source_page_index: int, bbox: Iterable[float], manifest_pages: list[dict[str, Any]]
) -> dict[str, Any] | None:
    cx, cy = bbox_center(bbox)
    for item in manifest_pages:
        if int(item["source_page_index"]) != source_page_index:
            continue
        clip = item["clip"]
        if float(clip["x0"]) <= cx <= float(clip["x1"]) and float(clip["y0"]) <= cy <= float(clip["y1"]):
            return item
    return None


def to_logical_pixel_bbox(
    bbox: Iterable[float], clip: dict[str, float], page_width: float, page_height: float
) -> list[float]:
    x0, y0, x1, y1 = [float(v) for v in bbox]
    cw = float(clip["x1"]) - float(clip["x0"])
    ch = float(clip["y1"]) - float(clip["y0"])
    sx, sy = page_width / cw, page_height / ch
    return [
        (x0 - float(clip["x0"])) * sx,
        (y0 - float(clip["y0"])) * sy,
        (x1 - float(clip["x0"])) * sx,
        (y1 - float(clip["y0"])) * sy,
    ]


def block_bbox(block: dict[str, Any]) -> list[float] | None:
    bbox = block.get("deepseek_bbox") or block.get("bbox")
    if bbox and len(bbox) == 4:
        return [float(v) for v in bbox]
    members = block.get("geometry_members") or []
    if len(members) == 1:
        bbox = members[0].get("pixel_bbox") or members[0].get("bbox")
        if bbox and len(bbox) == 4:
            return [float(v) for v in bbox]
    return None


def block_geometry_record(page: str, block: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": page,
        "block_id": block.get("block_id") or block.get("id"),
        "bbox": block_bbox(block),
        "geometry_members": block.get("geometry_members") or [],
    }


def nearest_source_block(
    blocks: list[dict[str, Any]], marker_bbox: list[float], preceding_pdf_text: str = ""
) -> tuple[dict[str, Any] | None, str | None]:
    phrase = re.sub(r"[^a-z0-9]+", " ", preceding_pdf_text.lower()).strip()
    if len(phrase) >= 12:
        text_matches: list[tuple[int, dict[str, Any]]] = []
        for block in blocks:
            text = re.sub(r"[^a-z0-9]+", " ", normalized_text(block.get("text") or block.get("content") or "").lower()).strip()
            if phrase in text:
                text_matches.append((len(text) - text.rfind(phrase), block))
        if text_matches:
            return min(text_matches, key=lambda item: item[0])[1], "source_pdf_text_exact_phrase"
        phrase_tokens = [token for token in phrase.split() if len(token) >= 3]
        fuzzy_matches: list[tuple[float, dict[str, Any]]] = []
        if len(phrase_tokens) >= 3:
            for block in blocks:
                text = re.sub(r"[^a-z0-9]+", " ", normalized_text(block.get("text") or block.get("content") or "").lower()).strip()
                text_tokens = set(text.split())
                matched = sum(token in text_tokens or any(word.startswith(token) for word in text_tokens) for token in phrase_tokens)
                coverage = matched / len(phrase_tokens)
                if coverage >= 0.75:
                    fuzzy_matches.append((coverage, block))
        if fuzzy_matches:
            return max(fuzzy_matches, key=lambda item: item[0])[1], "source_pdf_text_token_coverage"
    mx, my = bbox_center(marker_bbox)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for block in blocks:
        bbox = block_bbox(block)
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        vertical_distance = 0.0 if y0 <= my <= y1 else min(abs(my - y0), abs(my - y1))
        horizontal_distance = 0.0 if x0 <= mx <= x1 + 16 else min(abs(mx - x0), abs(mx - x1))
        # Strongly prefer the prose box whose terminal line owns the glyph.
        score = 4.0 * vertical_distance + horizontal_distance + abs(my - y1) * 0.05
        role = str(block.get("block_type") or block.get("role") or "").lower()
        if role in {"caption", "heading", "figure", "image", "table"}:
            score += 100.0
        ranked.append((score, block))
    return (min(ranked, key=lambda item: item[0])[1], "marker_geometry_nearest_block") if ranked else (None, None)


def first_continuation_block(blocks: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    ordered_fallback: list[dict[str, Any]] = []
    for block in blocks:
        text = normalized_text(block.get("text") or block.get("content") or "")
        bbox = block_bbox(block)
        role = str(block.get("block_type") or block.get("role") or "").lower()
        if not text or role in {"caption", "heading", "figure", "image", "table"}:
            continue
        if len(text) < 20:
            continue
        ordered_fallback.append(block)
        if not bbox:
            continue
        x0, y0, _, _ = bbox
        # Topmost prose wins; x is only a deterministic tie breaker.
        ranked.append((y0 * 10000.0 + x0, block))
    if ranked:
        return min(ranked, key=lambda item: item[0])[1], "topmost_aligned_geometry"
    if ordered_fallback:
        # This does not invent geometry. It is used only to validate the text
        # boundary when an older aligned artifact predates bbox provenance.
        return ordered_fallback[0], "deepseek_aligned_order_no_geometry"
    return None, None


def read_aligned_page(aligned_root: Path, logical_index: int) -> dict[str, Any] | None:
    path = aligned_root / f"page_{logical_index + 1:04d}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_pages_or_identity(manifest: dict[str, Any], pdf: Any) -> list[dict[str, Any]]:
    pages = manifest.get("pages") or []
    if pages:
        return pages
    if manifest.get("should_split") is False and int(manifest.get("output_page_count") or 0) == len(pdf):
        return [
            {
                "output_page_index": index,
                "source_page_index": index,
                "side": "full",
                "clip": {"x0": 0.0, "y0": 0.0, "x1": float(page.rect.width), "y1": float(page.rect.height)},
            }
            for index, page in enumerate(pdf)
        ]
    raise ValueError("split manifest has no page mapping and cannot be safely interpreted as identity")


def extract_spans(page: Any) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for block_index, block in enumerate(page.get_text("rawdict").get("blocks", [])):
        for line_index, line in enumerate(block.get("lines", [])):
            line_spans = line.get("spans", [])
            for span_index, span in enumerate(line_spans):
                text = "".join(char.get("c", "") for char in span.get("chars", []))
                spans.append(
                    {
                        "bbox": list(span["bbox"]),
                        "font": span.get("font", ""),
                        "size": float(span.get("size", 0)),
                        "text": text,
                        "block_index": block_index,
                        "line_index": line_index,
                        "span_index": span_index,
                        "line_span_count": len(line_spans),
                    }
                )
    return spans


def find_preceding_span(symbol: dict[str, Any], spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    sx0, sy0, _, sy1 = symbol["bbox"]
    scy = (sy0 + sy1) / 2.0
    choices: list[tuple[float, dict[str, Any]]] = []
    for span in spans:
        if span is symbol or is_symbol_font(span["font"]):
            continue
        text = normalized_text(span["text"])
        if len(text) < 2:
            continue
        x0, y0, x1, y1 = span["bbox"]
        y_distance = abs(scy - (y0 + y1) / 2.0)
        x_distance = abs(sx0 - x1)
        if y_distance <= max(5.0, symbol["size"]) and x_distance <= max(10.0, symbol["size"] * 2.0):
            choices.append((3.0 * y_distance + x_distance, span))
    return min(choices, key=lambda item: item[0])[1] if choices else None


def discover_candidates(pdf: Any, manifest_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source_index, page in enumerate(pdf):
        spans = extract_spans(page)
        for span in spans:
            raw = span["text"]
            if not is_symbol_font(span["font"]) or len(raw) != 1:
                continue
            # A continuation mark is commonly emitted as an independently
            # positioned glyph.  Symbols embedded in a text line are far more
            # often equations, URL bullets, or decorative end-of-article marks.
            # This is PDF-structure evidence, not a font/character whitelist.
            if span["line_span_count"] != 1:
                continue
            logical = map_bbox_to_logical_page(source_index, span["bbox"], manifest_pages)
            if not logical:
                continue
            clip = logical["clip"]
            _, cy = bbox_center(span["bbox"])
            y_norm = (cy - float(clip["y0"])) / (float(clip["y1"]) - float(clip["y0"]))
            preceding = find_preceding_span(span, spans)
            if not preceding or y_norm < 0.55:
                continue
            key = f"{span['font'].lower()}|{raw}|{round(span['size'], 1)}"
            candidates.append(
                {
                    "cluster_key": key,
                    "source_page_index": source_index,
                    "logical_page_index": int(logical["output_page_index"]),
                    "logical_page": f"page_{int(logical['output_page_index']) + 1:04d}",
                    "split_side": logical.get("side"),
                    "clip": clip,
                    "pdf_bbox": span["bbox"],
                    "normalized_bbox": [
                        (span["bbox"][0] - float(clip["x0"])) / (float(clip["x1"]) - float(clip["x0"])),
                        (span["bbox"][1] - float(clip["y0"])) / (float(clip["y1"]) - float(clip["y0"])),
                        (span["bbox"][2] - float(clip["x0"])) / (float(clip["x1"]) - float(clip["x0"])),
                        (span["bbox"][3] - float(clip["y0"])) / (float(clip["y1"]) - float(clip["y0"])),
                    ],
                    "font": span["font"],
                    "raw_glyph": raw,
                    "font_size": span["size"],
                    "pdf_block_index": span["block_index"],
                    "pdf_line_index": span["line_index"],
                    "standalone_pdf_line": True,
                    "preceding_pdf_text": normalized_text(preceding["text"]),
                }
            )
    return candidates


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def render_overlays(pdf: Any, proposals: list[dict[str, Any]], output_dir: Path) -> None:
    overlays = output_dir / "overlays"
    overlays.mkdir(parents=True, exist_ok=True)
    for stale in overlays.glob("*_marker.png"):
        stale.unlink()
    for proposal in proposals:
        source_index = proposal["source_page_index"]
        clip = proposal["clip"]
        page = pdf[source_index]
        import fitz  # local import keeps pure helpers testable without PyMuPDF

        clip_rect = fitz.Rect(clip["x0"], clip["y0"], clip["x1"], clip["y1"])
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=clip_rect, alpha=False)
        png = overlays / f"{proposal['logical_page']}_marker.png"
        from PIL import Image, ImageDraw

        mode = "RGBA" if pix.alpha else "RGB"
        image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        draw = ImageDraw.Draw(image)
        marker = proposal["marker_pixel_bbox"]
        pad = 12
        draw.rectangle(
            [marker[0] - pad, marker[1] - pad, marker[2] + pad, marker[3] + pad],
            outline="#e00000",
            width=5,
        )
        draw.text((marker[0] - pad, max(0, marker[1] - 34)), "DISCOVERED CONTINUATION GLYPH", fill="#e00000", stroke_width=2, stroke_fill="white")
        image.save(png)
        proposal["overlay_image"] = str(png.relative_to(output_dir))


def write_html(path: Path, summary: dict[str, Any], proposals: list[dict[str, Any]]) -> None:
    cards = []
    for p in proposals:
        decision = p["continuation_type"]
        color = "#b42318" if decision == "SENTENCE_CONTINUES" else "#175cd3"
        cards.append(
            f"""
            <section class="card">
              <h2>{html.escape(p['logical_page'])} &rarr; {html.escape(p['target_logical_page'])}
                <span style="color:{color}">{decision}</span></h2>
              <div class="grid"><img src="{html.escape(p.get('overlay_image',''))}"><div>
                <p><b>Discovered glyph provenance:</b> {html.escape(p['font'])}, raw code {html.escape(repr(p['raw_glyph']))}, PDF bbox {p['pdf_bbox']}</p>
                <p><b>Source block:</b> {html.escape(str(p.get('source_block_id')))}<br>{html.escape(p.get('source_text_preview',''))}</p>
                <p><b>Next block:</b> {html.escape(str(p.get('target_block_id')))}<br>{html.escape(p.get('target_text_preview',''))}</p>
                <p><b>Signals:</b> {html.escape(', '.join(p['decision_reasons']))}</p>
                <p><b>Action:</b> {html.escape(p['shadow_action'])}</p>
              </div></div>
            </section>"""
        )
    path.write_text(
        """<!doctype html><meta charset="utf-8"><title>Continuation marker shadow audit</title>
        <style>body{font-family:system-ui;margin:24px;background:#f6f7f9;color:#111827}.card{background:white;padding:18px;margin:18px 0;border-radius:10px;box-shadow:0 1px 5px #0002}.grid{display:grid;grid-template-columns:minmax(360px,1.2fr) minmax(320px,1fr);gap:20px}img{width:100%;border:1px solid #ccc}h2{margin-top:0}p{line-height:1.45}@media(max-width:900px){.grid{grid-template-columns:1fr}}</style>"""
        + f"<h1>Born-digital continuation-marker shadow audit</h1><pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>"
        + "".join(cards),
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    import fitz

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(args.split_manifest).read_text(encoding="utf-8"))
    aligned_root = Path(args.aligned_root)
    pdf = fitz.open(args.pdf)
    manifest_pages = manifest_pages_or_identity(manifest, pdf)
    raw_candidates = discover_candidates(pdf, manifest_pages)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in raw_candidates:
        groups[item["cluster_key"]].append(item)
    minimum_support = max(2, math.ceil(len(manifest_pages) * 0.03))
    accepted_keys = {key for key, members in groups.items() if len({m["logical_page_index"] for m in members}) >= minimum_support}
    accepted = [item for item in raw_candidates if item["cluster_key"] in accepted_keys]

    proposals: list[dict[str, Any]] = []
    merge_previews: list[dict[str, Any]] = []
    for item in accepted:
        source_page = read_aligned_page(aligned_root, item["logical_page_index"])
        target_page = read_aligned_page(aligned_root, item["logical_page_index"] + 1)
        if not source_page or not target_page:
            item.update({"status": "UNRESOLVED", "reason": "aligned_source_or_target_page_missing"})
            proposals.append(item)
            continue
        page_width = float(source_page.get("page_width") or 768)
        page_height = float(source_page.get("page_height") or 1152)
        marker_px = to_logical_pixel_bbox(item["pdf_bbox"], item["clip"], page_width, page_height)
        source_blocks = source_page.get("aligned_blocks") or source_page.get("blocks") or []
        target_blocks = target_page.get("aligned_blocks") or target_page.get("blocks") or []
        source_block, source_mapping_method = nearest_source_block(source_blocks, marker_px, item["preceding_pdf_text"])
        target_block, target_mapping_method = first_continuation_block(target_blocks)
        if not source_block or not target_block:
            item.update({"status": "UNRESOLVED", "reason": "source_or_target_block_not_mapped", "marker_pixel_bbox": marker_px})
            proposals.append(item)
            continue
        source_text = normalized_text(source_block.get("text") or source_block.get("content") or "")
        target_text = normalized_text(target_block.get("text") or target_block.get("content") or "")
        continuation_type, reasons = classify_continuation(item["preceding_pdf_text"], target_text)
        item.update(
            {
                "status": "RESOLVED",
                "marker_pixel_bbox": marker_px,
                "source_block_id": source_block.get("block_id") or source_block.get("id"),
                "source_block_mapping_method": source_mapping_method,
                "source_text_preview": source_text[-240:],
                "target_logical_page": f"page_{item['logical_page_index'] + 2:04d}",
                "target_block_id": target_block.get("block_id") or target_block.get("id"),
                "target_block_mapping_method": target_mapping_method,
                "target_text_preview": target_text[:240],
                "continuation_type": continuation_type,
                "decision_reasons": reasons,
                "shadow_action": "PROPOSE_NODE_MERGE" if continuation_type == "SENTENCE_CONTINUES" else "LINK_ARTICLE_ONLY_DO_NOT_MERGE_NODE",
            }
        )
        proposals.append(item)
        if continuation_type == "SENTENCE_CONTINUES":
            source_for_join = source_text.rstrip()
            if not TERMINAL_RE.search(item["preceding_pdf_text"]):
                # OCR may hallucinate a period over the marker.  This preview
                # normalizes only the boundary punctuation; source text and
                # mathematical OCR are otherwise left untouched.
                source_for_join = re.sub(r"\s*[.]\s*$", "", source_for_join)
            merge_previews.append(
                {
                    "decision": "PROPOSE_NODE_MERGE",
                    "source": block_geometry_record(item["logical_page"], source_block),
                    "target": block_geometry_record(item["target_logical_page"], target_block),
                    "source_text": source_text,
                    "target_text": target_text,
                    "merged_text_preview": normalized_text(source_for_join + " " + target_text),
                    "geometry_policy": "preserve_per_page_members_no_union",
                    "boundary_normalization": "remove_trailing_OCR_period_only_when_source_PDF_has_no_terminal_punctuation",
                }
            )

    resolved = [p for p in proposals if p.get("status") == "RESOLVED"]
    render_overlays(pdf, resolved, output_dir)
    cluster_rows = [
        {
            "cluster_key": key,
            "candidate_count": len(members),
            "support_pages": sorted({m["logical_page"] for m in members}),
            "accepted": key in accepted_keys,
        }
        for key, members in sorted(groups.items())
    ]
    summary = {
        "document_id": manifest.get("document_id"),
        "source_pdf_pages": len(pdf),
        "logical_pages": len(manifest_pages),
        "raw_symbol_terminal_candidates": len(raw_candidates),
        "candidate_clusters": len(groups),
        "minimum_cross_page_support": minimum_support,
        "accepted_marker_clusters": len(accepted_keys),
        "accepted_marker_occurrences": len(accepted),
        "resolved_occurrences": len(resolved),
        "sentence_continuations": sum(p.get("continuation_type") == "SENTENCE_CONTINUES" for p in resolved),
        "article_only_continuations": sum(p.get("continuation_type") == "ARTICLE_CONTINUES" for p in resolved),
        "node_merge_proposals": sum(p.get("shadow_action") == "PROPOSE_NODE_MERGE" for p in resolved),
        "unresolved": sum(p.get("status") != "RESOLVED" for p in proposals),
        "production_modified": False,
    }
    write_jsonl(output_dir / "continuation_marker_candidates.jsonl", raw_candidates)
    (output_dir / "continuation_marker_clusters.json").write_text(json.dumps(cluster_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(output_dir / "continuation_links.jsonl", proposals)
    write_jsonl(output_dir / "node_merge_preview.jsonl", merge_previews)
    (output_dir / "continuation_marker_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(output_dir / "continuation_marker_report.html", summary, resolved)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--aligned-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


if __name__ == "__main__":
    print(json.dumps(run(build_parser().parse_args()), indent=2))
