from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from .config import load_config
from .io_utils import read_json, read_jsonl, write_json

ANAPHOR = re.compile(r"^\s*(?:these|this|those|such|they|it|the former|the latter)\b", re.I)
REFERENCE = re.compile(r"\b(?:Fig(?:ure)?|Table)\.?\s*[0-9IVXLCDM]+\b", re.I)


def diagnose(config: dict, manifest: Path):
    root = Path(config["output"]["graph_root"])
    doc_ids = [x.strip() for x in manifest.read_text(encoding="utf-8").splitlines() if x.strip()]
    if "gw150914_detection" not in doc_ids:
        doc_ids.append("gw150914_detection")
    rows=[]
    for doc_id in doc_ids:
        out=root/doc_id
        if not (out/"evidence_nodes.jsonl").exists():
            rows.append({"doc_id":doc_id,"status":"missing_or_failed"});continue
        nodes=read_jsonl(out/"evidence_nodes.jsonl")
        structural=read_jsonl(out/"structural_edges.jsonl")
        semantic=read_jsonl(out/"semantic_edges.jsonl") if (out/"semantic_edges.jsonl").exists() else []
        pilot_path=out/"pilot_manifest.json"
        stats_path=out/"adjudication_statistics.json"
        if not pilot_path.exists() or not stats_path.exists():
            rows.append({"doc_id":doc_id,"status":"phase1_only","evidence_nodes":len(nodes)})
            continue
        pilot=read_json(pilot_path)
        selected=set(pilot.get("node_ids",[])); selected_nodes=[n for n in nodes if n["node_id"] in selected]
        semantic_pairs={frozenset((e["source"],e["target"])) for e in semantic}
        ordered=sorted(selected_nodes,key=lambda n:n.get("document_order",0))
        missing_anaphora=[]
        for previous,current in zip(ordered,ordered[1:]):
            if (current.get("document_order",0)-previous.get("document_order",0)==1
                    and ANAPHOR.search(current.get("plain_text", ""))
                    and frozenset((previous["node_id"],current["node_id"])) not in semantic_pairs):
                missing_anaphora.append([previous["node_id"],current["node_id"]])
        reference_nodes={e["source"] for e in structural if e["edge_type"] in {"REFERENCES_FIGURE","REFERENCES_TABLE"}}
        unresolved=[n["node_id"] for n in nodes if REFERENCE.search(n.get("original_markdown", "")) and n["node_id"] not in reference_nodes
                    and n.get("evidence_type")!="caption"]
        formulas=[n["node_id"] for n in selected_nodes if n.get("evidence_type")=="formula"]
        semantic_ids={e["source"] for e in semantic}|{e["target"] for e in semantic}
        stats=read_json(stats_path)
        validation=read_json(out/"semantic_validation_report.json") if (out/"semantic_validation_report.json").exists() else {"summary":{}}
        rows.append({"doc_id":doc_id,"status":"complete","evidence_nodes":len(nodes),"pilot_nodes":len(selected_nodes),
            "proposed_edges":stats.get("proposed"),"accepted_edges":len(semantic),
            "acceptance_rate":round(len(semantic)/stats["proposed"],3) if stats.get("proposed") else None,
            "isolated_pilot_nodes":sum(n["node_id"] not in semantic_ids for n in selected_nodes),
            "formula_nodes":len(formulas),"isolated_formula_nodes":sum(x not in semantic_ids for x in formulas),
            "unresolved_visual_references":unresolved,"unlinked_anaphoric_pairs":missing_anaphora,
            "malformed_verification_outputs":validation.get("summary",{}).get("malformed_llm_output_count"),
            "malformed_adjudications":stats.get("malformed")})
    report={"documents":rows,"summary":{"documents_expected":len(doc_ids),
        "documents_complete":sum(r["status"]=="complete" for r in rows),
        "documents_failed":sum(r["status"]!="complete" for r in rows),
        "accepted_edges":sum(r.get("accepted_edges",0) for r in rows)}}
    write_json(root/"corpus_diagnostic_report.json",report)
    cards=[]
    for r in rows:
        if r["status"]!="complete":
            label = "Phase 1 complete; semantic pilot failed" if r["status"] == "phase1_only" else "missing or failed"
            cards.append(f"<tr><td>{html.escape(r['doc_id'])}</td><td colspan='11'>{label}</td></tr>");continue
        cards.append("<tr>"+"".join(f"<td>{html.escape(str(x))}</td>" for x in (r["doc_id"],r["evidence_nodes"],r["pilot_nodes"],r["proposed_edges"],r["accepted_edges"],r["acceptance_rate"],r["isolated_pilot_nodes"],r["formula_nodes"],r["isolated_formula_nodes"],len(r["unresolved_visual_references"]),len(r["unlinked_anaphoric_pairs"]),r["malformed_adjudications"]))+"</tr>")
    page="""<!doctype html><meta charset='utf-8'><title>EvidenceNet corpus diagnostics</title><style>body{font:14px system-ui;margin:28px;background:#0b1020;color:#e9eef9}table{border-collapse:collapse;width:100%}th,td{border:1px solid #31405f;padding:7px;text-align:left}th{position:sticky;top:0;background:#18233a}tr:nth-child(even){background:#111a2d}</style><h1>EvidenceNet corpus pilot diagnostics</h1><table><thead><tr><th>Document</th><th>Evidence</th><th>Pilot</th><th>Proposed</th><th>Accepted</th><th>Rate</th><th>Isolated</th><th>Formula</th><th>Isolated formula</th><th>Unresolved visual refs</th><th>Unlinked anaphora</th><th>Malformed audit</th></tr></thead><tbody>"""+"".join(cards)+"</tbody></table>"
    (root/"corpus_diagnostic_report.html").write_text(page,encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--config",required=True);p.add_argument("--manifest",required=True)
    a=p.parse_args(argv);print(json.dumps(diagnose(load_config(a.config),Path(a.manifest)),indent=2))


if __name__=="__main__": main()
