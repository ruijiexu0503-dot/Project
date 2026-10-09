#!/usr/bin/env python3
"""Shadow-only content-item and EvidenceUnit assembly over selected pages."""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from evidence_graph.config import load_config
from evidence_graph.continuation_detector import completeness
from evidence_graph.llm_client import create_llm, extract_json


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def bbox(value):
    return value if isinstance(value, list) and len(value) == 4 else None


def geometry(block):
    result = []
    for member in block.get("geometry_members") or []:
        box = bbox(member.get("bbox") or member.get("pixel_bbox"))
        if box:
            result.append({"member_id": member.get("member_id"), "bbox": box})
    direct = bbox(block.get("bbox") or block.get("deepseek_bbox"))
    if not result and direct:
        result.append({"member_id": None, "bbox": direct})
    return result


def text_fragments(block_id, text, atom_type):
    """Split long prose at explicit paragraph/sentence boundaries with exact source spans."""
    if not text:
        return []
    stripped=text.strip()
    formula_like=(stripped.startswith(("\\[", "$$", "\\begin"))
                  or (len(stripped)>200 and stripped.count("\\")/max(1,len(stripped))>.035))
    indivisible=str(atom_type or "").lower() in {"heading","caption","table","formula","equation"} or formula_like
    spans=[]
    paragraphs=list(re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)",text,re.S))
    for paragraph in paragraphs:
        start,end=paragraph.span(); value=paragraph.group(0)
        if indivisible or len(value)<=350:
            spans.append((start,end)); continue
        boundaries=[]
        for match in re.finditer(r"\s+",value):
            left=value[:match.start()].rstrip(); right=value[match.end():].lstrip()
            if left and right and left[-1] in ".!?" and right[0] in '"\'“‘([ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
                boundaries.append(match.end())
        if not boundaries:
            spans.append((start,end)); continue
        local_start=0
        for boundary in boundaries+[len(value)]:
            segment=value[local_start:boundary]
            left_trim=len(segment)-len(segment.lstrip()); right_trim=len(segment.rstrip())
            seg_start=start+local_start+left_trim; seg_end=start+local_start+right_trim
            if seg_end>seg_start: spans.append((seg_start,seg_end))
            local_start=boundary
    return [{"fragment_id":f"{block_id}::F{index:03d}","source_atom_id":block_id,
             "char_start":start,"char_end":end,"text":text[start:end],
             "oversized_unsplit":end-start>1600}
            for index,(start,end) in enumerate(spans,1)]


def load_provenance(path: Path):
    return {(row["document_id"], row["page"]): row for row in read_jsonl(path)}


def visual_rows(row):
    result = []
    for bundle in row.get("bundles", []):
        result.append({
            "visual_bundle_id": bundle["bundle_id"],
            "bbox": bundle.get("bbox"),
            "provenance_state": bundle.get("provenance_state"),
            "layout_label": (bundle.get("layout_region") or {}).get("label"),
            "geometry_members": [
                {"member_id": member.get("member_id"), "bbox": member.get("bbox"),
                 "bbox_source": member.get("bbox_source")}
                for member in bundle.get("geometry_members", [])
            ],
        })
    return result


