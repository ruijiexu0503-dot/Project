#!/usr/bin/env python3
"""Shadow pilot for evidence nodes made of addressable multimodal components.

It consumes frozen page representations.  Qwen proposes only *composite*
information units; every other source component is materialised as a singleton.
Thus a failed model response cannot silently discard text or visual provenance.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
sys.path.insert(0, str(ROOT / "EvidenceNet/scripts"))
from evidence_graph.llm_client import create_llm, extract_json

import run_flow_first_evidence_pilot as base

SOURCE = ROOT / "EvidenceNet/output/bounded_composite_v4_geometry"
OUT = ROOT / "EvidenceNet/output/multimodal_information_unit_pilot_v1"
MODEL = ROOT / "external/models/Qwen3.5-35B-A3B"
CASES = [("DLRmagazine_176_EN", "page_0012"), ("gw150914_detection_dolphin", "page_0002")]
ALLOWED_RELATIONS = {"CAPTION_OF", "DIRECT_EXPLANATION", "MEASURES", "DEPICTS", "SUPPORTS"}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def source_image(document: str, page: str) -> Path:
    if document == "DLRmagazine_176_EN":
        return ROOT / "EvidenceNet/output/composite_evidence_pilot_v3_recomposed_components" / document / page / "original.png"
    return ROOT / "EvidenceNet/output/dolphin_paper_node_pipeline_v1/prepared/raw" / document / page / "page.png"


def make_components(rep, assembly, presentations):
    fragments = base.fragments(rep)
    visual_by_id = {row["visual_bundle_id"]: row for row in rep["visual_bundles"]}
    images = {row["panel_id"]: row.get("image") for row in presentations}
    components = []
    for unit in assembly["evidence_units"]:
        if unit.get("fragment_ids"):
            ids = unit["fragment_ids"]
            components.append({"component_id": "T_" + unit["evidence_unit_id"], "modality": "text",
                               "role_hint": "caption" if unit["evidence_unit_id"] in {"EU_014", "EU_004"} else "prose",
                               "text": "\n".join(fragments[f]["text"] for f in ids),
                               "source_fragment_ids": ids,
                               "geometry_members": [dict(g, source_atom_id=fragments[f]["atom"]["atom_id"])
                                                    for f in ids for g in fragments[f]["atom"].get("geometry_members", [])]})
        for visual_id in unit.get("visual_panel_ids", []):
            # A visual can already have been composited by the old bounded branch.  It remains
            # an independently addressable source component in this experiment.
            visual = visual_by_id[visual_id]
            components.append({"component_id": "V_" + visual_id, "modality": "image", "role_hint": "figure_or_image",
                               "source_visual_panel_ids": [visual_id], "image": images.get(visual_id),
                               # Keep the extracted PDF object distinct from the page-visible
                               # presentation.  The former can be uncropped or extend outside
                               # the page; the latter shows how it appeared in the document.
                               "original_assets": [{k: member.get(k) for k in ("member_id", "asset_id", "source_object_path", "source_alpha_mask_path")}
                                                   for member in visual.get("native_components", [])],
                               "geometry_members": [dict(g, source_visual_panel_id=visual_id)
                                                    for g in visual.get("geometry_members", [])]})
    seen = set(); result = []
    for component in components:
        if component["component_id"] not in seen:
            result.append(component); seen.add(component["component_id"])
    return result


def prompt(components):
    listing = []
    for row in components:
        item = {k: row[k] for k in ("component_id", "modality", "role_hint")}
        if row["modality"] == "text": item["text"] = row["text"]
        listing.append(item)
    schema = {"groups": [{"component_ids": ["T_EU_004", "V_example"],
                           "claim": "brief conservative statement based only on group components",
                           "internal_relations": [{"source_component": "T_EU_004", "target_component": "V_example",
                                                   "relation": "CAPTION_OF", "anchor": "exact source text substring"}],
                           "status": "CONFIRMED|NEEDS_REVIEW", "basis": "what on the source page supports grouping"}]}
    return """You assemble citable multimodal information units from one page. Return JSON only.

Each input item is an immutable source component. Every supplied visual image has its exact component ID burned into a black banner at the top. Use that visible ID, not image order, when returning a visual component ID. Propose a group ONLY when its components together provide one independently citable observation, measurement, explanation, or figure statement. A group may contain several images with one caption.

