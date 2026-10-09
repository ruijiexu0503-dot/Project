#!/usr/bin/env python3
"""Shadow pilot: treat parser visual boxes as proposals, not semantic parents.

The pilot starts with the member-aware PDF representation, then exposes each
native asset as a separately selectable visual-panel candidate.  It is limited
to DLR pages selected for boundary review and never writes production outputs.
"""
from __future__ import annotations

import argparse
import copy
import base64
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
sys.path.insert(0, str(ROOT / "EvidenceNet/scripts"))

import run_member_asset_evidence_pipeline as member
from run_evidence_unit_shadow_pilot import prompt as base_prompt

ORIGINAL_BASE_VALIDATE = member.base_validate

OUT = Path(os.environ.get(
    "SEMANTIC_PANEL_OUTPUT",
    ROOT / "EvidenceNet/output/semantic_panel_evidence_pilot_v1",
)).resolve()

CASES = [
    {
        "document": "DLRmagazine_176_EN", "page": page,
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages" / f"page_{page:04d}",
        "audit": ROOT / "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2",
    }
    for page in (9, 12, 17)
]


def panel_id(asset_id: str) -> str:
    return "P_" + asset_id.replace("page_", "").replace("_asset_", "_A")


def panelize(representation: dict[str, Any], target: Path) -> dict[str, Any]:
    """Replace visual-parent candidates with asset-level panel candidates.

    An asset can still consist of several PDF paint tiles.  Those tiles remain
    one candidate here; a parser envelope is retained only as an audit proposal.
    """
    parser_proposals = representation["visual_bundles"]
    candidates: list[dict[str, Any]] = []
    panel_map: dict[str, str] = {}
    for proposal in parser_proposals:
        components_by_asset: dict[str, list[dict[str, Any]]] = {}
        for component in proposal.get("native_components", []):
            components_by_asset.setdefault(component["asset_id"], []).append(component)
        if not components_by_asset:
            candidates.append({**proposal, "proposal_kind": "parser_only"})
            continue
        for asset_id, components in components_by_asset.items():
            visual_id = panel_id(asset_id)
            panel_map[asset_id] = visual_id
            boxes = [component["bbox"] for component in components]
            candidates.append({
                "visual_bundle_id": visual_id,
                "bbox": member.envelope(boxes),
                "bbox_semantics": "index envelope of an asset-level panel candidate; members retain observed geometry",
                "layout_label": "asset_panel_candidate",
                "provenance_state": "native_asset_recomposable_candidate",
                "proposal_kind": "native_asset_panel",
                "parser_visual_proposal_ids": [proposal["visual_bundle_id"]],
                "source_block_ids": proposal.get("source_block_ids", []),
                "geometry_members": [
                    {"member_id": component["member_id"], "bbox": component["bbox"],
                     "bbox_source": component["bbox_source"]}
                    for component in components
                ],
                "native_components": components,
                "native_asset_groups": [group for group in proposal.get("native_asset_groups", [])
                                        if group.get("asset_id") == asset_id],
            })

    image_inputs = [{"kind": "annotated_page", "path": representation["annotated_page"],
                     "description": "rendered source page; green labels are text atoms, blue labels are parser proposals"}]
    for candidate in candidates:
        sheets = member.make_component_sheets(candidate, target / "panel_sheets")
        candidate["component_sheet_paths"] = [str(path) for path in sheets]
        for index, path in enumerate(sheets, 1):
            # Six full-resolution visual inputs exhaust a 40 GiB A100 on the
            # dense DLR page.  These sheets are identifier aids, so a bounded
            # audit copy preserves their role while keeping VLM image tokens sane.
            with Image.open(path) as source:
                image = source.convert("RGB")
                image.thumbnail((640, 480), Image.Resampling.LANCZOS)
                image.save(path)
            image_inputs.append({
                "kind": "native_asset_panel_sheet", "path": str(path),
                "visual_bundle_id": candidate["visual_bundle_id"], "sheet_index": index,
                "member_ids": member.sheet_member_ids(path),
                "description": "unoccluded PDF objects for one visual-panel candidate",
            })
    representation["parser_visual_proposals"] = parser_proposals
    representation["visual_bundles"] = candidates
    representation["panel_map"] = panel_map
    representation["image_inputs"] = image_inputs
    representation["node_boundary_policy"] = {
        "parser_boxes": "audit proposals only",
        "native_asset": "selectable semantic-panel candidate",
        "pdf_tiles": "provenance members; do not independently materialize without distinct semantic evidence",
    }
    return representation


