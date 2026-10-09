#!/usr/bin/env python3
"""Isolated Dolphin + PDF-native-member EvidenceNode pilot.

The semantic parent remains the Dolphin visual bundle.  Native PDF objects are
provided to the VLM as labelled, unoccluded source-object sheets and are copied
verbatim into every materialized EvidenceNode that owns the parent visual.
No production graph is read or written.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
sys.path.insert(0, str(ROOT / "EvidenceNet/scripts"))

from evidence_graph.llm_client import create_llm, extract_json
from run_evidence_unit_shadow_pilot import atom_rows, prompt as base_prompt, validate as base_validate

OUT = Path(os.environ.get(
    "MEMBER_ASSET_OUTPUT",
    ROOT / "EvidenceNet/output/member_asset_evidence_pipeline_v2",
)).resolve()
MODEL = Path(os.environ.get(
    "MEMBER_ASSET_MODEL",
    ROOT / "external/models/Qwen3.5-35B-A3B",
)).resolve()
OVERLAY_TEXT = ROOT / "parsing/audits/dolphin_visual_overlay_text_v1/recovered_overlay_text.jsonl"

CASES = [
    {
        "document": "DLRmagazine_176_EN", "page": 9,
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages/page_0009",
        "audit": ROOT / "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2",
    },
    {
        "document": "DLRmagazine_176_EN", "page": 17,
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages/page_0017",
        "audit": ROOT / "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2",
    },
    {
        "document": "gw150914_detection", "page": 2,
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/gw150914_page_0002",
        "audit": ROOT / "parsing/audits/multi_type_visual_adapter_v1/gw150914_detection_full",
    },
    {
        "document": "gw150914_detection", "page": 4,
        "dolphin": ROOT / "parsing/experiments/dolphin_v2_pilot/work/gw150914_page_0004",
        "audit": ROOT / "parsing/audits/multi_type_visual_adapter_v1/gw150914_detection_full",
    },
]


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def block_type(label: str) -> str:
    if label == "fig": return "image"
    if label == "tab": return "table"
    if label == "cap": return "caption"
    if label.startswith("sec_"): return "heading"
    if label in {"formula", "equation", "equ"}: return "formula"
    return "text"


def scale_box(box: list[float], source: list[int], target: tuple[int, int]) -> list[float]:
    return [round(box[i] * target[i % 2] / source[i % 2], 3) for i in range(4)]


def area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def overlap(a: list[float], b: list[float]) -> float:
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def envelope(boxes: list[list[float]]) -> list[float]:
    return [min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)]


def source_image(case: dict[str, Any], size: tuple[int, int]) -> Image.Image:
    page = case["page"]
    candidate = case["audit"] / f"page_{page:04d}" / "original.jpg"
    if not candidate.exists():
        raise FileNotFoundError(candidate)
    return Image.open(candidate).convert("RGB").resize(size, Image.Resampling.LANCZOS)


def source_member(asset: dict[str, Any], member: dict[str, Any], member_index: int,
                  size: tuple[int, int], audit: Path) -> dict[str, Any]:
    member_id = f"{asset['asset_id']}::M{member_index:03d}"
    raw_path = Path(member["asset_path"])
    alpha_path = Path(member["alpha_mask_path"]) if member.get("alpha_mask_path") else None
    return {
        "member_id": member_id,
        "asset_id": asset["asset_id"],
        "xref": member.get("xref"),
        "invocation_path": member.get("invocation_path"),
        "soft_mask": member.get("soft_mask"),
        "smask_xref": member.get("smask_xref"),
        "transform": member.get("transform"),
        "bbox": scale_box(member["rendered_bbox_pixels"], asset["image_size"], size),
        "bbox_source": "pdf_native_render_invocation",
        "source_object_path": str(raw_path),
        "source_alpha_mask_path": str(alpha_path) if alpha_path else None,
        "layer_mask_path": str(audit / asset["layer_mask"]) if asset.get("layer_mask") else None,
        "visible_mask_path": str(audit / asset["visible_mask"]) if asset.get("visible_mask") else None,
        "mask_canvas_size": asset.get("image_size"),
        "placement_consistent": asset.get("mask_placement_consistent"),
        "routing_decision": asset.get("decision"),
        "routing_reasons": asset.get("reasons", []),
        "information_policy": "retain verbatim under semantic parent; never replace by union bbox",
    }


def prepare_case(case: dict[str, Any]) -> dict[str, Any]:
    page = case["page"]
    page_id = f"page_{page:04d}"
    target = OUT / case["document"] / page_id
    summary = read(case["dolphin"] / "run_summary.json")
    size = tuple(summary["image_size"])
    output_json = case["dolphin"] / "output_json"
    element_path = next(output_json.glob("*.json"))
    elements = read(element_path)
    image = source_image(case, size)
    target.mkdir(parents=True, exist_ok=True)
    page_path = target / "original.png"
    image.save(page_path)

    blocks: list[dict[str, Any]] = []
    visuals: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        label = str(element.get("label") or "unknown")
        box = element.get("bbox")
        block_id = f"D{index:03d}"
        blocks.append({
            "block_id": block_id, "text": str(element.get("text") or ""),
            "block_type": block_type(label), "bbox": box,
            "geometry_members": ([{"member_id": f"{block_id}::G000", "bbox": box,
                                    "bbox_source": "dolphin_v2_element_bbox"}] if box else []),
            "role": label, "label": label,
            "deepseek_order": element.get("reading_order", index),
        })
        if label == "fig" and box:
            visual_id = f"V{index:03d}"
            visuals.append({
                "visual_bundle_id": visual_id,
                "bbox": box,
                "bbox_semantics": "Dolphin semantic visual envelope; not native union geometry",
                "layout_label": "figure", "provenance_state": "dolphin_semantic_parent",
                "source_block_ids": [block_id],
                "geometry_members": [{"member_id": f"{visual_id}::DOLPHIN", "bbox": box,
                                      "bbox_source": "dolphin_v2_complete_figure"}],
                "native_components": [],
            })

    # Dolphin may classify a photograph-backed magazine spread as one full-page
    # figure.  Preserve native PDF text drawn over that visual as independent
    # atoms instead of allowing the visual classification to erase it.
    overlay_rows = []
    if OVERLAY_TEXT.exists():
        overlay_rows = [row for row in jsonl(OVERLAY_TEXT)
                        if row.get("document_id") == case["document"].lower()
                        and row.get("page") == page_id]
    for overlay_index, row in enumerate(overlay_rows):
        block_id = f"PDFTEXT_{overlay_index:03d}"
        members = []
        for member_index, member in enumerate(row.get("geometry_members", []), 1):
            if member.get("bbox"):
                members.append({"member_id": f"{block_id}::G{member_index:03d}",
                                "bbox": member["bbox"],
                                "bbox_source": member.get("bbox_source") or "pdf_native_text_layer"})
        blocks.append({
            "block_id": block_id, "text": row.get("text", ""), "block_type": "text",
            "bbox": members[0]["bbox"] if len(members) == 1 else None,
            "geometry_members": members, "role": row.get("role_hint") or "overlay_text",
            "label": row.get("role_hint") or "overlay_text",
            "deepseek_order": len(elements) + overlay_index,
            "source_parser": "pdf_native_text_layer",
            "visual_parent": row.get("visual_parent"),
            "recovered_text_id": row.get("recovered_text_id"),
        })

    assets = [row for row in jsonl(case["audit"] / "visual_assets.jsonl") if row.get("source_page") == page]
    asset_ledger = []
    for asset in assets:
        components = [source_member(asset, member, i, size, case["audit"])
                      for i, member in enumerate(asset.get("render_layer_members", []), 1)]
        boxes = [component["bbox"] for component in components]
        if not boxes:
            asset_ledger.append({"asset_id": asset["asset_id"], "status": "NO_RENDER_MEMBERS"})
            continue
        asset_box = envelope(boxes)
        scores = []
        for visual in visuals:
            ov = overlap(asset_box, visual["bbox"])
            scores.append((ov / max(1.0, area(asset_box)), ov / max(1.0, area(visual["bbox"])), visual))
        best = max(scores, default=(0.0, 0.0, None), key=lambda row: (row[0], row[1]))
        if best[2] is None or (best[0] < 0.08 and best[1] < 0.02):
            visual_id = f"NATIVE_{len(visuals):03d}"
            owner = {
                "visual_bundle_id": visual_id, "bbox": asset_box,
                "bbox_semantics": "index envelope only; physical members below",
                "layout_label": "native_visual_asset", "provenance_state": "native_asset_without_dolphin_parent",
                "source_block_ids": [], "geometry_members": [], "native_components": [],
            }
            visuals.append(owner)
            state = "NATIVE_VISUAL_CREATED"
        else:
            owner = best[2]
            state = "ATTACHED_TO_DOLPHIN_VISUAL"
        owner["native_components"].extend(components)
        owner.setdefault("native_asset_groups", []).append({
            "asset_id": asset["asset_id"], "member_ids": [row["member_id"] for row in components],
            "xrefs": asset.get("xrefs", []), "decision": asset.get("decision"),
            "reasons": asset.get("reasons", []),
            "layer_mask_path": str(case["audit"] / asset["layer_mask"]) if asset.get("layer_mask") else None,
            "visible_mask_path": str(case["audit"] / asset["visible_mask"]) if asset.get("visible_mask") else None,
        })
        asset_ledger.append({"asset_id": asset["asset_id"], "status": state,
                             "visual_bundle_id": owner["visual_bundle_id"],
                             "member_ids": [row["member_id"] for row in components]})

    atoms = atom_rows({"aligned_blocks": blocks})
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    for atom in atoms:
        for member in atom["geometry_members"]:
            draw.rectangle(member["bbox"], outline="#22a35a", width=3)
            draw.text((member["bbox"][0], member["bbox"][1]), atom["atom_id"], fill="#116f3b",
                      stroke_width=1, stroke_fill="white")
    for visual in visuals:
        draw.rectangle(visual["bbox"], outline="#1866d5", width=4)
        draw.text((visual["bbox"][0], max(0, visual["bbox"][1] - 13)), visual["visual_bundle_id"],
                  fill="#1866d5", stroke_width=1, stroke_fill="white")
    annotated_path = target / "annotated_page.png"
    annotated.save(annotated_path)

    image_inputs = [{"kind": "annotated_page", "path": str(annotated_path),
                     "description": "full rendered page with Dolphin atom and visual IDs"}]
    for visual in visuals:
        sheets = make_component_sheets(visual, target / "component_sheets")
        visual["component_sheet_paths"] = [str(path) for path in sheets]
        for sheet_index, path in enumerate(sheets, 1):
            image_inputs.append({"kind": "recovered_source_component_sheet", "path": str(path),
                                 "visual_bundle_id": visual["visual_bundle_id"],
                                 "sheet_index": sheet_index,
                                 "member_ids": sheet_member_ids(path),
                                 "description": "unoccluded PDF source objects labelled by member_id"})

    request = member_prompt(case["document"], page_id, atoms, visuals, image_inputs)
    representation = {
        "document_id": case["document"], "page": page_id, "atoms": atoms,
        "visual_bundles": visuals, "asset_ledger": asset_ledger,
        "image_inputs": image_inputs, "annotated_page": str(annotated_path),
        "source_parser": "Dolphin-v2", "native_source": str(case["audit"] / "visual_assets.jsonl"),
        "overlay_text_source": str(OVERLAY_TEXT),
        "overlay_text_atoms": len(overlay_rows),
        "production_modified": False,
    }
    write(target / "input_representation.json", representation)
    (target / "prompt.txt").write_text(request, encoding="utf-8")
    return representation


def make_component_sheets(visual: dict[str, Any], output: Path, per_sheet: int = 12) -> list[Path]:
    components = visual.get("native_components", [])
    if not components:
        return []
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob(f"{visual['visual_bundle_id']}_sheet_*"):
        stale.unlink()
    # A PDF figure can be composed of dozens of render tiles. Keep every tile,
    # but bound the number and total pixels of contact-sheet inputs to the VLM.
    if len(components) > 24:
        per_sheet, cell_w, cell_h, label_h, cols = 36, 180, 130, 26, 6
    else:
        cell_w, cell_h, label_h, cols = 360, 250, 34, 3
    paths = []
    font = ImageFont.load_default()
    for sheet_no in range(math.ceil(len(components) / per_sheet)):
        subset = components[sheet_no * per_sheet:(sheet_no + 1) * per_sheet]
        rows = math.ceil(len(subset) / cols)
        canvas = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), "white")
        draw = ImageDraw.Draw(canvas)
        for index, component in enumerate(subset):
            x = (index % cols) * cell_w; y = (index // cols) * (cell_h + label_h)
            path = Path(component["source_object_path"])
            with Image.open(path) as source:
                rgba = source.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (238, 241, 246, 255))
                background.alpha_composite(rgba)
                tile = background.convert("RGB")
                tile.thumbnail((cell_w - 12, cell_h - 12), Image.Resampling.LANCZOS)
            ox = x + (cell_w - tile.width) // 2; oy = y + 6 + (cell_h - tile.height) // 2
            canvas.paste(tile, (ox, oy))
            draw.rectangle((x, y, x + cell_w - 1, y + cell_h + label_h - 1), outline="#9aa8ba", width=1)
            draw.text((x + 7, y + cell_h + 7), component["member_id"], fill="#172033", font=font)
        path = output / f"{visual['visual_bundle_id']}_sheet_{sheet_no + 1:02d}.png"
        canvas.save(path)
        (path.with_suffix(".members.json")).write_text(
            json.dumps([row["member_id"] for row in subset], ensure_ascii=False), encoding="utf-8")
        paths.append(path)
    return paths


def sheet_member_ids(path: Path) -> list[str]:
    return json.loads(path.with_suffix(".members.json").read_text(encoding="utf-8"))


def member_prompt(document: str, page: str, atoms: list[dict[str, Any]],
                  visuals: list[dict[str, Any]], image_inputs: list[dict[str, Any]]) -> str:
    base = base_prompt(document, page, atoms, visuals, [row["description"] for row in image_inputs])
    base = base.replace(
        '"visual_summary": "empty for TEXT; visibly grounded summary for visual units", "reason": "short assembly rationale"',
        '"visual_summary": "empty for TEXT; visibly grounded summary for visual units", '
        '"visual_description": {"visible_page_observation": "directly visible content", '
        '"recovered_source_observation": "content visible in unoccluded PDF source objects", '
        '"caption_or_context_interpretation": "grounded interpretation or null", '
        '"discrepancy": "difference between rendered page and source objects or null", '
        '"uncertainty": "short uncertainty or null"}, '
        '"component_groups": [{"member_ids": ["every native member exactly once"], '
        '"direct_observation": "grounded description", '
        '"relationship_to_parent": "technical_tile|foreground|background|panel|other", '
        '"uncertainty": "short uncertainty or null"}], '
        '"reason": "short assembly rationale"'
    )
    contract = """

