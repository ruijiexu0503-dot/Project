#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))

from offline_citation_graph.registry import CitationRegistry


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(config: dict, output: Path, include_journal_fingerprint: bool) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    registry = CitationRegistry(output / "citation_registry.sqlite", reset=True)
    source_ids: dict[str, str] = {}
    for document in config["documents"]:
        identifiers=[(item["scheme"],item["value"]) for item in document["identifiers"]
                     if include_journal_fingerprint or item["scheme"]!="journal_fingerprint"]
        source_ids[document["slug"]]=registry.ingest_aligned_source(
            PROJECT/document["aligned_dir"],PROJECT/document["pdf"],identifiers,
            document["title"],document.get("year"),document.get("version_label"))
    corpus_ids=set(source_ids.values()); edges=[]; source_summaries={}
    for slug,work_id in source_ids.items():
        target=output/slug; source_summaries[slug]=registry.export(target,work_id)
        edges.extend(edge for edge in rows(target/"citation_edges.jsonl") if edge["target"] in corpus_ids)
    unique={(edge["source"],edge["target"],edge["reference_key"]):edge for edge in edges}
    edges=list(unique.values())
    (output/"cross_document_citation_edges.jsonl").write_text(
        "".join(json.dumps(edge,ensure_ascii=False)+"\n" for edge in edges),encoding="utf-8")
    summary={"documents":len(source_ids),"document_work_ids":source_ids,
             "cross_document_citation_edges":len(edges),"source_summaries":source_summaries,
             "journal_fingerprint_enabled":include_journal_fingerprint,"production_modified":False}
    (output/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    cards=[]
    for edge in edges:
        provenance=edge["provenance"]
        cards.append(f"<section><h2>{html.escape(edge['source'])} → CITES → {html.escape(edge['target'])}</h2>"
                     f"<p>Reference [{html.escape(edge['reference_key'])}] · mentions={edge['mention_count']} · "
                     f"{html.escape(edge['resolution_method'])}</p><pre>{html.escape(provenance['raw_text'])}</pre>"
                     f"<p>{html.escape(provenance['source_page'])} / {html.escape(provenance['source_block_id'])}</p></section>")
    (output/"three_paper_reference_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><style>body{font:15px system-ui;max-width:1100px;margin:30px auto}"
        "section{padding:16px;margin:15px;border-left:5px solid #168f62;background:#eef8f4}pre{white-space:pre-wrap}</style>"
        f"<h1>Three-paper offline citation audit</h1><pre>{html.escape(json.dumps(summary,indent=2))}</pre>"+"".join(cards),encoding="utf-8")
    registry.close()
    return summary


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--config",default=str(ROOT/"config/gw150914_three_paper_pilot.json"))
    parser.add_argument("--output",default=str(ROOT/"output/gw150914_three_paper_pilot"))
    parser.add_argument("--mode",choices=("both","baseline","enhanced"),default="both"); args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding="utf-8")); output=Path(args.output).resolve()
    baseline=(run(config,output/"baseline_exact_doi_arxiv",False) if args.mode in {"both","baseline"}
              else json.loads((output/"baseline_exact_doi_arxiv/summary.json").read_text(encoding="utf-8")))
    enhanced=(run(config,output/"enhanced_exact_bibliographic_identity",True) if args.mode in {"both","enhanced"}
              else json.loads((output/"enhanced_exact_bibliographic_identity/summary.json").read_text(encoding="utf-8")))
    comparison={"baseline":baseline,"enhanced":enhanced,
                "question":"Can the three offline papers be linked using source citation provenance plus exact target identity?",
                "production_modified":False}
    (output/"comparison_summary.json").write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(comparison,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
