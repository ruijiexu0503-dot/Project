from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .config import load_config
from .enrichment import enrich_evidence_nodes
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


def _slug(value): return re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(value).name)


def _fields(node):
    return {"base_summary": node.get("base_summary"), "key_points": node.get("key_points", []),
            "keywords": node.get("keywords", []), "entities": node.get("entities", []),
            "discourse_role": node.get("discourse_role"),
            "formula_semantics": node.get("metadata", {}).get("formula_semantics")}


def main():
    parser=argparse.ArgumentParser(description="Resumable non-destructive enrichment model comparison")
    parser.add_argument("--doc-id",required=True); parser.add_argument("--config",required=True)
    parser.add_argument("--output-root",default="output/enrichment_comparisons"); parser.add_argument("--batch-size",type=int,default=2)
    args=parser.parse_args(); config=load_config(args.config); model=config["enrichment"]["model"]
    source=Path(config["output"]["graph_root"])/args.doc_id
    output=Path(args.output_root)/_slug(model)/args.doc_id; output.mkdir(parents=True,exist_ok=True)
    checkpoint_path=output/"node_enrichment_comparison.jsonl"
    nodes=sorted(read_jsonl(source/"evidence_nodes.jsonl"),key=lambda n:n["document_order"])
    existing=read_jsonl(checkpoint_path) if checkpoint_path.exists() else []
    by_id={r["node_id"]:r for r in existing}; pending=[]
    for node in nodes:
        row=by_id.get(node["node_id"])
        if not row or (row.get("status")!="ok" and row.get("attempts",0)<3): pending.append(node)
    llm=create_llm(config["enrichment"])
    for offset in range(0,len(pending),args.batch_size):
        batch=pending[offset:offset+args.batch_size]; selected={n["node_id"] for n in batch}
        updated,failures=enrich_evidence_nodes(
            nodes,selected,llm,args.batch_size,config["enrichment"].get("generation_tokens",450),
            config["enrichment"].get("retry_generation_tokens",650))
        updated_by_id={n["node_id"]:n for n in updated}; failed={nid for f in failures for nid in f.get("node_ids",[])}
        for node in batch:
            previous=by_id.get(node["node_id"],{}); attempts=previous.get("attempts",0)+1
            candidate=updated_by_id[node["node_id"]]
            status="error" if node["node_id"] in failed else "ok"
            by_id[node["node_id"]]={"node_id":node["node_id"],"document_order":node["document_order"],
                "evidence_type":node.get("evidence_type"),"status":status,"attempts":attempts,
                "qwen2_5_baseline":_fields(node),"qwen3_5_candidate":_fields(candidate) if status=="ok" else None,
                "candidate_model":model,"failures":[f for f in failures if node["node_id"] in f.get("node_ids",[])]}
        write_jsonl(checkpoint_path,[by_id[k] for k in sorted(by_id,key=lambda x:next(n["document_order"] for n in nodes if n["node_id"]==x))])
        print({"processed":min(offset+len(batch),len(pending)),"pending_at_start":len(pending),
               "complete":sum(r.get("status")=="ok" for r in by_id.values())},flush=True)
    summary={"doc_id":args.doc_id,"source_nodes":len(nodes),"candidate_model":model,
             "completed":sum(r.get("status")=="ok" for r in by_id.values()),
             "unresolved":sum(r.get("status")!="ok" for r in by_id.values()),
             "original_evidence_nodes_unchanged":True}
    write_json(output/"summary.json",summary); print(json.dumps(summary,indent=2))


if __name__=="__main__": main()