ADDITIONAL NATIVE-ASSET DESCRIPTION CONTRACT:
- After the annotated page, the supplied images are labelled contact sheets of original PDF source objects.
- These source objects are unoccluded payloads. Use them to recover content hidden by later page painting, but distinguish
  recovered-source observation from what is visible on the rendered page.
- native_components are technical provenance members of a semantic visual parent. Do not create one EvidenceUnit per
  PDF tile and do not infer that technical fragmentation means semantic independence.
- A native-backed visual must be selected as its whole visual_bundle_id or retained as structural. Do not select its
  visual_member_ids individually: the source-object members are provenance, not semantic subfigures.
- For every VISUAL or COMPOSITE EvidenceUnit add visual_description with exactly these keys:
  visible_page_observation, recovered_source_observation, caption_or_context_interpretation, discrepancy, uncertainty.
- Also add component_groups, a list of objects with member_ids, direct_observation, relationship_to_parent, uncertainty.
  Every native component belonging to a selected visual bundle must occur exactly once across component_groups.
  Several technical tiles may share one component group, but no member may be omitted.
- The pipeline will copy the complete native component ledger into the node independently of the model response.

IMAGE INPUT MAP:
""" + json.dumps(image_inputs, ensure_ascii=False, indent=2)
    return base + contract


def validate_member_coverage(parsed: dict[str, Any], visuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_visual = {row["visual_bundle_id"]: row for row in visuals}
    native_geometry_members = {
        member["member_id"]
        for visual in visuals if visual.get("native_components")
        for member in visual.get("geometry_members", [])
    }
    errors = []
    for item in parsed.get("content_items", []):
        for unit in item.get("evidence_units", []):
            selected = unit.get("visual_bundle_ids", [])
            expected = {component["member_id"] for visual_id in selected
                        for component in by_visual.get(visual_id, {}).get("native_components", [])}
            groups = unit.get("component_groups", [])
            observed = [member_id for group in groups for member_id in group.get("member_ids", [])]
            if Counter(observed) != Counter(expected):
                errors.append({"type": "native_component_description_coverage",
                               "unit": unit.get("evidence_unit_id"),
                               "missing": sorted(expected - set(observed)),
                               "unknown": sorted(set(observed) - expected),
                               "duplicates": sorted(key for key, count in Counter(observed).items() if count > 1)})
            if selected and not isinstance(unit.get("visual_description"), dict):
                errors.append({"type": "missing_visual_description", "unit": unit.get("evidence_unit_id")})
            illegal = sorted(set(unit.get("visual_member_ids", [])) & native_geometry_members)
            if illegal:
                errors.append({"type": "native_backed_visual_must_use_whole_bundle",
                               "unit": unit.get("evidence_unit_id"), "visual_member_ids": illegal})
    return errors


def materialize(representation: dict[str, Any], parsed: dict[str, Any], valid: bool) -> list[dict[str, Any]]:
    atoms = {row["atom_id"]: row for row in representation["atoms"]}
    fragments = {fragment["fragment_id"]: (fragment, atom)
                 for atom in representation["atoms"] for fragment in atom["text_fragments"]}
    visuals = {row["visual_bundle_id"]: row for row in representation["visual_bundles"]}
    result = []
    for item in parsed.get("content_items", []):
        for unit in item.get("evidence_units", []):
            selected_fragments = [fragments[key] for key in unit.get("text_fragment_ids", []) if key in fragments]
            selected_visuals = [visuals[key] for key in unit.get("visual_bundle_ids", []) if key in visuals]
            text = "\n".join(fragment["text"] for fragment, _ in selected_fragments).strip()
            geometry = [dict(member, source_atom_id=atom["atom_id"])
                        for _, atom in selected_fragments for member in atom.get("geometry_members", [])]
            for visual in selected_visuals:
                geometry.extend(dict(member, source_visual_bundle_id=visual["visual_bundle_id"])
                                for member in visual.get("geometry_members", []))
            components = [dict(component, semantic_parent_visual_id=visual["visual_bundle_id"])
                          for visual in selected_visuals for component in visual.get("native_components", [])]
            result.append({
                "node_id": f"{representation['document_id']}_{representation['page']}_{item.get('content_item_id')}_{unit.get('evidence_unit_id')}",
                "node_type": "evidence", "status": "VALIDATED_SHADOW_EVIDENCE" if valid else "UNVALIDATED_CANDIDATE",
                "document_id": representation["document_id"], "page": representation["page"],
                "content_item_id": item.get("content_item_id"), "unit_type": unit.get("unit_type"),
                "plain_text": text, "visual_description": unit.get("visual_description"),
                "component_groups": unit.get("component_groups", []),
                "geometry_members": geometry,
                "native_visual_components": components,
                "native_asset_groups": [group for visual in selected_visuals for group in visual.get("native_asset_groups", [])],
                "source_atom_ids": sorted({atom["atom_id"] for _, atom in selected_fragments}),
                "source_visual_bundle_ids": [row["visual_bundle_id"] for row in selected_visuals],
                "provenance_policy": "all native members retained verbatim; semantic parent remains Dolphin visual",
                "production_modified": False,
            })
    return result


def retained_non_evidence_components(representation: dict[str, Any], parsed: dict[str, Any],
                                     nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a lossless sidecar for native members assigned to structural/non-evidence visuals."""
    preserved = {component["member_id"] for node in nodes for component in node["native_visual_components"]}
    disposition: dict[str, str] = {}
    for visual_id in parsed.get("page_structure_visual_bundle_ids", []):
        disposition[visual_id] = "PAGE_STRUCTURE"
    for item in parsed.get("content_items", []):
        for visual_id in item.get("structural_visual_bundle_ids", []):
            disposition[visual_id] = "CONTENT_ITEM_STRUCTURE"
    rows = []
    for visual in representation["visual_bundles"]:
        for component in visual.get("native_components", []):
            if component["member_id"] not in preserved:
                rows.append({
                    **component,
                    "semantic_parent_visual_id": visual["visual_bundle_id"],
                    "disposition": disposition.get(visual["visual_bundle_id"], "UNRESOLVED_RETAIN"),
                    "reason": "not materialized as an EvidenceNode, retained losslessly in structural sidecar",
                })
    return rows


