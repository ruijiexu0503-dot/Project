from __future__ import annotations
import argparse,json
from pathlib import Path
from .adversarial_verifier import bidirectional_traversal_rows
from .config import load_config
from .io_utils import read_jsonl,write_json,write_jsonl
from .llm_client import create_llm
from .relation_verifier import verify_semantic_relations

def main():
 p=argparse.ArgumentParser();p.add_argument("--model",required=True);p.add_argument("--output",required=True);p.add_argument("--config",default="config/evidence_graph.yaml");p.add_argument("--chunk-size",type=int,default=5);a=p.parse_args()
 source=Path("output/scientific_body_semantics/shared_candidates/gw150914_detection");target=Path(a.output);target.mkdir(parents=True,exist_ok=True)
 nodes=read_jsonl(source/"evidence_nodes.jsonl");candidates=read_jsonl(source/"candidates.jsonl")
 status_path=target/"status.json";status=json.loads(status_path.read_text()) if status_path.exists() else {"processed":0}
 accepted=read_jsonl(target/"accepted_edges.jsonl") if (target/"accepted_edges.jsonl").exists() else []
 rejected=read_jsonl(target/"rejected.jsonl") if (target/"rejected.jsonl").exists() else []
 unsupported=read_jsonl(target/"unsupported.jsonl") if (target/"unsupported.jsonl").exists() else []
 malformed=read_jsonl(target/"malformed.jsonl") if (target/"malformed.jsonl").exists() else []
 config=load_config(a.config);config["enrichment"].update(model=str(Path(a.model).resolve()),require_cuda=True,enable_thinking=False)
 llm=create_llm(config["enrichment"]);start=int(status.get("processed",0))
 for offset in range(start,len(candidates),a.chunk_size):
  chunk=candidates[offset:offset+a.chunk_size]
  aa,rr,uu,mm=verify_semantic_relations(chunk,nodes,llm,threshold=.80,batch_size=2,generation_tokens=700,retry_generation_tokens=900,require_reverse_consistency=True)
  accepted+=aa;rejected+=rr;unsupported+=uu;malformed+=mm
  write_jsonl(target/"accepted_edges.jsonl",accepted);write_jsonl(target/"rejected.jsonl",rejected);write_jsonl(target/"unsupported.jsonl",unsupported);write_jsonl(target/"malformed.jsonl",malformed)
  status={"processed":min(offset+len(chunk),len(candidates)),"total":len(candidates),"accepted":len(accepted),"rejected":len(rejected),"unsupported":len(unsupported),"malformed":len(malformed),"complete":offset+len(chunk)>=len(candidates)}
  write_json(status_path,status);print(json.dumps(status),flush=True)
 write_jsonl(target/"bidirectional_traversal.jsonl",bidirectional_traversal_rows(accepted))
if __name__=="__main__":main()