def atom_rows(payload):
    rows = []
    for block in payload.get("aligned_blocks", []):
        if str(block.get("block_type") or "").lower() == "image":
            continue
        text=str(block.get("text") or "")
        complete,possible,continuation_reason=completeness(text.strip())
        starts_lowercase=bool(text.strip() and text.strip()[0].islower())
        rows.append({
            "atom_id": block.get("block_id"),
            "atom_type": block.get("block_type") or "text",
            "text_preview": text[:500],
            "text_length": len(text),
            "text_fragments": text_fragments(block.get("block_id"),text,block.get("block_type")),
            "weak_fragmentation_hints": {
                "starts_lowercase": starts_lowercase,
                "possible_continuation": bool(possible or not complete),
                "continuation_reason": continuation_reason,
                "warning": "weak cues only; length never determines attachment"
            },
            "geometry_members": geometry(block),
            "layout_role": block.get("role") or block.get("label"),
            "deepseek_order": block.get("deepseek_order"),
        })
    # Document layouts have very different font sizes and block granularity.  Expose ranks rather
    # than using an absolute character/area cutoff, and keep them as weak diagnostics only.
    lengths=sorted(row["text_length"] for row in rows if row["text_length"])
    areas=sorted(sum(max(0,g["bbox"][2]-g["bbox"][0])*max(0,g["bbox"][3]-g["bbox"][1])
                     for g in row["geometry_members"]) for row in rows if row["geometry_members"])
    for row in rows:
        length=row["text_length"]
        area=sum(max(0,g["bbox"][2]-g["bbox"][0])*max(0,g["bbox"][3]-g["bbox"][1])
                 for g in row["geometry_members"])
        row["weak_fragmentation_hints"]["page_relative_text_length_percentile"]=(
            round(sum(value<=length for value in lengths)/len(lengths),3) if lengths else None)
        row["weak_fragmentation_hints"]["page_relative_geometry_area_percentile"]=(
            round(sum(value<=area for value in areas)/len(areas),3) if areas and row["geometry_members"] else None)
    return rows


