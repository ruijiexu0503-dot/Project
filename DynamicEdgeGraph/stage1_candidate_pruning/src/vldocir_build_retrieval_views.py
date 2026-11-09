"""Create additive, type-aware text retrieval views for VL-DocIR canonical nodes.

This adapter deliberately leaves the source node construction, old pilot views, and
all previously frozen embeddings untouched.  There is no length/token-count gate:
short labels, formulae and captions remain eligible when they have textual content.
Pure visual URLs are retained in the canonical universe but deferred from ordinary
text semantic retrieval until a visual/metadata route is added.
"""
from __future__ import annotations
import argparse, json, re, time
from collections import Counter
from pathlib import Path
from .common import sha256, write_jsonl

URL_ONLY = re.compile(r"^(?:https?://|data:image/|//)[^\s]+$", re.I)

def retrieval_text(node: dict) -> str:
    text = str(node.get("text", "")).strip()
    prefix = {"FORMULA": "Formula", "TABLE": "Table", "CAPTION": "Caption"}.get(node.get("node_type"))
    return f"{prefix}: {text}" if prefix else text

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nodes", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    views=[]; audit=[]; node_count=0
    with args.nodes.open() as f:
        for line in f:
            if not line.strip(): continue
            node=json.loads(line); node_count += 1
            nid=node["id"]; raw=str(node.get("text", "")).strip(); typ=node.get("node_type", "OTHER")
            if not raw:
                status, reason = "DEFERRED", "empty_canonical_content"
            elif typ == "IMAGE" and URL_ONLY.fullmatch(raw):
                status, reason = "DEFERRED", "visual_asset_url_without_textual_description"
            else:
                status, reason = "ELIGIBLE", None
            rec={"node_id":nid,"document_id":node["document_id"],"page_number":node["page_number"],
                 "node_type":typ,"status":status,"reason":reason,
                 "retrieval_routes": ["qwen3_0_6b_dense","gte_qwen2_1_5b_dense","bge_en_icl_dense","mxbai_dense","gte_large_dense","bm25"] if status=="ELIGIBLE" else []}
            audit.append(rec)
            if status == "ELIGIBLE":
                views.append({"view_id":f"{nid}::type_aware_text_v1","node_id":nid,
                              "document_id":node["document_id"],"page_number":node["page_number"],
                              "node_type":typ,"view_kind":"type_aware_text_v1",
                              "retrieval_text":retrieval_text(node)})
    write_jsonl(args.output/"retrieval_views.jsonl", views)
    write_jsonl(args.output/"view_eligibility_audit.jsonl", audit)
    summary={"created_at":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "canonical_nodes":node_count,"eligible_nodes":len(views),"deferred_nodes":node_count-len(views),
             "eligible_types":dict(Counter(v["node_type"] for v in views)),
             "deferred_reasons":dict(Counter(x["reason"] for x in audit if x["status"]!="ELIGIBLE")),
             "source_nodes":str(args.nodes.resolve()),"source_nodes_sha256":sha256(args.nodes),
             "policy":"additive type-aware text views; no minimum-token gate; pure visual URLs deferred from text routes"}
    (args.output/"view_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True)+"\n")
    print(json.dumps(summary, sort_keys=True))
if __name__ == "__main__": main()