Rules:
1. Do not group by topic, proximity, or a shared article alone. A text component must explicitly describe, caption, measure, or explain the image(s).
2. Use only component IDs provided. Do not place a component in more than one proposed group.
3. Every group must have at least two modalities, including one image and one text/table/formula component.
4. Every relation must run between members of that group. `anchor` must be an exact nonempty substring of the listed text component. Allowed relations are CAPTION_OF, DIRECT_EXPLANATION, MEASURES, DEPICTS, SUPPORTS.
5. `claim` is a short conservative paraphrase; never add facts that cannot be seen or read in the group.
6. If association is uncertain, omit the group. Components omitted from groups will remain standalone evidence with their provenance intact.

Return exactly this schema:\n""" + json.dumps(schema, ensure_ascii=False) + "\n\nSOURCE COMPONENTS:\n" + json.dumps(listing, ensure_ascii=False)


def validate_groups(raw, components):
    errors = []; known = {row["component_id"]: row for row in components}; accepted = []; used = set()
    if not isinstance(raw, dict) or not isinstance(raw.get("groups"), list):
        return [], [{"type": "schema", "detail": "groups must be a list"}]
    for index, group in enumerate(raw["groups"], 1):
        ids = group.get("component_ids", [])
        relations = group.get("internal_relations", [])
        bad = not isinstance(ids, list) or len(ids) < 2 or len(set(ids)) != len(ids) or any(i not in known for i in ids)
        modalities = {known[i]["modality"] for i in ids if i in known}
        bad = bad or not ({"image", "text"} <= modalities) or bool(set(ids) & used)
        if not isinstance(group.get("claim"), str) or not group["claim"].strip() or not isinstance(group.get("basis"), str) or not group["basis"].strip(): bad = True
        for relation in relations:
            source, target = relation.get("source_component"), relation.get("target_component")
            anchor = relation.get("anchor")
            if source not in ids or target not in ids or source == target or relation.get("relation") not in ALLOWED_RELATIONS:
                bad = True; continue
            # OCR/text extraction often introduces line breaks inside a quoted sentence.
            # Permit only whitespace normalization: all non-whitespace characters must
            # still occur verbatim in the cited source component.
            normalized_anchor = re.sub(r"\s+", " ", anchor).strip() if isinstance(anchor, str) else ""
            normalized_text = re.sub(r"\s+", " ", known[source].get("text", "")).strip()
            if known[source]["modality"] != "text" or not normalized_anchor or normalized_anchor not in normalized_text:
                bad = True
            elif anchor not in known[source]["text"]:
                relation["anchor_match"] = "WHITESPACE_NORMALIZED"
        if not relations: bad = True
        if bad: errors.append({"type": "invalid_group", "index": index, "component_ids": ids})
        else:
            accepted.append({**group, "group_id": f"MMU_{len(accepted)+1:03d}"}); used.update(ids)
    return accepted, errors


def materialize(rep, components, groups):
    grouped = {cid: group for group in groups for cid in group["component_ids"]}
    nodes = []
    for group in groups:
        members = [next(c for c in components if c["component_id"] == cid) for cid in group["component_ids"]]
        nodes.append(make_node(rep, group["group_id"], members, group.get("claim"), group["status"], group["basis"], group["internal_relations"]))
    for component in components:
        if component["component_id"] not in grouped:
            nodes.append(make_node(rep, "ATOM_" + component["component_id"], [component], None, "UNASSOCIATED_SOURCE_COMPONENT",
                                   "No directly grounded multimodal group was accepted.", []))
    return nodes


def make_node(rep, local_id, members, claim, status, basis, relations):
    modalities = sorted({row["modality"] for row in members})
    text = "\n".join(row.get("text", "") for row in members if row["modality"] == "text")
    geometry = [g for row in members for g in row.get("geometry_members", [])]
    return {"node_id": f"{rep['document_id']}_{rep['page']}_{local_id}", "node_type": "evidence", "document_id": rep["document_id"], "page": rep["page"],
            "unit_type": "COMPOSITE" if len(modalities) > 1 else ("TEXT" if modalities == ["text"] else "VISUAL"), "modalities": modalities,
            "components": [{k: v for k, v in row.items() if k in {"component_id", "modality", "role_hint", "text", "source_fragment_ids", "source_visual_panel_ids", "image", "original_assets", "geometry_members"}}
                           for row in members], "plain_text": text, "claim": claim, "internal_relations": relations, "association_basis": basis,
            "status": status, "geometry_members": geometry, "retrieval_eligible": False, "production_modified": False}


def overlay(page_image, nodes, output):
    colors = ["#d7263d", "#0072b2", "#009e73", "#e69f00", "#cc79a7", "#6a3d9a"]
    with Image.open(page_image) as raw:
        image = raw.convert("RGB")
    draw = ImageDraw.Draw(image)
    for i, node in enumerate(nodes):
        if node["unit_type"] != "COMPOSITE": continue
        color = colors[i % len(colors)]
        for geo in node["geometry_members"]:
            if geo.get("bbox"):
                draw.rectangle(tuple(map(int, geo["bbox"])), outline=color, width=5)
                draw.text((int(geo["bbox"][0])+3, int(geo["bbox"][1])+3), node["node_id"].rsplit("_", 1)[-1], fill=color, stroke_width=1, stroke_fill="white")
    image.save(output)


def data_uri(path):
    if not path or not Path(path).exists(): return ""
    mime = "image/jpeg" if Path(path).suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def labelled_visual_inputs(components, target):
    """Make the model's visual identity channel explicit rather than positional."""
    paths = []
    for component in components:
        if component["modality"] != "image":
            continue
        asset = next((row.get("source_object_path") for row in component.get("original_assets", []) if row.get("source_object_path")), None)
        source = Path(asset or component.get("image", ""))
        if not source.exists():
            continue
        with Image.open(source) as raw:
            image = raw.convert("RGB")
        banner = 54
        labeled = Image.new("RGB", (image.width, image.height + banner), "black")
        labeled.paste(image, (0, banner))
        draw = ImageDraw.Draw(labeled)
        draw.text((12, 14), component["component_id"], fill="white", font=ImageFont.load_default(), stroke_width=1, stroke_fill="black")
        path = target / "model_visual_inputs" / f"{component['component_id']}.png"
        path.parent.mkdir(parents=True, exist_ok=True); labeled.save(path)
        paths.append(str(path))
    return paths


