from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl

REFERENCE = re.compile(r"^\s*\[(\d+)\]\s+")
AFFILIATION = re.compile(r"^\s*\\\(\s*\^\{\d+\}", re.I)
SCIENTIFIC_HEADINGS = re.compile(r"\b(?:abstract|introduction|methods?|results?|discussion|conclusion|references)\b", re.I)


def detect(nodes, sections):
    ordered = sorted(nodes, key=lambda x: x["document_order"])
    section_title = {x["section_id"]: x.get("title", "") for x in sections}
    headings = [section_title.get(x.get("section_id"), "") for x in ordered]
    scientific_score = sum(bool(SCIENTIFIC_HEADINGS.search(x or "")) for x in set(headings))
    refs = []
    for i, node in enumerate(ordered):
        match = REFERENCE.match(node.get("plain_text") or node.get("original_markdown") or "")
        if match: refs.append((i, int(match.group(1))))
    reference_start = None; reference_end = None
    for pos in range(len(refs)-4):
        window = refs[pos:pos+5]
        if all(window[j+1][0] == window[j][0]+1 for j in range(4)):
            reference_start = window[0][0]; break
    if reference_start is not None:
        reference_end = reference_start
        while reference_end + 1 < len(ordered) and REFERENCE.match(
                ordered[reference_end+1].get("plain_text") or ordered[reference_end+1].get("original_markdown") or ""):
            reference_end += 1
    affiliation_start = next((i for i,x in enumerate(ordered)
                              if reference_end is not None and i > reference_end and
                              AFFILIATION.match(x.get("plain_text") or x.get("original_markdown") or "")), None)
    ack_start = next((i for i,x in enumerate(ordered)
                      if "acknowledg" in section_title.get(x.get("section_id"), "").casefold()), None)
    body_end = min(x for x in (ack_start, reference_start) if x is not None)
    rows=[]
    for i,node in enumerate(ordered):
        if i < body_end: region="SCIENTIFIC_BODY"; eligible=True
        elif reference_start is not None and reference_start <= i <= reference_end: region="BIBLIOGRAPHY"; eligible=False
        elif affiliation_start is not None and i >= affiliation_start: region="AFFILIATIONS"; eligible=False
        elif reference_end is not None and i > reference_end: region="AUTHOR_LIST"; eligible=False
        else: region="ACKNOWLEDGMENTS"; eligible=False
        rows.append({"node_id":node["node_id"],"document_order":node["document_order"],
                     "content_region":region,"semantic_eligible":eligible})
    return rows,{"document_schema":"SCIENTIFIC_PAPER" if scientific_score >= 3 and reference_start is not None else "UNCLASSIFIED",
                 "scientific_heading_score":scientific_score,"body_nodes":sum(x["semantic_eligible"] for x in rows),
                 "excluded_nodes":sum(not x["semantic_eligible"] for x in rows),
                 "reference_start_order":ordered[reference_start]["document_order"] if reference_start is not None else None,
                 "reference_end_order":ordered[reference_end]["document_order"] if reference_end is not None else None,
                 "regions":{r:sum(x["content_region"]==r for x in rows) for r in sorted({x["content_region"] for x in rows})}}


def main():
    p=argparse.ArgumentParser();p.add_argument("--doc-id",required=True);p.add_argument("--root",default="output/evidence_graph")
    p.add_argument("--output-root",default="output/semantic_eligibility");a=p.parse_args()
    source=Path(a.root)/a.doc_id; target=Path(a.output_root)/a.doc_id;target.mkdir(parents=True,exist_ok=True)
    rows,summary=detect(read_jsonl(source/"evidence_nodes.jsonl"),read_jsonl(source/"section_nodes.jsonl"))
    write_jsonl(target/"node_eligibility.jsonl",rows);write_json(target/"summary.json",summary);print(json.dumps(summary,indent=2))


if __name__=="__main__":main()