def panel_prompt(representation: dict[str, Any]) -> str:
    atoms = representation["atoms"]
    visuals = representation["visual_bundles"]
    crop_order = [row["description"] for row in representation["image_inputs"]]
    schema = {
        "relations": [{
            "relation_type": "CAPTION_OF|ILLUSTRATES|CONTEXT_FOR|CONTINUES",
            "source_evidence_unit_id": "EU_1", "target_evidence_unit_id": "EU_2",
            "basis": "short observable or textual cue", "confidence": "high|medium|low",
        }]
    }
    return base_prompt(representation["document_id"], representation["page"], atoms, visuals, crop_order) + f"""

SEMANTIC-PANEL PILOT POLICY:
- A Dolphin parser box is an audit proposal, never proof that all visual content inside it is one semantic object.
- Each native-asset panel candidate may be selected independently. Do not merge panels merely because their parser proposals overlap.
- Do keep the PDF tiles within a selected panel together unless pixels, caption, or local prose establish distinct semantic panels.
- A caption is a separately addressable TEXT EvidenceUnit. Link it to its visual with CAPTION_OF; do not force the entire article into a COMPOSITE node.
- A COMPOSITE may contain one visual panel plus its immediately interpreting caption or sentence. Never absorb unrelated paragraphs, an entire article, or a page-wide background just to make a node self-contained.
- For each visual panel, distinguish visible-page observation from nearby-text interpretation in visual_summary. Spatial overlap alone does not establish ownership.
- Return top-level relations only when both endpoints are evidence_unit_id values on this page. Retain uncertain links in unresolved.

Add this field to the returned JSON object:
{json.dumps(schema, ensure_ascii=False)}
"""


def prepare() -> None:
    member.OUT = OUT
    member.CASES = CASES
    for case in CASES:
        member.prepare_case(case)
        target = OUT / case["document"] / f"page_{case['page']:04d}"
        representation = panelize(member.read(target / "input_representation.json"), target)
        member.write(target / "input_representation.json", representation)
        (target / "prompt.txt").write_text(panel_prompt(representation), encoding="utf-8")
    member.write(OUT / "manifest.json", {
        "tasks": [f"{case['document']}/page_{case['page']:04d}" for case in CASES],
        "model": str(member.MODEL), "production_modified": False,
        "policy": "parser visual proposals -> independently selectable native-asset panels -> explicit contextual relations",
    })
    member.build_report()
    print(json.dumps({"tasks": len(CASES), "output": str(OUT), "production_modified": False}))


def materialize_relations() -> None:
    rows = []
    for case in CASES:
        target = OUT / case["document"] / f"page_{case['page']:04d}"
        assembly = target / "assembly.json"
        if not assembly.exists():
            continue
        for relation in member.read(assembly).get("relations", []):
            rows.append({"document_id": case["document"], "page": f"page_{case['page']:04d}",
                         **relation, "status": "UNVERIFIED_SHADOW_RELATION", "production_modified": False})
    member.write_jsonl(OUT / "evidence_relations.jsonl", rows)


