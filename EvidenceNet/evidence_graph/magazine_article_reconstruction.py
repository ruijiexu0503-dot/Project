"""Shadow PoC for page-level magazine article reconstruction."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import load_config
from .io_utils import read_jsonl, write_json
from .llm_client import create_llm
from .continuation_detector import completeness

DEFAULT_PAGES = ["page_0007", "page_0008", "page_0009", "page_0014", "page_0017", "page_0021", "page_0022"]
VISUAL_LABELS = {"image": "figure", "chart": "figure", "figure": "figure", "table": "table"}
TEXT_NODE_TYPES = {"text", "paragraph", "list"}


def _members(node: dict[str, Any], aligned_by_block: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    result = []
    for member in node.get("source_members", []):
        block = (aligned_by_block or {}).get(member.get("block_id"), {})
        result.append({"page": member.get("page"), "block_id": member.get("block_id"),
                       "bbox": member.get("bbox") or member.get("deepseek_bbox") or member.get("raw_bbox") or block.get("bbox"),
                       "role": member.get("role"), "matched_region_id": member.get("matched_region_id")})
    return result


def _page_image(nodes, visuals):
    for item in visuals:
        path = item.get("page_image")
        if path and Path(path).exists(): return path
    for node in nodes:
        for member in node.get("source_members", []):
            path = member.get("page_image")
            if path and Path(path).exists(): return path
    return None


def _project_root(path: Path) -> Path:
    """Find the shared project root from an EvidenceNet/parsing path."""
    resolved = path.resolve()
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / "parsing").is_dir() and (ancestor / "EvidenceNet").is_dir():
            return ancestor
    return Path.cwd().resolve()


def _resolve_existing_path(value, roots) -> str | None:
    """Resolve a stored absolute or project-relative asset path conservatively."""
    if not value:
        return None
    path = Path(value)
    candidates = [path] if path.is_absolute() else [Path(root) / path for root in roots]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return None


def _visual_record(visual):
    kind = visual.get("visual_type") or "visual"
    caption = (visual.get("caption_text") or "").strip()
    return {"visual_node_id": visual.get("node_id"), "visual_type": kind,
            "content_summary": caption[:500] if caption else f"{kind} region; inspect supplied crop.",
            "visible_text": caption[:800],
            "document_role": "supporting_table" if kind == "table" else "supporting_figure",
            "related_topic": "caption-associated page content" if caption else "undetermined from caption",
            "bbox": visual.get("bbox"), "asset_path": visual.get("asset_path"),
            "caption_evidence_id": visual.get("caption_evidence_id"),
            "description_source": "caption_or_visual_metadata_fallback"}


def _bbox(record):
    value = record.get("bbox") or record.get("deepseek_bbox")
    return value if isinstance(value, list) and len(value) == 4 else None


def _caption_distance(visual_bbox, caption_bbox, page_width, page_height):
    """Geometry-only caption affinity; lower is better."""
    vx1, vy1, vx2, vy2 = visual_bbox; cx1, cy1, cx2, cy2 = caption_bbox
    overlap = max(0.0, min(vx2, cx2) - max(vx1, cx1)) / max(1.0, min(vx2 - vx1, cx2 - cx1))
    vertical_gap = max(0.0, cy1 - vy2) / max(1.0, page_height)
    center_gap = abs(((vx1 + vx2) - (cx1 + cx2)) / 2.0) / max(1.0, page_width)
    above_penalty = 0.25 if cy2 < vy1 else 0.0
    return vertical_gap + 0.35 * center_gap + above_penalty - 0.2 * overlap


def _crop_visual(page_image, bbox, target):
    from PIL import Image
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(page_image) as image:
        x1, y1, x2, y2 = [int(round(value)) for value in bbox]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.width, x2), min(image.height, y2)
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid visual crop bbox: {bbox}")
        image.crop((x1, y1, x2, y2)).save(target)


def _grounded_visual_records(page_payload, asset_roots=()):
    """Promote grounded image blocks to visual inputs without duplicating them as text."""
    records = []
    for block in page_payload.get("aligned_blocks", []):
        if str(block.get("block_type") or "").lower() != "image":
            continue
        members = [
            {"bbox": member.get("bbox") or member.get("pixel_bbox"),
             "member_id": member.get("member_id"), "source_id": member.get("source_id")}
            for member in (block.get("geometry_members") or [])
            if _bbox(member)
        ]
        bbox = _bbox(block)
        if bbox is None and len(members) == 1:
            bbox = members[0]["bbox"]
        stored_asset = block.get("asset_path") or (block.get("raw") or {}).get("asset_path")
        records.append({
            "visual_node_id": block.get("block_id"),
            "visual_type": "figure",
            "content_summary": None,
            "visible_text": "",
            "document_role": "supporting_figure",
            "related_topic": None,
            "bbox": bbox,
            "bbox_members": members,
            "asset_path": _resolve_existing_path(stored_asset, asset_roots),
            "stored_asset_path": stored_asset,
            "caption_block_id": None,
            "caption_evidence_id": None,
            "source_region_ids": [block.get("matched_region_id")] if block.get("matched_region_id") else [],
            "source_block_id": block.get("block_id"),
            "description_source": "pending_vlm_description",
            "geometry_source": "deepseekocr2_grounding_group",
        })
    return records


def _layout_visual_records(doc_id, page_payload, page_image, page_dir, excluded_region_ids=None):
    """Create one shadow visual per layout region; never union unrelated regions."""
    page = page_payload.get("page") or "page_unknown"
    excluded_region_ids = {value for value in (excluded_region_ids or []) if value}
    regions = []
    for region in page_payload.get("layout_regions", []):
        label = str(region.get("label") or "").lower()
        bbox = _bbox(region)
        if label in VISUAL_LABELS and bbox and region.get("region_id") not in excluded_region_ids:
            regions.append((region, VISUAL_LABELS[label], bbox))
    captions = [block for block in page_payload.get("aligned_blocks", [])
                if str(block.get("block_type") or "").lower() == "caption" and _bbox(block)]
    width = float(page_payload.get("page_width") or 1); height = float(page_payload.get("page_height") or 1)
    used_captions = set(); records = []
    for index, (region, kind, bbox) in enumerate(regions, 1):
        candidates = sorted(((_caption_distance(bbox, _bbox(caption), width, height), caption)
                             for caption in captions if caption.get("block_id") not in used_captions), key=lambda pair: pair[0])
        caption = candidates[0][1] if candidates and candidates[0][0] <= 0.22 else None
        if caption: used_captions.add(caption.get("block_id"))
        region_id = region.get("region_id") or f"region_{index:04d}"
        node_id = f"{doc_id}_VIS_{page}_{region_id}"
        asset = page_dir / "visual_assets" / f"{node_id}.png"
        if page_image and Path(page_image).exists():
            _crop_visual(page_image, bbox, asset)
        caption_text = (caption or {}).get("text", "")
        records.append({"visual_node_id": node_id, "visual_type": kind, "content_summary": None,
                        "visible_text": caption_text, "document_role": "supporting_table" if kind == "table" else "supporting_figure",
                        "related_topic": None, "bbox": bbox, "asset_path": str(asset.resolve()) if asset.exists() else None,
                        "caption_block_id": (caption or {}).get("block_id"), "caption_evidence_id": None,
                        "source_region_ids": [region_id], "source_region_labels": [region.get("label")],
                        "description_source": "pending_vlm_description"})
    return records


def _describe_visual(llm, visual, max_new_tokens=450):
    asset = visual.get("asset_path")
    if not asset or not Path(asset).exists():
        return {**visual, "content_summary": visual.get("visible_text") or "Visual crop unavailable.",
                "description_source": "caption_fallback_missing_crop"}
    prompt = ("Describe this single document visual for article reconstruction. Identify what is visibly shown, "
              "the subject/entity, chart axes or image scene when legible, and which nearby caption/topic it supports. "
              "Do not infer facts that are not visible. Use short plain-language strings: no LaTeX, backslashes, or equations. "
              "Return one compact JSON object only with keys content_summary, visible_text, document_role, related_topic. "
              "Nearby caption OCR (may be empty): " + json.dumps(visual.get("visible_text") or ""))
    try:
        generation = llm.generate_json_with_images("Grounded document-visual describer. Compact valid JSON only.", prompt,
                                                   [asset], max(max_new_tokens, 700))
    except ValueError as exc:
        retry = (prompt + "\nThe prior response was invalid or truncated. Keep every value below 80 words and emit no markdown.")
        try:
            generation = llm.generate_json_with_images("Grounded document-visual describer. Compact valid JSON only.", retry,
                                                       [asset], max(max_new_tokens, 900))
        except ValueError as retry_exc:
            return {**visual, "content_summary": visual.get("visible_text") or "Visual region; inspect crop.",
                    "related_topic": visual.get("visible_text") or "undetermined", "description_source": "caption_fallback_after_vlm_parse_error",
                    "description_error": f"{exc}; retry: {retry_exc}"}
    parsed = generation.parsed if isinstance(generation.parsed, dict) else {}
    return {**visual,
            "content_summary": parsed.get("content_summary") or visual.get("visible_text") or "Visual region; inspect crop.",
            "visible_text": parsed.get("visible_text") or visual.get("visible_text") or "",
            "document_role": parsed.get("document_role") or visual.get("document_role"),
            "related_topic": parsed.get("related_topic") or "undetermined",
            "description_source": "vlm_crop_description",
            "description_model": generation.model,
            "description_raw_response": generation.raw}


def _prompt(doc_id, page, rows):
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    return (f"Reconstruct page {page} of {doc_id} from existing parsed nodes. First determine logical "
            "article/content-item grouping; only then determine reading order inside each article. "
            "Use text, node type, bbox, columns, continuation cues, captions and visual descriptions. "
            "ARTICLE BOUNDARIES: first list the independent top-level article starts mentally. A new large/top-level "
            "heading, especially when preceded by a new organisation/experiment/category label and separated vertically "
            "or by a rule, is strong evidence for a new article. Two independent top-level headings must not be merged "
            "merely because they share a page, topic, or layout. A heading may remain inside an article only when it is "
            "clearly a subordinate section heading. "
            "VISUALS: visual nodes and caption text nodes are distinct inputs and both must be included. Each visual node "
            "contains a grounded visual_description produced from its own image crop; use that description together with "
            "the visual bbox, nearby caption, headings and body text to determine article ownership. Assign every content "
            "figure/table/photo exactly once to the article it actually illustrates. Place it in reading_order at the point "
            "where the article introduces, references, captions, or explains it; do not automatically put it first merely "
            "because it is visually large or high on the page. Never use one visual to bridge otherwise independent "
            "articles. A content figure/table/photo must not be placed in non_article_nodes. Only a clearly decorative mark, "
            "logo, page furniture, or unrelated advertisement visual may be non-article. "
            "TEXT CONTINUATION HAS PRIORITY OVER VISUAL PLACEMENT: if a text block ends with an incomplete word, "
            "unfinished sentence, hyphenated continuation, or other clear continuation cue, first find and read the text "
            "block that completes it. Keep those text blocks adjacent in reading_order. Do not insert a figure, table, "
            "caption, sidebar, or another article between them. Only after the interrupted sentence or paragraph has been "
            "completed should reading_order return to the related visual and caption. For example, a block ending in "
            "'meas' followed by a block beginning 'ured to be' must be ordered consecutively as 'meas' -> 'ured to be'. "
            "An editorial article is a coherent headline/body/visual unit. Sidebar, brief, advertisement, "
            "running footer and page number may be separate or non-article, following the existing dataset "
            "convention. Do not change article boundaries to improve order. Every input node must appear "
            "exactly once in an article or non_article_nodes. Return JSON only: "
            '{"articles":[{"article_id":"A1","node_ids":["..."],"reading_order":["..."]}],"non_article_nodes":["..."]}\n'
            "NODES:\n" + payload)


def _starts_lowercase_continuation(text):
    match = re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", str(text or "").lstrip(" \t\"'‘’“”([{–—-"))
    return bool(match and match.group(0).islower())


def _continuation_constraints(rows):
    """Find strong text continuations separated only by caption-like material."""
    constraints = []
    for index, source in enumerate(rows):
        if str(source.get("node_type") or "").lower() not in TEXT_NODE_TYPES: continue
        source_text = str(source.get("text") or "").strip()
        complete, possible, reason = completeness(source_text)
        if complete and not possible: continue
        skipped = []
        for target in rows[index + 1:]:
            target_type = str(target.get("node_type") or "").lower()
            if target_type == "caption":
                skipped.append(target.get("node_id")); continue
            if target_type not in TEXT_NODE_TYPES: break
            target_text = str(target.get("text") or "").strip()
            if skipped and _starts_lowercase_continuation(target_text):
                constraints.append({"source": source.get("node_id"), "target": target.get("node_id"),
                                    "reason": reason or "unfinished_text_followed_by_lowercase_continuation",
                                    "skipped_caption_ids": skipped})
            break
    return constraints


def _validate(result, ids, top_level_heading_ids=None, required_article_visual_ids=None, continuation_constraints=None):
    errors, assigned = [], []
    if not isinstance(result, dict) or not isinstance(result.get("articles"), list):
        return {"valid": False, "errors": ["missing_articles"]}
    for article in result["articles"]:
        members = article.get("node_ids", []); order = article.get("reading_order", [])
        if set(members) != set(order): errors.append({"type": "membership_order_mismatch", "article_id": article.get("article_id")})
        if len(order) != len(set(order)): errors.append({"type": "duplicate_order", "article_id": article.get("article_id")})
        headings = sorted(set(members) & set(top_level_heading_ids or []))
        if len(headings) > 1:
            errors.append({"type": "multiple_top_level_headings_in_one_article", "article_id": article.get("article_id"),
                           "node_ids": headings})
        assigned.extend(members)
    assigned.extend(result.get("non_article_nodes", []))
    misplaced_visuals = sorted(set(result.get("non_article_nodes", [])) & set(required_article_visual_ids or []))
    if misplaced_visuals:
        errors.append({"type": "content_visual_assigned_non_article", "node_ids": misplaced_visuals})
    if len(assigned) != len(set(assigned)): errors.append({"type": "node_assigned_multiple_times"})
    missing = sorted(ids - set(assigned)); extra = sorted(set(assigned) - ids)
    if missing: errors.append({"type": "missing_nodes", "node_ids": missing})
    if extra: errors.append({"type": "unknown_nodes", "node_ids": extra})
    article_by_node = {node_id: article for article in result.get("articles", []) for node_id in article.get("node_ids", [])}
    for constraint in continuation_constraints or []:
        source = constraint["source"]; target = constraint["target"]
        article = article_by_node.get(source)
        if article is None or article is not article_by_node.get(target):
            errors.append({"type": "continuation_pair_split_across_articles", **constraint}); continue
        order = article.get("reading_order", [])
        if source not in order or target not in order or order.index(target) != order.index(source) + 1:
            errors.append({"type": "continuation_pair_not_adjacent", **constraint})
    return {"valid": not errors, "errors": errors, "missing_nodes": missing, "extra_nodes": extra}


def _normalise_result(result):
    """Repair the common one-element JSON-array wrapper from Qwen."""
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        return result[0]
    return result


def _attach_caption_grounded_visuals(result, visual_rows):
    """Insert visuals beside their geometry-associated captions without semantic guessing."""
    if not isinstance(result, dict): return result, []
    articles = result.get("articles", []); non_article = result.get("non_article_nodes", []); repairs = []
    for visual in visual_rows:
        visual_id = visual.get("visual_node_id"); caption_id = visual.get("caption_block_id")
        if not visual_id or not caption_id: continue
        targets = [article for article in articles if caption_id in article.get("node_ids", [])]
        if len(targets) != 1: continue
        target = targets[0]
        for article in articles:
            article["node_ids"] = [node_id for node_id in article.get("node_ids", []) if node_id != visual_id]
            article["reading_order"] = [node_id for node_id in article.get("reading_order", []) if node_id != visual_id]
        non_article = [node_id for node_id in non_article if node_id != visual_id]
        target["node_ids"].insert(target["node_ids"].index(caption_id), visual_id)
        target["reading_order"].insert(target["reading_order"].index(caption_id), visual_id)
        repairs.append({"type": "caption_grounded_visual_attachment", "visual_node_id": visual_id,
                        "caption_block_id": caption_id, "article_id": target.get("article_id"),
                        "reading_order_position": "immediately_before_caption"})
    result["non_article_nodes"] = non_article
    return result, repairs


def _short_article_label(row):
    text = str(row.get("text") or "").strip()
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text)
    return (str(row.get("node_type") or "").lower() == "text" and 0 < len(words) <= 5
            and len(text) <= 60 and not re.search(r"[.!?]$", text))


def _split_multiple_heading_articles(result, rows, top_level_heading_ids):
    """Split only an LLM article that violates the independent top-heading invariant."""
    if not isinstance(result, dict): return result, []
    row_index = {row.get("node_id"): index for index, row in enumerate(rows)}
    rebuilt = []; detached = list(result.get("non_article_nodes", [])); repairs = []
    for article in result.get("articles", []):
        member_ids = set(article.get("node_ids", []))
        headings = sorted(member_ids & set(top_level_heading_ids or []), key=lambda node_id: row_index.get(node_id, 10**9))
        if len(headings) <= 1:
            rebuilt.append(article); continue
        boundaries = []
        for heading_number, heading_id in enumerate(headings):
            boundary = row_index[heading_id]
            if heading_number and boundary > 0:
                predecessor = rows[boundary - 1]
                if predecessor.get("node_id") in member_ids and _short_article_label(predecessor):
                    boundary -= 1
            boundaries.append(boundary)
        known_members = {node_id for node_id in member_ids if node_id in row_index}
        detached.extend(node_id for node_id in member_ids if node_id not in row_index)
        source_order = article.get("reading_order", [])
        for segment_number, start in enumerate(boundaries):
            end = boundaries[segment_number + 1] if segment_number + 1 < len(boundaries) else 10**9
            segment_ids = {node_id for node_id in known_members if start <= row_index[node_id] < end}
            if segment_number == 0:
                segment_ids |= {node_id for node_id in known_members if row_index[node_id] < start}
            ordered = [node_id for node_id in source_order if node_id in segment_ids]
            # Preserve every member even if the model omitted it from reading_order; validation will still audit it.
            ordered += [row.get("node_id") for row in rows if row.get("node_id") in segment_ids and row.get("node_id") not in ordered]
            rebuilt.append({**article, "node_ids": list(ordered), "reading_order": list(ordered)})
        repairs.append({"type": "split_multiple_independent_top_level_headings",
                        "original_article_id": article.get("article_id"), "heading_node_ids": headings,
                        "resulting_article_count": len(headings)})
    for index, article in enumerate(rebuilt, 1): article["article_id"] = f"A{index}"
    result["articles"] = rebuilt
    result["non_article_nodes"] = list(dict.fromkeys(detached))
    return result, repairs


def _enforce_continuation_constraints(result, constraints):
    """Keep strongly grounded text continuations adjacent within an LLM-selected article."""
    if not isinstance(result, dict): return result, []
    repairs = []
    for constraint in constraints:
        source = constraint["source"]; target = constraint["target"]
        matches = [article for article in result.get("articles", [])
                   if source in article.get("reading_order", []) and target in article.get("reading_order", [])]
        if len(matches) != 1: continue
        article = matches[0]; order = article["reading_order"]
        if order.index(target) == order.index(source) + 1: continue
        order.remove(target); order.insert(order.index(source) + 1, target)
        repairs.append({"type": "strong_text_continuation_adjacency", "article_id": article.get("article_id"), **constraint})
    return result, repairs


def run(args):
    cfg = load_config(args.config); source = Path(cfg["output"]["graph_root"]) / args.doc_id
    output = Path(args.output) / args.doc_id; output.mkdir(parents=True, exist_ok=True)
    evidence_path = source / "evidence_nodes.jsonl"
    if evidence_path.exists():
        nodes = read_jsonl(evidence_path)
    elif args.node_source == "aligned":
        nodes = []
    else:
        raise FileNotFoundError(f"Missing EvidenceNode input: {evidence_path}")
    aligned_root = Path(args.aligned_root) / args.doc_id
    if (aligned_root / "aligned_json").exists(): aligned_root = aligned_root / "aligned_json"
    elif not aligned_root.exists() and (Path(args.aligned_root) / args.doc_id / "aligned_json").exists():
        aligned_root = Path(args.aligned_root) / args.doc_id / "aligned_json"
    project_root = _project_root(aligned_root)
    asset_roots = (project_root, aligned_root, Path.cwd())
    aligned_by_page = {}
    for page_path in aligned_root.glob("page_*.json"):
        payload = json.loads(page_path.read_text(encoding="utf-8")); aligned_by_page[payload["page"]] = payload
    visuals = read_jsonl(source / "visual_nodes.jsonl") if (source / "visual_nodes.jsonl").exists() else []
    by_page = defaultdict(list); visual_by_page = defaultdict(list)
    for node in nodes:
        for page in node.get("page_ids", []): by_page[page].append(node)
    for visual in visuals: visual_by_page[visual.get("page")].append(visual)
    pages = args.pages or DEFAULT_PAGES
    if args.repair_existing:
        page_results = []
        for page in pages:
            page_dir = output / page; parsed_path = page_dir / "qwen_parsed.json"
            if not parsed_path.exists(): continue
            parsed = _normalise_result(json.loads(parsed_path.read_text())); write_json(parsed_path, parsed)
            rep = json.loads((page_dir / "page_representation.json").read_text())
            expected = {x["node_id"] for x in rep.get("nodes", [])} | {x["visual_node_id"] for x in rep.get("visual_regions", [])}
            validation = _validate(parsed, expected); write_json(page_dir / "validation.json", validation)
            page_results.append({"page": page, "status": "repaired", "node_count": len(rep.get("nodes", [])),
                                 "visual_count": len(rep.get("visual_regions", [])), "article_count": len(parsed.get("articles", [])) if isinstance(parsed, dict) else None,
                                 "validation": validation})
        summary = {"doc_id": args.doc_id, "pages": pages, "source_nodes": len(nodes), "page_results": page_results,
                   "production_modified": False, "model_stage": "existing_outputs_repaired"}
        write_json(output / "reconstruction_summary.json", summary); return summary
    llm = None if args.prepare_only else create_llm(cfg["enrichment"])
    page_results = []
    for page in pages:
        page_nodes = sorted(by_page.get(page, []), key=lambda n: n.get("document_order", 10**9))
        page_aligned = aligned_by_page.get(page, {}); aligned_blocks = page_aligned.get("aligned_blocks", [])
        if args.node_source == "aligned" and not aligned_blocks:
            raise RuntimeError(f"No aligned blocks found for {page}; refusing EvidenceNode fallback")
        aligned_by_block = {b.get("block_id"): b for b in aligned_blocks}
        if args.node_source == "aligned" and aligned_blocks:
            rows = [{"node_id": b.get("block_id"), "node_type": b.get("block_type", "text"),
                     "bbox_members": [{"block_id": b.get("block_id"), "bbox": m.get("bbox")} for m in (b.get("geometry_members") or [])] or [{"block_id": b.get("block_id"), "bbox": b.get("bbox") or b.get("deepseek_bbox")}],
                     "text": b.get("text", ""), "visual_description": None} for b in aligned_blocks
                    if str(b.get("block_type") or "").lower() != "image"]
        else:
            rows = [{"node_id": n["node_id"], "node_type": n.get("evidence_type") or n.get("node_type"),
                     "bbox_members": _members(n, aligned_by_block), "text": n.get("plain_text", ""), "visual_description": None}
                    for n in page_nodes]
        image = page_aligned.get("page_image") or _page_image(page_nodes, visual_by_page.get(page, []))
        if image:
            image = _resolve_existing_path(image, asset_roots)
        page_dir = output / page; page_dir.mkdir(exist_ok=True)
        grounded_visual_rows = _grounded_visual_records(page_aligned, asset_roots)
        grounded_region_ids = {
            region_id for visual in grounded_visual_rows for region_id in visual.get("source_region_ids", [])
        }
        visual_rows = grounded_visual_rows + _layout_visual_records(
            args.doc_id, page_aligned, image, page_dir, grounded_region_ids
        )
        if not visual_rows:
            visual_rows = [_visual_record(v) for v in visual_by_page.get(page, [])]
        if not args.prepare_only:
            descriptions_path = page_dir / "visual_descriptions.jsonl"
            cached = read_jsonl(descriptions_path) if descriptions_path.exists() else []
            cached_by_id = {row.get("visual_node_id"): row for row in cached}
            visual_rows = [cached_by_id.get(visual.get("visual_node_id")) or
                           _describe_visual(llm, visual, args.visual_description_tokens) for visual in visual_rows]
            with descriptions_path.open("w", encoding="utf-8") as handle:
                for visual in visual_rows:
                    handle.write(json.dumps(visual, ensure_ascii=False) + "\n")
        for row in rows:
            row["visual_description"] = next((x for x in visual_rows if x.get("caption_block_id") == row["node_id"]
                                               or x.get("caption_evidence_id") == row["node_id"]), None)
        if args.resume and (page_dir / "qwen_parsed.json").exists() and (page_dir / "page_representation.json").exists():
            parsed = _normalise_result(json.loads((page_dir / "qwen_parsed.json").read_text(encoding="utf-8")))
            validation_path = page_dir / "validation.json"
            validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else _validate(parsed, {x["node_id"] for x in rows} | {x["visual_node_id"] for x in visual_rows})
            page_results.append({"page": page, "status": "resumed", "node_count": len(rows),
                                 "geometry_nodes": sum(bool(any(m.get("bbox") for m in row["bbox_members"])) for row in rows),
                                 "visual_count": len(visual_rows), "article_count": len(parsed.get("articles", [])) if isinstance(parsed, dict) else None,
                                 "validation": validation})
            continue
        representation = {"document_id": args.doc_id, "page": page, "page_image": image, "nodes": rows, "visual_regions": visual_rows}
        write_json(page_dir / "page_representation.json", representation)
        prompt_rows = rows + [{"node_id": x["visual_node_id"], "node_type": "visual_region", "bbox": x["bbox"],
                               "bbox_members": x.get("bbox_members") or [],
                               "text": x.get("visible_text", ""), "visual_description": x} for x in visual_rows]
        continuation_constraints = _continuation_constraints(rows)
        prompt = _prompt(args.doc_id, page, prompt_rows)
        if continuation_constraints:
            prompt += ("\nMANDATORY TEXT CONTINUATION ADJACENCY CONSTRAINTS (derived conservatively from parsed text; "
                       "do not place any node between each source and target):\n" +
                       json.dumps(continuation_constraints, ensure_ascii=False, indent=2))
        (page_dir / "qwen_prompt.txt").write_text(prompt, encoding="utf-8")
        geometry_count = sum(bool(any(m.get("bbox") for m in row["bbox_members"])) for row in rows)
        if args.prepare_only:
            page_results.append({"page": page, "status": "prepared", "node_count": len(rows), "geometry_nodes": geometry_count, "visual_count": len(visual_rows)})
            continue
        images = [image] if image else []
        images += [x["asset_path"] for x in visual_rows if x.get("asset_path") and Path(x["asset_path"]).exists()][:8]
        expected_ids = {x["node_id"] for x in rows} | {x["visual_node_id"] for x in visual_rows}
        top_headings = {x["node_id"] for x in rows if x.get("node_type") == "heading" and str(x.get("text") or "").lstrip().startswith("# ")}
        generation = llm.generate_json_with_images("Conservative document reconstruction assistant. JSON only.", prompt, images, args.max_new_tokens)
        parsed = _normalise_result(generation.parsed)
        parsed, repairs = _split_multiple_heading_articles(parsed, rows, top_headings)
        parsed, visual_repairs = _attach_caption_grounded_visuals(parsed, visual_rows)
        repairs += visual_repairs
        parsed, continuation_repairs = _enforce_continuation_constraints(parsed, continuation_constraints)
        repairs += continuation_repairs
        required_visuals = {x["visual_node_id"] for x in visual_rows}
        validation = _validate(parsed, expected_ids, top_headings, required_visuals, continuation_constraints)
        attempts = [{"attempt": 1, "validation": validation, "deterministic_repairs": repairs, "raw": generation.raw}]
        for attempt in range(args.max_validation_retries):
            if validation["valid"]: break
            retry_prompt = (prompt + "\nYour previous result failed validation: " + json.dumps(validation["errors"], ensure_ascii=False) +
                            "\nReturn a corrected complete JSON assignment. Do not merge independent top-level headings.")
            generation = llm.generate_json_with_images("Conservative document reconstruction assistant. JSON only.", retry_prompt, images, args.max_new_tokens)
            parsed = _normalise_result(generation.parsed); parsed, repairs = _split_multiple_heading_articles(parsed, rows, top_headings)
            parsed, visual_repairs = _attach_caption_grounded_visuals(parsed, visual_rows)
            repairs += visual_repairs
            parsed, continuation_repairs = _enforce_continuation_constraints(parsed, continuation_constraints)
            repairs += continuation_repairs
            validation = _validate(parsed, expected_ids, top_headings, required_visuals, continuation_constraints)
            attempts.append({"attempt": attempt + 2, "validation": validation, "deterministic_repairs": repairs, "raw": generation.raw})
        write_json(page_dir / "qwen_parsed.json", parsed)
        (page_dir / "qwen_raw_response.txt").write_text(generation.raw, encoding="utf-8")
        write_json(page_dir / "generation_attempts.json", attempts)
        write_json(page_dir / "validation.json", validation)
        page_results.append({"page": page, "status": "complete", "node_count": len(rows), "geometry_nodes": geometry_count, "visual_count": len(visual_rows),
                             "article_count": len(parsed.get("articles", [])) if isinstance(parsed, dict) else None, "validation": validation})
    summary = {"doc_id": args.doc_id, "pages": pages, "source_nodes": len(nodes),
               "selected_nodes": sum(x["node_count"] for x in page_results), "page_results": page_results,
               "production_modified": False, "model_stage": "prepared_only" if args.prepare_only else cfg["enrichment"].get("model")}
    write_json(output / "reconstruction_summary.json", summary); return summary


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--doc-id", required=True); parser.add_argument("--config", required=True)
    parser.add_argument("--output", default="output/magazine_article_reconstruction_poc"); parser.add_argument("--pages", nargs="*")
    parser.add_argument("--aligned-root", default="parsing/output/hybrid_deepseek_layout_mvp/aligned_json")
    parser.add_argument("--node-source", choices=["aligned", "evidence"], default="aligned")
    parser.add_argument("--prepare-only", action="store_true"); parser.add_argument("--repair-existing", action="store_true"); parser.add_argument("--resume", action="store_true"); parser.add_argument("--max-new-tokens", type=int, default=1400)
    parser.add_argument("--visual-description-tokens", type=int, default=700)
    parser.add_argument("--max-validation-retries", type=int, default=1)
    args = parser.parse_args(argv); print(json.dumps(run(args), indent=2, ensure_ascii=False))


if __name__ == "__main__": main()
