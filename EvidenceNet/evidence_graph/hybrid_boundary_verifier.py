from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .io_utils import read_json, read_jsonl, write_jsonl
from .llm_client import create_llm

PROMPT_VERSION="hybrid-boundary-verification-v1"


def verify_document(doc_id, candidate_report, config, llm):
    root=Path(config["output"]["graph_root"])/doc_id
    nodes=sorted(read_jsonl(root/"evidence_nodes.jsonl"),key=lambda n:n["document_order"])
    candidates=sorted(set(candidate_report["methods"]["title_plus_strong_trend"]))
    checkpoint=root/"hybrid_boundary_checkpoint.jsonl"
    existing=read_jsonl(checkpoint) if checkpoint.exists() else []
    by_index={r["boundary_index"]:r for r in existing if r.get("prompt_version")==PROMPT_VERSION
              and r.get("decision") in {"SAME_CONTENT_UNIT","STARTS_NEW_CONTENT_UNIT"}}
    system=("Determine whether a candidate position separates independent content units. Use only "
            "the supplied local text. Return JSON only. Reject subsection, caption, running-header, "
            "byline, affiliation, and ordinary paragraph transitions as content-unit boundaries.")
    for index in candidates:
        if index in by_index: continue
        left=nodes[max(0,index-2):index+1];right=nodes[index+1:min(len(nodes),index+4)]
        payload={"boundary_index":index,"left":[{"node_id":n["node_id"],"text":n["plain_text"][-900:]} for n in left],
                 "right":[{"node_id":n["node_id"],"text":n["plain_text"][:900]} for n in right],
                 "cross_similarity":candidate_report["similarities"][index],
                 "smoothed_similarity":candidate_report["smoothed"][index],
                 "prominence":candidate_report["prominence"][index]}
        prompt=f'''Decide whether the right side begins a new independent article, appendix, or other
standalone content unit. The nearest paragraphs may differ in
topic without creating a new unit. A title/byline followed by coherent body text is strong evidence;
a caption, subsection, running header, affiliation, date, or continuation is not.
Return one object with boundary_index; decision (SAME_CONTENT_UNIT or STARTS_NEW_CONTENT_UNIT);
confidence; supporting_span_left; supporting_span_right; rationale; right_unit_kind
(editorial, front_matter, back_matter, or other).
INPUT:\n{json.dumps(payload,ensure_ascii=False)}'''
        try:
            g=llm.generate_json(system,prompt,max_new_tokens=900);row=g.parsed
            if not isinstance(row,dict) or row.get("decision") not in {"SAME_CONTENT_UNIT","STARTS_NEW_CONTENT_UNIT"}:
                raise ValueError("invalid boundary decision")
            result={"boundary_index":index,"left_id":nodes[index]["node_id"],"right_id":nodes[index+1]["node_id"],
                    "decision":row["decision"],"confidence":float(row.get("confidence",0)),
                    "supporting_span_left":str(row.get("supporting_span_left","")),
                    "supporting_span_right":str(row.get("supporting_span_right","")),
                    "rationale":str(row.get("rationale","")),"right_unit_kind":row.get("right_unit_kind","other"),
                    "embedding_signals":{"cross_similarity":payload["cross_similarity"],
                        "smoothed_similarity":payload["smoothed_similarity"],"prominence":payload["prominence"]},
                    "model":g.model,"timestamp":g.timestamp,"prompt_version":PROMPT_VERSION}
        except Exception as exc:
            result={"boundary_index":index,"left_id":nodes[index]["node_id"],"right_id":nodes[index+1]["node_id"],
                    "decision":"UNRESOLVED","error":str(exc),"prompt_version":PROMPT_VERSION}
        by_index[index]=result;write_jsonl(checkpoint,[by_index[i] for i in sorted(by_index)])
    rows=[by_index[i] for i in candidates]
    accepted={r["boundary_index"] for r in rows if r["decision"]=="STARTS_NEW_CONTENT_UNIT" and r.get("confidence",0)>=.8}
    unit=1;assignments=[]
    for i,node in enumerate(nodes):
        if i and i-1 in accepted: unit+=1
        assignments.append({"node_id":node["node_id"],"content_unit_id":f"UNIT_{unit:04d}"})
    edges=[{"source":r["left_id"],"target":r["right_id"],"edge_layer":"content_segmentation",
            "edge_type":r["decision"],"confidence":r.get("confidence",0),"supporting_span_left":r.get("supporting_span_left",""),
            "supporting_span_right":r.get("supporting_span_right",""),"rationale":r.get("rationale",""),
            "right_unit_kind":r.get("right_unit_kind"),"embedding_signals":r.get("embedding_signals",{})}
           for r in rows if r["decision"]!="UNRESOLVED"]
    write_jsonl(root/"hybrid_content_unit_edges.jsonl",edges)
    write_jsonl(root/"hybrid_content_unit_assignments.jsonl",assignments)
    return {"doc_id":doc_id,"candidates":len(candidates),"accepted_boundaries":len(accepted),
            "content_units":unit,"unresolved":sum(r["decision"]=="UNRESOLVED" for r in rows)}


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--config",required=True);p.add_argument("--comparison",required=True)
    a=p.parse_args(argv);config=load_config(a.config);comparison=read_json(a.comparison);llm=create_llm(config["enrichment"])
    results=[]
    for report in comparison["documents"]:
        results.append(verify_document(report["doc_id"],report,config,llm));print(json.dumps(results[-1]),flush=True)


if __name__=="__main__":main()