def run() -> None:
    manifest = read(OUT / "manifest.json")
    llm = create_llm({"provider": "transformers", "model": manifest["model"], "dtype": "bfloat16",
                      "device_map": "auto", "require_cuda": True, "enable_thinking": False})
    summaries = []
    for task in manifest["tasks"]:
        target = OUT / task
        representation = read(target / "input_representation.json")
        if (target / "validation.json").exists() and read(target / "validation.json").get("valid"):
            summaries.append(read(target / "run_summary.json")); continue
        image_paths = [row["path"] for row in representation["image_inputs"]]
        request = (target / "prompt.txt").read_text(encoding="utf-8")
        parsed = None; check = None; errors = []
        first_attempt = len(list(target.glob("raw_response_*.txt"))) + 1
        for retry in range(2):
            attempt = first_attempt + retry
            try:
                generation = llm.generate_raw_with_images(
                    "Conservative multimodal EvidenceNode assembler. JSON only.", request, image_paths, 8000)
                (target / f"raw_response_{attempt}.txt").write_text(generation.raw, encoding="utf-8")
                candidate = extract_json(generation.raw)
                if not isinstance(candidate, dict): raise ValueError("top-level response is not an object")
                candidate_check = base_validate(
                    candidate, representation["atoms"], representation["visual_bundles"])
                candidate_check["errors"].extend(
                    validate_member_coverage(candidate, representation["visual_bundles"]))
                candidate_check["valid"] = not candidate_check["errors"]
                parsed, check = candidate, candidate_check
                write(target / f"validation_attempt_{attempt}.json", candidate_check)
                if candidate_check["valid"]:
                    break
                if retry == 0:
                    request += (
                        "\n\nCORRECTION REQUIRED. Your previous JSON failed deterministic coverage validation. "
                        "Return a complete replacement JSON object, not a patch. Preserve every atom, fragment, "
                        "visual and native member exactly once. Validator errors:\n" +
                        json.dumps(candidate_check["errors"], ensure_ascii=False, indent=2)
                    )
            except Exception as exc:
                errors.append(str(exc))
        if parsed is None:
            summary = {"document": representation["document_id"], "page": representation["page"],
                       "status": "generation_failed", "errors": errors, "production_modified": False}
            write(target / "run_summary.json", summary); summaries.append(summary); continue
        assert check is not None
        nodes = materialize(representation, parsed, check["valid"])
        retained = retained_non_evidence_components(representation, parsed, nodes)
        write(target / "assembly.json", parsed); write(target / "validation.json", check)
        write_jsonl(target / "evidence_nodes.jsonl", nodes)
        write_jsonl(target / "retained_non_evidence_components.jsonl", retained)
        input_components = sum(len(row.get("native_components", [])) for row in representation["visual_bundles"])
        node_components = sum(len(row["native_visual_components"]) for row in nodes)
        summary = {
            "document": representation["document_id"], "page": representation["page"],
            "status": "complete", "valid": check["valid"], "evidence_nodes": len(nodes),
            "visual_nodes": sum(bool(row["source_visual_bundle_ids"]) for row in nodes),
            "native_components_preserved_in_nodes": node_components,
            "native_components_retained_outside_nodes": len(retained),
            "input_native_components": input_components,
            "native_component_loss": input_components - node_components - len(retained),
            "production_modified": False,
        }
        write(target / "run_summary.json", summary); summaries.append(summary)
        write(OUT / "progress.json", {"pages": summaries, "production_modified": False})
    write(OUT / "summary.json", {"pages": summaries, "production_modified": False})
    build_report()