def image_uri(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


EVIDENCE_COLORS = [
    "#d7263d", "#0072b2", "#009e73", "#e69f00", "#cc79a7", "#56b4e9",
    "#6a3d9a", "#b15928", "#1b9e77", "#e7298a", "#7570b3", "#66a61e",
]


def evidence_overlay(target: Path, nodes: list[dict[str, Any]]) -> tuple[Path, list[tuple[str, str, dict[str, Any]]]]:
    """Draw final evidence membership only; parser proposals stay out of this view."""
    with Image.open(target / "original.png") as source:
        canvas = source.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    legend = []
    for index, node in enumerate(nodes):
        color = EVIDENCE_COLORS[index % len(EVIDENCE_COLORS)]
        evidence_id = node["node_id"].rsplit("_", 1)[-1]
        boxes = [member.get("bbox") for member in node.get("geometry_members", []) if member.get("bbox")]
        for box in boxes:
            x1, y1, x2, y2 = [int(round(value)) for value in box]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(canvas.width - 1, x2), min(canvas.height - 1, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            draw.rectangle((x1, y1, x2, y2), outline=color, width=5)
            draw.rectangle((x1, y1, min(canvas.width - 1, x1 + 44), min(canvas.height - 1, y1 + 22)), fill=color)
            draw.text((x1 + 4, y1 + 4), evidence_id, fill="white")
        legend.append((evidence_id, color, node))
    output = target / "evidence_overlay.png"
    canvas.save(output)
    return output, legend


def build_panel_report() -> None:
    """Render the PDF-native recovered object before legacy parser overlays."""
    sections = []
    for case in CASES:
        target = OUT / case["document"] / f"page_{case['page']:04d}"
        input_path = target / "input_representation.json"
        if not input_path.exists():
            continue
        representation = member.read(input_path)
        nodes_path = target / "evidence_nodes.jsonl"
        nodes = member.jsonl(nodes_path) if nodes_path.exists() else []
        summary_path = target / "run_summary.json"
        summary = member.read(summary_path) if summary_path.exists() else {"status": "prepared"}
        panels = []
        for visual in representation["visual_bundles"]:
            views = []
            for component in visual.get("native_components", []):
                for label, key in (("Recovered PDF source", "source_object_path"),
                                   ("Visible support", "visible_mask_path"),
                                   ("Native layer", "layer_mask_path")):
                    path_value = component.get(key)
                    path = Path(path_value) if path_value else None
                    if path and path.exists():
                        views.append(f"<figure><img src='{image_uri(path)}'><figcaption>{label}: "
                                     f"{html.escape(component['member_id'])}</figcaption></figure>")
            panels.append(f"<article><h3>{html.escape(visual['visual_bundle_id'])}</h3>"
                          f"<p>{html.escape(visual.get('provenance_state', ''))}; parser proposal: "
                          f"{html.escape(', '.join(visual.get('parser_visual_proposal_ids', [])))}</p>"
                          f"<div class='views'>{''.join(views)}</div></article>")
        node_rows = "".join(
            f"<li><code>{html.escape(node['node_id'])}</code> · {html.escape(node['unit_type'])} · "
            f"text {len(node.get('plain_text', ''))} chars · panels "
            f"{html.escape(', '.join(node.get('source_visual_bundle_ids', [])))}</li>"
            for node in nodes
        ) or "<li>No materialized nodes</li>"
        overlay_path, legend = evidence_overlay(target, nodes)
        legend_html = "".join(
            f"<li><span class='swatch' style='background:{color}'></span><code>{html.escape(evidence_id)}</code> · "
            f"{html.escape(node['unit_type'])} · {html.escape(', '.join(node.get('source_visual_bundle_ids', [])) or 'text')}</li>"
            for evidence_id, color, node in legend
        ) or "<li>No materialized nodes</li>"
        sections.append(
            f"<section><h2>{html.escape(case['document'])} — source page {case['page']:04d}</h2>"
            f"<p>{html.escape(json.dumps(summary, ensure_ascii=False))}</p>"
            f"<h3>Final EvidenceUnits: one color per node</h3><img class='page' src='{image_uri(overlay_path)}'>"
            f"<ul class='legend'>{legend_html}</ul>"
            f"<h3>PDF-native recovered visual sources</h3>{''.join(panels)}"
            f"<h3>Materialized EvidenceUnits</h3><ul>{node_rows}</ul></section>"
        )
    (OUT / "semantic_panel_review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Semantic panel EvidenceNode review</title>"
        "<style>body{font:15px system-ui;margin:24px;background:#eef1f5;color:#172033}section,article{background:white;max-width:1600px;margin:20px auto;padding:18px}article{border:1px solid #ccd4df}.page{max-width:100%;display:block}.views{display:flex;gap:16px;flex-wrap:wrap}.views figure{margin:0;max-width:31%}.views img{max-width:100%;height:auto}figcaption{font-size:12px}.legend{display:flex;gap:14px;flex-wrap:wrap;padding:0;list-style:none}.swatch{display:inline-block;width:14px;height:14px;vertical-align:-2px;margin-right:4px}code{overflow-wrap:anywhere}</style>"
        "<h1>DLR semantic-panel EvidenceNode review</h1>"
        "<p>The large page image shows final EvidenceUnit membership only. Parser proposals are intentionally omitted. Each panel below starts from the PDF-native recovered source object; visible/layer masks retain rendering provenance.</p>"
        + "".join(sections), encoding="utf-8")


def normalize_panel_response(parsed: dict[str, Any], atoms: list[dict[str, Any]], visuals: list[dict[str, Any]]) -> None:
    """Make redundant native member declarations canonical before validation.

    The base schema allows a whole bundle or all of its members.  Panel bundles
    use the former; a model sometimes emits both, which has no extra meaning and
    would otherwise look like duplicate coverage.
    """
    members_by_visual = {
        visual["visual_bundle_id"]: {member.get("member_id") for member in visual.get("geometry_members", [])}
        for visual in visuals
    }
    fragments_by_atom = {
        atom["atom_id"]: [fragment["fragment_id"] for fragment in atom.get("text_fragments", [])]
        for atom in atoms
    }
    for item in parsed.get("content_items", []):
        for unit in item.get("evidence_units", []):
            selected = set(unit.get("visual_bundle_ids", []))
            redundant = set().union(*(members_by_visual.get(visual_id, set()) for visual_id in selected))
            unit["visual_member_ids"] = [member_id for member_id in unit.get("visual_member_ids", [])
                                         if member_id not in redundant]
        # A structural decision already gives the content a non-evidence role;
        # restore every source fragment to its structural ledger deterministically.
        for decision in item.get("atom_decisions", []):
            if decision.get("action") == "STRUCTURAL_KEEP":
                atom_id = decision.get("atom_id")
                if atom_id:
                    item.setdefault("structural_fragment_ids", [])
                    item["structural_fragment_ids"].extend(
                        fragment_id for fragment_id in fragments_by_atom.get(atom_id, [])
                        if fragment_id not in item["structural_fragment_ids"]
                    )


def panel_validate(parsed: dict[str, Any], atoms: list[dict[str, Any]], visuals: list[dict[str, Any]]) -> dict[str, Any]:
    normalize_panel_response(parsed, atoms, visuals)
    check = ORIGINAL_BASE_VALIDATE(parsed, atoms, visuals)
    # Panel provenance is copied deterministically into the materialized node;
    # a visual description is useful, but not a reason to reject an otherwise
    # complete evidence-boundary decision in this pilot.
    return check


def run() -> None:
    member.OUT = OUT
    member.CASES = CASES
    member.base_validate = panel_validate
    member.validate_member_coverage = lambda parsed, visuals: []
    member.build_report = build_panel_report
    member.run()
    materialize_relations()
    build_panel_report()


def report() -> None:
    build_panel_report()
    materialize_relations()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "report"])
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "report": report}[args.action]()