def final_page_render_crops(components, page_image, target):
    """Crop the final rendered PDF page, never a re-render of the extracted asset."""
    with Image.open(page_image) as raw:
        page = raw.convert("RGB")
    for component in components:
        if component["modality"] != "image":
            continue
        boxes = [member.get("bbox") for member in component.get("geometry_members", []) if member.get("bbox")]
        if not boxes:
            continue
        left = max(0, int(min(box[0] for box in boxes)) - 12)
        top = max(0, int(min(box[1] for box in boxes)) - 12)
        right = min(page.width, int(max(box[2] for box in boxes)) + 12)
        bottom = min(page.height, int(max(box[3] for box in boxes)) + 12)
        if right <= left or bottom <= top:
            continue
        path = target / "final_page_render_crops" / f"{component['component_id']}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        page.crop((left, top, right, bottom)).save(path)
        component["final_page_render_crop"] = str(path)


def render(case_dir, nodes, page_image):
    overlay_path = case_dir / "composite_membership_overlay.png"; overlay(page_image, nodes, overlay_path)
    cards = []
    for node in nodes:
        pieces = []
        for component in node["components"]:
            if component["modality"] == "text":
                pieces.append(f"<article><code>{html.escape(component['component_id'])}</code><p>{html.escape(component['text'])}</p></article>")
            else:
                originals = "".join(f"<figure><img src='{data_uri(asset.get('source_object_path'))}'><figcaption>Original PDF asset · {html.escape(asset.get('member_id', 'unknown'))}</figcaption></figure>"
                                    for asset in component.get("original_assets", []) if data_uri(asset.get("source_object_path")))
                final_render = data_uri(component.get("final_page_render_crop"))
                page_view = f"<figure><img src='{final_render}'><figcaption>Final PDF page render, cropped at this component's recorded page bbox</figcaption></figure>" if final_render else ""
                pieces.append(f"<article><code>{html.escape(component['component_id'])}</code><p>Visual source component</p><div class='assets'>{originals or '<p>Original extracted asset unavailable for this parser route.</p>'}{page_view}</div></article>")
        rel = "".join(f"<li>{html.escape(r['relation'])}: {html.escape(r['source_component'])} → {html.escape(r['target_component'])}; anchor: {html.escape(r['anchor'])}</li>" for r in node["internal_relations"])
        kind = "Composite multimodal evidence node" if node["unit_type"] == "COMPOSITE" else "Standalone source-component evidence node"
        cards.append(f"<section class='{html.escape(node['unit_type'].lower())}'><h2>{html.escape(node['node_id'].rsplit('_',1)[-1])}</h2><p><b>{html.escape(kind)}</b> · <b>{html.escape(node['status'])}</b> · {html.escape(node.get('claim') or '')}</p><p>{html.escape(node['association_basis'])}</p><div class='components'>{''.join(pieces)}</div>{'<ul>'+rel+'</ul>' if rel else ''}</section>")
    doc = f"""<!doctype html><meta charset='utf-8'><style>body{{font:15px system-ui;background:#edf1f4;color:#16212d;margin:24px}}main{{max-width:1400px;margin:auto}}section{{background:#fff;border-left:5px solid #7b8794;padding:18px;margin:16px 0}}section.composite{{border-color:#0072b2}}img{{max-width:100%;max-height:500px;object-fit:contain}}.components,.assets{{display:flex;gap:18px;flex-wrap:wrap}}article,figure{{max-width:46%;margin:10px 0}}article p{{white-space:pre-wrap;line-height:1.45}}code{{overflow-wrap:anywhere}}.overlay{{width:100%;max-height:none}}</style><main><h1>Multimodal information-unit pilot</h1><p>Every source component has its own node card below. Colored boxes show components in accepted composite evidence nodes; they are separate components, not one merged page box. Visual cards show the extracted PDF source asset alongside a crop from the final rendered PDF page, so text overlays and final compositing remain visible.</p><img class='overlay' src='{data_uri(overlay_path)}'><h2>All evidence nodes</h2>{''.join(cards)}</main>"""
    (case_dir / "report.html").write_text(doc, encoding="utf-8")


