from __future__ import annotations
import argparse,json
from pathlib import Path
from .candidate_generator import generate_semantic_candidates
from .config import load_config
from .embeddings import generate_document_embeddings
from .io_utils import read_jsonl,write_json,write_jsonl
from .split_semantic_run import BGE_M3

def main():
 p=argparse.ArgumentParser();p.add_argument("--doc-id",required=True);p.add_argument("--model-slug",default="Qwen3.5-35B-A3B");p.add_argument("--config",default="config/evidence_graph.yaml");a=p.parse_args()
 source=Path("output/qwen35_semantic_graphs")/a.model_slug/"evidence_graph"/a.doc_id
 target=Path("output/scientific_body_semantics/shared_candidates")/a.doc_id;target.mkdir(parents=True,exist_ok=True)
 eligibility={x["node_id"]:x for x in read_jsonl(Path("output/semantic_eligibility")/a.doc_id/"node_eligibility.jsonl")}
 nodes=[x for x in read_jsonl(source/"evidence_nodes.jsonl") if eligibility[x["node_id"]]["semantic_eligible"]]
 config=load_config(a.config); config["embedding"].update(enabled=True,model=BGE_M3,input_mode="original_plus_summary")
 embeddings,metadata=generate_document_embeddings(nodes,{x["node_id"] for x in nodes},config["embedding"]["input_mode"],config["embedding"]["model"])
 assignments={x["node_id"]:f"{a.doc_id}_SCIENTIFIC_BODY" for x in nodes}
 candidates=generate_semantic_candidates(nodes,embeddings,{**config["candidates"],**config.get("full_semantic",{})},assignments)
 write_jsonl(target/"evidence_nodes.jsonl",nodes);write_jsonl(target/"embedding_vectors.jsonl",embeddings);write_json(target/"embedding_metadata.json",metadata);write_jsonl(target/"candidates.jsonl",candidates)
 summary={"doc_id":a.doc_id,"semantic_eligible_nodes":len(nodes),"candidates":len(candidates),"source_enrichment":a.model_slug};write_json(target/"summary.json",summary);print(json.dumps(summary,indent=2))
if __name__=="__main__":main()
