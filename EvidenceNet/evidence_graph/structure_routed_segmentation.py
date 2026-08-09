from __future__ import annotations

import argparse, json
from pathlib import Path

from .embeddings import generate_document_embeddings
from .io_utils import read_json, read_jsonl, write_json, write_jsonl
from .page_aware_segmentation import segment


def main():
    p=argparse.ArgumentParser(description="Apply binary structure-profile routing to Evidence graphs")
    p.add_argument("--graph-root",required=True);p.add_argument("--profile-root",required=True)
    p.add_argument("--aligned-root",required=True);p.add_argument("--output-root",required=True)
    args=p.parse_args(); graph_root=Path(args.graph_root); profiles=Path(args.profile_root)
    aligned=Path(args.aligned_root); output=Path(args.output_root);output.mkdir(parents=True,exist_ok=True)
    summary=[]
    for node_path in sorted(graph_root.glob("*/evidence_nodes.jsonl")):
        doc=node_path.parent.name; profile=read_json(profiles/f"{doc}.json"); nodes=read_jsonl(node_path)
        target=output/doc;target.mkdir(parents=True,exist_ok=True)
        if profile["profile"]=="MULTI_ITEM_COLLECTION":
            embeddings,meta=generate_document_embeddings(nodes,{n["node_id"] for n in nodes},"original_plus_summary")
            assignments,segments,diagnostics,standalone,resumptions=segment(nodes,embeddings,str(aligned/doc))
            write_jsonl(target/"embedding_vectors.jsonl",embeddings);write_json(target/"embedding_metadata.json",meta)
            write_jsonl(target/"assignments.jsonl",assignments);write_jsonl(target/"segments.jsonl",segments)
            write_jsonl(target/"boundary_diagnostics.jsonl",diagnostics)
            result={"doc_id":doc,"profile":profile["profile"],"action":"SEGMENTED",
                    "nodes":len(nodes),"top_level_items":len({r["content_item_id"] for r in assignments}),
                    "segments":len(segments),"whole_page_interruptions":len(standalone),"resumptions":len(resumptions)}
        else:
            assignments=[{"node_id":n["node_id"],"segment_id":"SEGMENT_0001","content_item_id":"ITEM_0001"} for n in nodes]
            write_jsonl(target/"assignments.jsonl",assignments)
            result={"doc_id":doc,"profile":profile["profile"],"action":"PRESERVED_ONE_TOP_LEVEL_ITEM",
                    "nodes":len(nodes),"top_level_items":1,"internal_sections":len({tuple(n.get("section_path") or []) for n in nodes if n.get("section_path")})}
        write_json(target/"routing_result.json",result);summary.append(result);print(json.dumps(result),flush=True)
    write_json(output/"summary.json",{"documents":len(summary),"results":summary,"uses_llm_or_vlm":False})


if __name__=="__main__":main()