def run(local_check=False, output_root=OUT, reuse_model_responses=False, cpu=False):
    llm = None if local_check else create_llm({"provider": "transformers", "model": str(MODEL), "dtype": "bfloat16",
                                               "device_map": "cpu" if cpu else "auto", "require_cuda": not cpu, "enable_thinking": False})
    summaries = []
    for document, page in CASES:
        source = SOURCE / document / page; target = output_root / document / page; target.mkdir(parents=True, exist_ok=True)
        rep, assembly, presentations = read(source / "input_representation.json"), read(source / "assembly.json"), read(source / "visual_presentations.json")
        components = make_components(rep, assembly, presentations); image = source_image(document, page)
        final_page_render_crops(components, image, target)
        raw = {"groups": []}; model_error = None
        cached_response = target / "model_response.json"
        if reuse_model_responses and cached_response.exists():
            raw = read(cached_response)
        elif llm:
            try:
                visual_inputs = labelled_visual_inputs(components, target)
                raw = extract_json(llm.generate_raw_with_images("Conservative multimodal evidence assembler. JSON only.", prompt(components), [str(image)] + visual_inputs, 3500).raw)
            except Exception as exc: model_error = str(exc)
        groups, errors = validate_groups(raw, components)
        nodes = materialize(rep, components, groups)
        coverage = sorted(c["component_id"] for n in nodes for c in n["components"]) == sorted(c["component_id"] for c in components)
        # Invalid proposals are audit findings.  They are excluded from the graph, so
        # they do not make the materialised fallback graph structurally invalid.
        validation = {"valid": coverage, "rejected_model_proposals": errors, "component_count": len(components), "component_coverage": coverage, "composite_count": len(groups)}
        write(target / "input_components.json", components); write(target / "model_response.json", raw); write(target / "validation.json", validation); jsonl(target / "evidence_nodes.jsonl", nodes)
        shutil.copy2(image, target / "original.png"); render(target, nodes, image)
        summary = {"document_id": document, "page": page, "components": len(components), "composites": len(groups), "validation": validation, "model_error": model_error, "production_modified": False}
        write(target / "summary.json", summary); summaries.append(summary)
    write(output_root / "summary.json", summaries); print(json.dumps(summaries, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--local-check", action="store_true"); parser.add_argument("--reuse-model-responses", action="store_true"); parser.add_argument("--cpu", action="store_true"); parser.add_argument("--output-root", type=Path, default=OUT)
    args = parser.parse_args(); run(args.local_check, args.output_root, args.reuse_model_responses, args.cpu)
