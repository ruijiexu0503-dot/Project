from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .config import load_config
from .io_utils import read_json, read_jsonl, write_json, write_jsonl
from .loader import load_aligned_document, page_number

ASSET_LABELS = {"image": "figure", "chart": "figure", "figure": "figure", "table": "table"}
CAPTION_PREFIX = re.compile(r"\b(FIG(?:URE)?|TABLE)\.?\s*([0-9IVXLCDM]+)\b", re.I)
REFERENCE = re.compile(r"\b(Fig(?:ure)?|Table)\.?\s*([0-9IVXLCDM]+)\b", re.I)


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _roman(value):
    if value.isdigit(): return int(value)
    vals={"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}; total=0; prev=0
    for char in reversed(value.upper()):
        number=vals.get(char,0); total += -number if number < prev else number; prev=max(prev,number)
    return total or None


def _resolve_page_image(page, aligned_root):
    raw=Path(str(page.get("page_image") or ""))
    if raw.is_absolute() and raw.exists(): return raw
    root=Path(aligned_root).resolve()
    candidates=[root/raw, root.parents[2]/raw if len(root.parents)>2 else root/raw]
    for candidate in candidates:
        if candidate.exists(): return candidate
    return candidates[-1]


def _crop(source, bbox, target):
    from PIL import Image
    target.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(source) as image:
        x1,y1,x2,y2=[max(0,int(round(x))) for x in bbox]
        x2=min(image.width,x2);y2=min(image.height,y2)
        image.crop((x1,y1,x2,y2)).save(target)


def _edge(source,target,kind,confidence=1.0,metadata=None):
    return {"source":source,"target":target,"edge_layer":"structural","edge_type":kind,
            "confidence":confidence,"metadata":metadata or {}}


def build_multimodal(doc_id: str, config: dict[str,Any]):
    root=Path(config["output"]["graph_root"])/doc_id
    pages=load_aligned_document(config["input"]["aligned_root"],doc_id)
    evidence=read_jsonl(root/"evidence_nodes.jsonl"); sections=read_jsonl(root/"section_nodes.jsonl")
    structural=read_jsonl(root/"structural_edges.jsonl"); graph=read_json(root/"graph.json")
    by_page={}
    for node in evidence: by_page.setdefault(node["page_ids"][0],[]).append(node)
    visual_nodes=[]; visual_by_number={}; caption_ids=set(); warnings=[]
    counters={"figure":0,"table":0}
    for page in pages:
        page_id=page["page"]
        grouped={}
        for region in page.get("layout_regions",[]):
            kind=ASSET_LABELS.get(str(region.get("label") or "").lower())
            bbox=region.get("bbox")
            if kind and isinstance(bbox,list) and len(bbox)==4: grouped.setdefault(kind,[]).append(region)
        captions=[]
        for node in by_page.get(page_id,[]):
            for match in CAPTION_PREFIX.finditer(node["plain_text"]):
                kind="table" if match.group(1).upper()=="TABLE" else "figure"
                if kind=="figure" and not (node.get("evidence_type")=="caption" and match.start()<8):
                    continue
                captions.append((node,kind,_roman(match.group(2))))
        for kind,regions in grouped.items():
            matching=[x for x in captions if x[1]==kind]
            caption,number=(matching[0][0],matching[0][2]) if matching else (None,None)
            counters[kind]+=1; number=number or counters[kind]
            prefix="FIG" if kind=="figure" else "TABLE"; node_id=f"{doc_id}_{prefix}_{number:04d}"
            bbox=_union([r["bbox"] for r in regions]); crop=root/"assets"/f"{node_id}.png"
            source=_resolve_page_image(page,config["input"]["aligned_root"])
            try: _crop(source,bbox,crop)
            except Exception as exc: warnings.append({"type":"visual_crop_failed","node_id":node_id,"error":str(exc),"source":str(source)})
            node={"node_id":node_id,"node_type":"visual","visual_type":kind,"doc_id":doc_id,
                  "section_id":caption.get("section_id") if caption else (by_page.get(page_id) or [{}])[0].get("section_id"),
                  "section_path":caption.get("section_path",[]) if caption else (by_page.get(page_id) or [{}])[0].get("section_path",[]),
                  "page":page_id,"page_ids":[page_id],"bbox":bbox,"source_region_ids":[r.get("region_id") for r in regions],
                  "source_region_labels":[r.get("label") for r in regions],"page_image":str(source),
                  "asset_path":str(crop.resolve()) if crop.exists() else None,"caption_evidence_id":caption.get("node_id") if caption else None,
                  "caption_text":caption.get("original_markdown") if caption else None,
                  "document_order":caption.get("document_order") if caption else min(
                      (n.get("document_order", 10**9) for n in by_page.get(page_id, [])), default=10**9),
                  "modalities":["image"],"provisional":True}
            visual_nodes.append(node); visual_by_number[(kind,number)]=node
            if caption: caption_ids.add(caption["node_id"])
    additions=[]
    for visual in visual_nodes:
        additions.append(_edge(visual["node_id"],doc_id,"IN_DOCUMENT"))
        if visual.get("section_id"): additions.append(_edge(visual["node_id"],visual["section_id"],"IN_SECTION"))
        if visual.get("caption_evidence_id"):
            additions.append(_edge(visual["caption_evidence_id"],visual["node_id"],"CAPTION_OF"))
            additions.append(_edge(visual["node_id"],visual["caption_evidence_id"],"HAS_CAPTION"))
        for page_node in by_page.get(visual["page"], []):
            additions.append(_edge(page_node["node_id"], visual["node_id"], "COLOCATED_WITH_VISUAL", 1.0,
                {"page": visual["page"], "semantic_candidate_only": True,
                 "reason": "text_and_visual_share_source_page"}))
    for node in evidence:
        for match in REFERENCE.finditer(node["original_markdown"]):
            kind="table" if match.group(1).lower().startswith("table") else "figure"; number=_roman(match.group(2))
            visual=visual_by_number.get((kind,number))
            if visual and node["node_id"] != visual.get("caption_evidence_id"):
                additions.append(_edge(node["node_id"],visual["node_id"],"REFERENCES_TABLE" if kind=="table" else "REFERENCES_FIGURE",
                                       metadata={"reference_span":match.group(0)}))
    # Associate parsed HTML table content with the nearest table visual on the same page.
    for visual in (v for v in visual_nodes if v["visual_type"]=="table"):
        page_nodes=sorted(by_page.get(visual["page"],[]),key=lambda n:n["document_order"])
        caption=next((n for n in page_nodes if n["node_id"]==visual.get("caption_evidence_id")),None)
        contents=[n for n in page_nodes if re.search(r"<table\b",n["original_markdown"],re.I)]
        if contents:
            content=min(contents,key=lambda n:abs(n["document_order"]-(caption["document_order"] if caption else n["document_order"])))
            additions.append(_edge(content["node_id"],visual["node_id"],"TABLE_CONTENT_OF"))
            additions.append(_edge(visual["node_id"],content["node_id"],"HAS_TABLE_CONTENT"))
    # Retype display mathematics without changing IDs, source text, or provenance.
    formulas=[]; ordered=sorted(evidence,key=lambda n:n["document_order"])
    for index,node in enumerate(ordered):
        if re.search(r"\\\[.*?\\\]",node["original_markdown"],re.S):
            node["evidence_type"]="formula"; node["modalities"]=["text","math"]
            node["metadata"]={**node.get("metadata",{}),"derived_content_kind":"display_formula"}; formulas.append(node["node_id"])
            if index:
                prev=ordered[index-1]; additions.append(_edge(prev["node_id"],node["node_id"],"REFERENCES_FORMULA",
                    0.95,{"reason":"text_immediately_introduces_display_formula"}))
                additions.append(_edge(prev["node_id"],node["node_id"],"CONTINUES_TO",0.95,{"reason":"display_formula_continuation"}))
            if index+1<len(ordered) and ordered[index+1]["plain_text"].lstrip()[:1].islower():
                additions.append(_edge(node["node_id"],ordered[index+1]["node_id"],"CONTINUES_TO",0.98,
                    {"reason":"formula_followed_by_symbol_explanation"}))
    multimodal_types={"REFERENCES_FIGURE","REFERENCES_TABLE","REFERENCES_FORMULA","CAPTION_OF","HAS_CAPTION",
                      "COLOCATED_WITH_VISUAL",
                      "TABLE_CONTENT_OF","HAS_TABLE_CONTENT"}
    structural=[e for e in structural if e["edge_type"] not in multimodal_types]
    seen={(e["source"],e["target"],e["edge_type"]) for e in structural}; unique=[]
    for edge in additions:
        key=(edge["source"],edge["target"],edge["edge_type"])
        if key not in seen: unique.append(edge);seen.add(key)
    structural+=unique
    write_jsonl(root/"visual_nodes.jsonl",visual_nodes);write_jsonl(root/"evidence_nodes.jsonl",evidence)
    write_jsonl(root/"multimodal_structural_edges.jsonl",[e for e in structural if e["edge_type"] in multimodal_types])
    write_jsonl(root/"structural_edges.jsonl",structural)
    non_visual=[n for n in graph["nodes"] if n.get("node_type")!="visual"]
    by_id={n["node_id"]:n for n in evidence}
    graph["nodes"]=[by_id.get(n["node_id"],n) for n in non_visual]+visual_nodes
    semantic=[e for e in graph["edges"] if e.get("edge_layer")=="semantic"]
    graph["edges"]=structural+semantic;write_json(root/"graph.json",graph)
    report={"doc_id":doc_id,"visual_nodes":len(visual_nodes),"figures":sum(n["visual_type"]=="figure" for n in visual_nodes),
            "tables":sum(n["visual_type"]=="table" for n in visual_nodes),"formula_evidence_nodes":formulas,
            "added_structural_edges":len(unique),"warnings":warnings}
    errors=[]; ids=[n["node_id"] for n in visual_nodes]
    if len(ids)!=len(set(ids)): errors.append({"type":"duplicate_visual_node_ids"})
    for node in visual_nodes:
        if not node.get("asset_path") or not Path(node["asset_path"]).exists(): errors.append({"type":"missing_visual_asset","node_id":node["node_id"]})
        if not node.get("caption_evidence_id"):
            warnings.append({"type":"missing_visual_caption","node_id":node["node_id"]})
    linked_formula={e["target"] for e in structural if e["edge_type"]=="REFERENCES_FORMULA"}
    for node_id in formulas:
        if node_id not in linked_formula: errors.append({"type":"isolated_formula","node_id":node_id})
    validation={"doc_id":doc_id,"valid":not errors,"errors":errors,"warnings":warnings,
                "summary":{"error_count":len(errors),"warning_count":len(warnings)}}
    write_json(root/"multimodal_report.json",report);write_json(root/"multimodal_validation_report.json",validation)
    return {**report,"validation":validation["summary"]}


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument("--doc-id",required=True);parser.add_argument("--config",required=True);args=parser.parse_args(argv)
    print(json.dumps(build_multimodal(args.doc_id,load_config(args.config)),indent=2))
if __name__=="__main__":main()