def data_uri(path: Path) -> str:
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def build_report() -> None:
    sections = []
    for case in CASES:
        target = OUT / case["document"] / f"page_{case['page']:04d}"
        if not (target / "input_representation.json").exists(): continue
        representation = read(target / "input_representation.json")
        summary = read(target / "run_summary.json") if (target / "run_summary.json").exists() else {"status": "prepared"}
        nodes = jsonl(target / "evidence_nodes.jsonl") if (target / "evidence_nodes.jsonl").exists() else []
        sheets = [Path(row["path"]) for row in representation["image_inputs"] if row["kind"] == "recovered_source_component_sheet"]
        sheet_html = "".join(f"<figure><img src='{data_uri(path)}'><figcaption>{html.escape(path.name)}</figcaption></figure>" for path in sheets)
        node_html = "".join("<details><summary>" + html.escape(row["node_id"]) +
                            f" — {len(row['native_visual_components'])} native members</summary><pre>" +
                            html.escape(json.dumps(row, ensure_ascii=False, indent=2)) + "</pre></details>" for row in nodes)
        sections.append(f"<section><h2>{html.escape(case['document'])} — page {case['page']:04d}</h2>"
                        f"<p>{html.escape(json.dumps(summary, ensure_ascii=False))}</p>"
                        f"<img class='page' src='{data_uri(target/'annotated_page.png')}'><div class='sheets'>{sheet_html}</div>{node_html}</section>")
    (OUT / "member_asset_evidence_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Member-aware EvidenceNode pilot</title>"
        "<style>body{font:14px system-ui;background:#edf1f6;margin:20px;color:#172033}section{background:white;max-width:1500px;margin:20px auto;padding:18px}.page{max-width:55%;vertical-align:top}.sheets{display:inline-grid;width:43%;grid-template-columns:1fr;gap:10px;margin-left:1%}.sheets img{width:100%}figure{margin:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:700px;overflow:auto}details{border-top:1px solid #ccd4df;padding:9px}</style>"
        "<h1>Recovered PDF source assets → member-aware EvidenceNodes</h1>"
        "<p>Dolphin supplies semantic parents. Contact sheets contain unoccluded PDF source objects. Every native component is retained in the materialized node ledger.</p>" + "".join(sections), encoding="utf-8")


def prepare() -> None:
    tasks = []
    for case in CASES:
        prepare_case(case)
        tasks.append(f"{case['document']}/page_{case['page']:04d}")
    write(OUT / "manifest.json", {
        "tasks": tasks, "model": str(MODEL), "production_modified": False,
        "policy": "Dolphin semantic parent + unoccluded PDF source-object sheets + complete member ledger",
    })
    build_report()
    print(json.dumps({"tasks": len(tasks), "output": str(OUT), "production_modified": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "report"])
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "report": build_report}[args.action]()