def annotate(page_image: Path, atoms, visuals, output: Path):
    with Image.open(page_image) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for atom in atoms:
        for member in atom["geometry_members"]:
            box = member["bbox"]
            draw.rectangle(box, outline=(20, 170, 60), width=3)
            draw.text((box[0] + 2, box[1] + 2), str(atom["atom_id"]), fill=(20, 120, 20),
                      stroke_width=1, stroke_fill="white")
    for visual in visuals:
        box = bbox(visual.get("bbox"))
        if box:
            draw.rectangle(box, outline=(30, 100, 255), width=4)
            draw.text((box[0] + 2, max(0, box[1] - 14)), visual["visual_bundle_id"], fill=(20, 70, 220),
                      stroke_width=1, stroke_fill="white")
        for member in visual.get("geometry_members", []):
            if bbox(member.get("bbox")):
                draw.rectangle(member["bbox"], outline=(130, 40, 220), width=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def crop_visuals(page_image: Path, visuals, output: Path, limit=3):
    with Image.open(page_image) as source:
        image = source.convert("RGB")
    ranked = sorted((v for v in visuals if bbox(v.get("bbox"))),
                    key=lambda v: (v["bbox"][2] - v["bbox"][0]) * (v["bbox"][3] - v["bbox"][1]), reverse=True)
    result = []
    for index, visual in enumerate(ranked[:limit], 1):
        x1, y1, x2, y2 = [int(round(v)) for v in visual["bbox"]]
        x1, y1 = max(0, x1), max(0, y1); x2, y2 = min(image.width, x2), min(image.height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        target = output / f"crop_{index:02d}_{visual['visual_bundle_id']}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.crop((x1, y1, x2, y2)).save(target)
        result.append((visual["visual_bundle_id"], target))
    image.close()
    return result


def prompt(document, page, atoms, visuals, crop_order):
    schema = {
        "content_items": [{
            "content_item_id": "CI_1", "content_kind": "article|advertisement|slide_section|front_matter|other",
            "atom_ids": ["block_id"], "visual_bundle_ids": ["bundle_id"],
            "reading_order": ["mixed atom_id or bundle_id"],
            "structural_fragment_ids": ["owned title/byline/navigation/label fragment retained as structure"],
            "structural_visual_bundle_ids": ["owned decorative or structural visual bundle retained as structure"],
            "structural_visual_member_ids": ["structural member when the bundle is resolved member-by-member"],
            "atom_decisions": [{
                "atom_id": "block_id",
                "action": "KEEP_AS_CORE|ATTACH_TO_ATOM|SPLIT_INTO_UNITS|STRUCTURAL_KEEP|UNRESOLVED_KEEP",
                "target_atom_id": "required only for ATTACH_TO_ATOM; otherwise null",
                "structure_type": "required for STRUCTURAL_KEEP; otherwise null",
                "reason": "short evidence-based reason"
            }],
            "evidence_units": [{
                "evidence_unit_id": "EU_1", "unit_type": "TEXT|VISUAL|COMPOSITE",
                "text_fragment_ids": ["source_atom_id::F001"], "visual_bundle_ids": ["whole bundle target"],
                "visual_member_ids": ["specific member target; use instead of the whole bundle when members have different roles"],
                "completeness": "COMPLETE|POSSIBLE_CONTINUATION|UNRESOLVED",
                "visual_summary": "empty for TEXT; visibly grounded summary for visual units",
                "reason": "short assembly rationale"
            }]
        }],
        "page_structure_atom_ids": [], "page_structure_visual_bundle_ids": [], "unresolved": []
    }
    return f"""Build conservative candidate EvidenceUnits for page {page} of {document}.

First separate independent content items/articles. Then order atoms only inside their own content item. A page may contain multiple articles, advertisements, sidebars or slide sections. Do not merge independent top-level headings.

Atomicity decision (required for every item-owned source atom):
- KEEP_AS_CORE: the atom is an indivisible evidence core (possibly with attached fragments or a visual); a legitimate short claim/list item/label may use this.
- ATTACH_TO_ATOM: the atom is a parsing/layout fragment and all of its text belongs in an EvidenceUnit with target_atom_id.
- SPLIT_INTO_UNITS: a large/coarse source atom contains more than one independently useful EvidenceUnit.
- STRUCTURAL_KEEP: title, byline, navigation, label, page furniture or other structure. Preserve it in structural_fragment_ids with a structure_type; it is not a scientific EvidenceUnit but must remain materializable as a structural node/metadata object.
- UNRESOLVED_KEEP: attachment or splitting is uncertain; retain its content rather than destructively merging or dropping it.
- Decide using content-item ownership, syntactic completeness, semantic dependency, role and member-level geometry together. Text length and area percentiles are weak review signals only. Never choose an action from size alone.
- ATTACH_TO_ATOM must target an atom in the same content item and both atoms must share an EvidenceUnit. Do not attach across articles, to page furniture, or merely to the nearest box.

EvidenceUnit rules:
- Parsing/layout blocks are source atoms, not automatically EvidenceUnits. TextFragments are deterministic, provenance-preserving spans inside those atoms.
- Merge adjacent text fragments only when they form one paragraph, sentence continuation, or indivisible claim/evidence passage.
- A parsing error may leave a tiny source atom that belongs to a larger neighbouring passage. Use syntax, article ownership and geometry together to place it adjacent and in the same EvidenceUnit when strongly supported. Never merge merely because text is short: bylines, labels, code and list items are often legitimately small.
- A page-initial lowercase fragment may continue from the previous page. If the preceding source is not supplied, retain it and mark its EvidenceUnit POSSIBLE_CONTINUATION rather than guessing a host.
- Keep independent claims separate even when adjacent.
- A visual bundle may contain multiple separate geometry members. Never invent a union or silently discard a member.
- If all members form one indivisible visual, target the whole bundle. If members have distinct roles or references, leave the bundle out of unit targets and assign each member exactly once via visual_member_ids. Never target both a bundle and its members.
- Create VISUAL or COMPOSITE only when the visual contributes content. A composite unit may combine a figure/photo/table with its caption or the immediately interpreting text. Do not absorb an entire article into one composite.
- Logo, page furniture and decorative graphics may be non-content. Advertisements are content items, not automatically discarded.
- If a final text atom may continue on the next page, mark POSSIBLE_CONTINUATION; do not pretend it is complete.
- Every input atom and every visual bundle must occur exactly once in a content item or a page_structure list. Page-level structure is retained, never discarded.
- Inside each content item, every fragment and visual must occur exactly once in either one EvidenceUnit or the item's structural list. Titles and bylines normally use STRUCTURAL_KEEP rather than becoming scientific EvidenceUnits.
- reading_order must contain every item-owned atom/bundle exactly once.
- visual_summary must distinguish what is directly visible from interpretation; use nearby text only when consistent with the image.

Image order supplied to you: {json.dumps(crop_order, ensure_ascii=False)}
Return exactly one JSON object matching this schema:
{json.dumps(schema, ensure_ascii=False)}

SOURCE ATOMS WITH PROVENANCE-PRESERVING TEXT FRAGMENTS:
{json.dumps(atoms, ensure_ascii=False)}

VISUAL BUNDLES:
{json.dumps(visuals, ensure_ascii=False)}
"""


def validate(parsed, atoms, visuals):
    errors = []
    atom_ids = {row["atom_id"] for row in atoms}; visual_ids = {row["visual_bundle_id"] for row in visuals}
    assigned_atoms = list(parsed.get("page_structure_atom_ids", [])); assigned_visuals = list(parsed.get("page_structure_visual_bundle_ids", []))
    member_parent={member.get("member_id"):visual["visual_bundle_id"] for visual in visuals
                   for member in visual.get("geometry_members",[]) if member.get("member_id")}
    members_by_bundle={visual["visual_bundle_id"]:{member.get("member_id") for member in visual.get("geometry_members",[])
                       if member.get("member_id")} for visual in visuals}
    fragment_parent={fragment["fragment_id"]:atom["atom_id"] for atom in atoms for fragment in atom.get("text_fragments",[])}
    fragments_by_atom={atom["atom_id"]:{fragment["fragment_id"] for fragment in atom.get("text_fragments",[])} for atom in atoms}
    for item in parsed.get("content_items", []):
        owned_atoms = item.get("atom_ids", []); owned_visuals = item.get("visual_bundle_ids", [])
        assigned_atoms += owned_atoms; assigned_visuals += owned_visuals
        expected_order = set(owned_atoms) | set(owned_visuals); order = item.get("reading_order", [])
        if set(order) != expected_order or len(order) != len(set(order)):
            errors.append({"type": "reading_order_membership", "content_item_id": item.get("content_item_id")})
        unit_fragment_ids=[]; unit_visual_ids=[]; unit_member_ids=[]; unit_ids=[]
        fragment_units={fragment_id:[] for atom_id in owned_atoms for fragment_id in fragments_by_atom.get(atom_id,set())}
        for unit in item.get("evidence_units", []):
            unit_ids.append(unit.get("evidence_unit_id")); unit_fragment_ids += unit.get("text_fragment_ids", [])
            for fragment_id in unit.get("text_fragment_ids", []):
                fragment_units.setdefault(fragment_id,[]).append(unit.get("evidence_unit_id"))
            unit_visual_ids += unit.get("visual_bundle_ids", [])
            unit_member_ids += unit.get("visual_member_ids", [])
            invalid_fragments=[fragment for fragment in unit.get("text_fragment_ids",[])
                               if fragment not in fragment_parent or fragment_parent[fragment] not in set(owned_atoms)]
            if invalid_fragments:
                errors.append({"type":"unit_text_fragment_outside_item","unit":unit.get("evidence_unit_id"),
                               "fragment_ids":invalid_fragments})
            if not set(unit.get("visual_bundle_ids", [])) <= set(owned_visuals):
                errors.append({"type": "unit_visual_outside_item", "unit": unit.get("evidence_unit_id")})
            invalid_members=[member for member in unit.get("visual_member_ids", [])
                             if member not in member_parent or member_parent[member] not in set(owned_visuals)]
            if invalid_members:
                errors.append({"type":"unit_visual_member_outside_item","unit":unit.get("evidence_unit_id"),
                               "member_ids":invalid_members})
            kind=unit.get("unit_type"); texts=unit.get("text_fragment_ids", [])
            images=unit.get("visual_bundle_ids", [])+unit.get("visual_member_ids", [])
            if not texts and not images:
                errors.append({"type":"empty_evidence_unit","unit":unit.get("evidence_unit_id")})
            if kind == "TEXT" and images or kind == "VISUAL" and texts or kind == "COMPOSITE" and (not texts or not images):
                errors.append({"type":"unit_type_content_mismatch","unit":unit.get("evidence_unit_id")})
        if len(unit_ids) != len(set(unit_ids)):
            errors.append({"type":"duplicate_evidence_unit_id","content_item_id":item.get("content_item_id")})
        decisions=item.get("atom_decisions",[])
        decision_ids=[decision.get("atom_id") for decision in decisions]
        if Counter(decision_ids) != Counter({value:1 for value in owned_atoms}):
            errors.append({"type":"atom_decision_coverage","content_item_id":item.get("content_item_id"),
                           "missing":sorted(set(owned_atoms)-set(decision_ids)),
                           "duplicates":sorted(k for k,v in Counter(decision_ids).items() if v>1)})
        valid_actions={"KEEP_AS_CORE","ATTACH_TO_ATOM","SPLIT_INTO_UNITS","STRUCTURAL_KEEP","UNRESOLVED_KEEP"}
        for decision in decisions:
            atom_id=decision.get("atom_id"); action=decision.get("action"); target=decision.get("target_atom_id")
            atom_fragments=fragments_by_atom.get(atom_id,set())
            atom_units={unit for fragment_id in atom_fragments for unit in fragment_units.get(fragment_id,[]) if unit}
            if action not in valid_actions:
                errors.append({"type":"invalid_atom_action","atom_id":atom_id,"action":action})
            elif action=="ATTACH_TO_ATOM":
                target_fragments=fragments_by_atom.get(target,set()) if target in set(owned_atoms) and target!=atom_id else set()
                target_units={unit for fragment_id in target_fragments for unit in fragment_units.get(fragment_id,[]) if unit}
                if not target_fragments or not atom_units.intersection(target_units):
                    errors.append({"type":"invalid_atom_attachment","atom_id":atom_id,"target_atom_id":target})
            elif target not in (None,""):
                errors.append({"type":"unexpected_atom_target","atom_id":atom_id,"action":action,"target_atom_id":target})
            if action=="SPLIT_INTO_UNITS" and len(atom_units)<2:
                errors.append({"type":"atom_split_not_materialized","atom_id":atom_id})
            if action=="STRUCTURAL_KEEP":
                if atom_fragments-set(item.get("structural_fragment_ids",[])):
                    errors.append({"type":"structural_atom_not_materialized","atom_id":atom_id})
                if not str(decision.get("structure_type") or "").strip():
                    errors.append({"type":"structural_atom_missing_type","atom_id":atom_id})
            elif decision.get("structure_type") not in (None,""):
                errors.append({"type":"unexpected_structure_type","atom_id":atom_id,"action":action})
            if action in {"KEEP_AS_CORE","UNRESOLVED_KEEP"} and not atom_units:
                errors.append({"type":"retained_atom_missing_from_units","atom_id":atom_id,"action":action})
        owned_fragments=set().union(*(fragments_by_atom.get(atom_id,set()) for atom_id in owned_atoms)) if owned_atoms else set()
        accounted_fragments=unit_fragment_ids+item.get("structural_fragment_ids", [])
        accounted_visuals=unit_visual_ids+item.get("structural_visual_bundle_ids", [])
        accounted_members=unit_member_ids+item.get("structural_visual_member_ids", [])
        invalid_structural_members=[member for member in item.get("structural_visual_member_ids", [])
                                    if member not in member_parent or member_parent[member] not in set(owned_visuals)]
        if invalid_structural_members:
            errors.append({"type":"structural_visual_member_outside_item","content_item_id":item.get("content_item_id"),
                           "member_ids":invalid_structural_members})
        if Counter(accounted_fragments) != Counter({value:1 for value in owned_fragments}):
            errors.append({"type":"within_item_fragment_coverage","content_item_id":item.get("content_item_id"),
                           "missing":sorted(owned_fragments-set(accounted_fragments)),
                           "duplicates":sorted(k for k,v in Counter(accounted_fragments).items() if v>1)})
        for visual_id in owned_visuals:
            whole_count=Counter(accounted_visuals)[visual_id]
            member_counts={member:Counter(accounted_members)[member] for member in members_by_bundle.get(visual_id,set())}
            whole_ok=whole_count == 1 and not any(member_counts.values())
            members_ok=whole_count == 0 and bool(member_counts) and all(count == 1 for count in member_counts.values())
            if not (whole_ok or members_ok):
                errors.append({"type":"within_item_visual_coverage","content_item_id":item.get("content_item_id"),
                               "visual_bundle_id":visual_id,"whole_bundle_count":whole_count,
                               "member_counts":member_counts})
    if Counter(assigned_atoms) != Counter({value: 1 for value in atom_ids}):
        errors.append({"type": "atom_assignment", "missing": sorted(atom_ids-set(assigned_atoms)),
                       "duplicates": sorted(k for k,v in Counter(assigned_atoms).items() if v>1)})
    if Counter(assigned_visuals) != Counter({value: 1 for value in visual_ids}):
        errors.append({"type": "visual_assignment", "missing": sorted(visual_ids-set(assigned_visuals)),
                       "duplicates": sorted(k for k,v in Counter(assigned_visuals).items() if v>1)})
    return {"valid": not errors, "errors": errors}


def structural_rows(parsed, atoms, visuals, document_id, page):
    """Materialize non-scientific content as retained structural records, never deletions."""
    atoms_by_id={row["atom_id"]:row for row in atoms}; visuals_by_id={row["visual_bundle_id"]:row for row in visuals}
    rows=[]
    for atom_id in parsed.get("page_structure_atom_ids",[]):
        if atom_id in atoms_by_id:
            rows.append({"document_id":document_id,"page":page,"scope":"page","source_kind":"atom",
                         "structure_type":"PAGE_STRUCTURE","source_id":atom_id,"source":atoms_by_id[atom_id]})
    for visual_id in parsed.get("page_structure_visual_bundle_ids",[]):
        if visual_id in visuals_by_id:
            rows.append({"document_id":document_id,"page":page,"scope":"page","source_kind":"visual_bundle",
                         "structure_type":"PAGE_STRUCTURE_VISUAL","source_id":visual_id,"source":visuals_by_id[visual_id]})
    for item in parsed.get("content_items",[]):
        item_id=item.get("content_item_id")
        for decision in item.get("atom_decisions",[]):
            atom_id=decision.get("atom_id")
            if decision.get("action")=="STRUCTURAL_KEEP" and atom_id in atoms_by_id:
                rows.append({"document_id":document_id,"page":page,"scope":"content_item",
                             "content_item_id":item_id,"source_kind":"atom",
                             "structure_type":decision.get("structure_type"),"source_id":atom_id,
                             "reason":decision.get("reason"),"source":atoms_by_id[atom_id]})
        for visual_id in item.get("structural_visual_bundle_ids",[]):
            if visual_id in visuals_by_id:
                rows.append({"document_id":document_id,"page":page,"scope":"content_item",
                             "content_item_id":item_id,"source_kind":"visual_bundle",
                             "structure_type":"STRUCTURAL_VISUAL","source_id":visual_id,
                             "source":visuals_by_id[visual_id]})
        for member_id in item.get("structural_visual_member_ids",[]):
            rows.append({"document_id":document_id,"page":page,"scope":"content_item",
                         "content_item_id":item_id,"source_kind":"visual_member",
                         "structure_type":"STRUCTURAL_VISUAL_MEMBER","source_id":member_id})
    return rows


def action_distribution(parsed):
    return dict(Counter(decision.get("action") or "MISSING"
                        for item in parsed.get("content_items",[])
                        for decision in item.get("atom_decisions",[])))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True); parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--visual-provenance", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true"); parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-new-tokens", type=int, default=1800)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(args.manifest); provenance = load_provenance(args.visual_provenance)
    llm = None if args.prepare_only else create_llm(load_config(args.config)["enrichment"])
    summaries=[]; all_units=[]; all_structural=[]; report_rows=[]
    documents=manifest["documents"]
    work_items=[]
    for page_index in range(max(len(document["pages"]) for document in documents)):
        for document in documents:
            if page_index < len(document["pages"]):
                work_items.append((document,document["pages"][page_index]))
    for document,page in work_items:
            doc_id=document["document_id"]; aligned_root=Path(document["aligned_root"]); raw_root=Path(document["raw_root"])
            target=args.output/doc_id/page; payload=read_json(aligned_root/f"{page}.json")
            atoms=atom_rows(payload); visuals=visual_rows(provenance.get((doc_id,page), {"bundles": []}))
            page_image=raw_root/page/"page.png"; annotated=target/"annotated_page.png"
            annotate(page_image,atoms,visuals,annotated); crops=crop_visuals(page_image,visuals,target/"visual_crops")
            crop_order=["annotated full page"]+[bundle_id for bundle_id,_ in crops]
            representation={"document_id":doc_id,"page":page,"atoms":atoms,"visual_bundles":visuals,
                            "annotated_page":str(annotated),"crop_order":crop_order}
            write_json(target/"input_representation.json",representation)
            request=prompt(doc_id,page,atoms,visuals,crop_order); (target/"prompt.txt").write_text(request,encoding="utf-8")
            if args.prepare_only:
                summaries.append({"document_id":doc_id,"page":page,"status":"prepared","atoms":len(atoms),"visuals":len(visuals)})
                report_rows.append((doc_id,page,annotated,None))
                continue
            assembly_path=target/"evidence_unit_assembly.json"; validation_path=target/"validation.json"
            if args.resume and assembly_path.exists() and validation_path.exists():
                parsed=read_json(assembly_path); check=read_json(validation_path)
                all_structural.extend(structural_rows(parsed,atoms,visuals,doc_id,page))
                unit_count=0
                for item in parsed.get("content_items",[]):
                    for unit in item.get("evidence_units",[]):
                        all_units.append({"document_id":doc_id,"page":page,"content_item_id":item.get("content_item_id"),**unit})
                        unit_count+=1
                summaries.append({"document_id":doc_id,"page":page,"status":"resumed","atoms":len(atoms),"visuals":len(visuals),
                                  "content_items":len(parsed.get("content_items",[])),"evidence_units":unit_count,
                                  "atom_action_distribution":action_distribution(parsed),
                                  "retained_structural_records":len(structural_rows(parsed,atoms,visuals,doc_id,page)),
                                  "validation":check})
                report_rows.append((doc_id,page,annotated,parsed))
                continue
            image_paths=[str(annotated)]+[str(path) for _,path in crops]
            parsed={}; parse_errors=[]; generation=None
            attempts=[(request,args.max_new_tokens),
                      (request+"\nRETRY: Return compact complete JSON. Use no prose outside JSON; keep every reason under 8 words and every visual_summary under 30 words.",
                       max(args.max_new_tokens,4000))]
            for attempt,(attempt_prompt,token_limit) in enumerate(attempts,1):
                try:
                    generation=llm.generate_raw_with_images(
                        "Conservative document EvidenceUnit assembler. JSON only.",attempt_prompt,image_paths,token_limit)
                except Exception as exc:
                    parse_errors.append({"attempt":attempt,"error":f"generation_error: {exc}","raw_characters":0})
                    continue
                (target/f"raw_response_attempt_{attempt}.txt").write_text(generation.raw,encoding="utf-8")
                try:
                    candidate=extract_json(generation.raw)
                    if isinstance(candidate,dict):
                        parsed=candidate; break
                    parse_errors.append({"attempt":attempt,"error":"top-level JSON is not an object",
                                         "raw_characters":len(generation.raw)})
                except (ValueError,json.JSONDecodeError) as exc:
                    parse_errors.append({"attempt":attempt,"error":str(exc),"raw_characters":len(generation.raw)})
            if not parsed:
                failure={"document_id":doc_id,"page":page,"status":"generation_failed",
                         "parse_errors":parse_errors,"production_modified":False}
                write_json(target/"generation_failure.json",failure); summaries.append(failure)
                write_json(args.output/"progress.json",{"production_modified":False,"completed_pages":summaries})
                report_rows.append((doc_id,page,annotated,{"generation_failure":failure}))
                continue
            check=validate(parsed,atoms,visuals); write_json(target/"evidence_unit_assembly.json",parsed)
            all_structural.extend(structural_rows(parsed,atoms,visuals,doc_id,page))
            write_json(target/"validation.json",check); (target/"raw_response.txt").write_text(generation.raw,encoding="utf-8")
            unit_count=0
            for item in parsed.get("content_items",[]):
                for unit in item.get("evidence_units",[]):
                    all_units.append({"document_id":doc_id,"page":page,"content_item_id":item.get("content_item_id"),**unit})
                    unit_count+=1
            summaries.append({"document_id":doc_id,"page":page,"status":"complete","atoms":len(atoms),"visuals":len(visuals),
                              "content_items":len(parsed.get("content_items",[])),"evidence_units":unit_count,
                              "atom_action_distribution":action_distribution(parsed),
                              "retained_structural_records":len(structural_rows(parsed,atoms,visuals,doc_id,page)),
                              "validation":check})
            report_rows.append((doc_id,page,annotated,parsed))
            write_json(args.output/"progress.json",{"production_modified":False,"completed_pages":summaries})
    overall_actions=Counter()
    for row in summaries:
        overall_actions.update(row.get("atom_action_distribution",{}))
    write_json(args.output/"summary.json",{"production_modified":False,"pages":summaries,
               "atomicity_action_distribution":dict(overall_actions),
               "valid_completed_pages":sum(bool(row.get("validation",{}).get("valid")) for row in summaries),
               "retained_structural_records":sum(row.get("retained_structural_records",0) for row in summaries)})
    if all_units:
        (args.output/"evidence_unit_candidates.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in all_units)+"\n",encoding="utf-8")
    if all_structural:
        (args.output/"structural_candidates.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in all_structural)+"\n",encoding="utf-8")
    cards=[]
    for doc_id,page,annotated,parsed in report_rows:
        relative=annotated.relative_to(args.output)
        detail="Prepared input; model assembly pending." if parsed is None else json.dumps(parsed,ensure_ascii=False,indent=2)
        cards.append(f"<section><h2>{html.escape(doc_id)} — {html.escape(page)}</h2>"
                     f"<img src='{html.escape(str(relative))}'><pre>{html.escape(detail)}</pre></section>")
    (args.output/"evidence_unit_shadow_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>EvidenceUnit shadow pilot</title>"
        "<style>body{font:14px system-ui;margin:24px;background:#111;color:#eee}section{margin:24px 0;padding:16px;background:#222}"
        "img{max-width:58%;vertical-align:top}pre{display:inline-block;max-width:40%;max-height:900px;overflow:auto;white-space:pre-wrap;margin-left:1%}</style>"
        "<h1>EvidenceUnit shadow pilot</h1><p>Green=text atoms; blue=VisualBundle; purple=separate VisualMembers. Production unchanged.</p>"+"".join(cards),
        encoding="utf-8")
    print(json.dumps({"pages":len(summaries),"production_modified":False,"output":str(args.output)}))


if __name__ == "__main__":
    main()
