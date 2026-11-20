#!/usr/bin/env python3
"""Build disjoint query/target views for every current article/section unit."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def chunks(texts):
    clean = [" ".join((x or "").split()) for x in texts if len((x or "").split()) >= 8]
    if len(clean) < 2:
        text = " ".join(clean)
        clean = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if len(x.split()) >= 5]
    left = "\n".join(clean[::2]); right = "\n".join(clean[1::2])
    return left, right


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-units", type=Path, required=True)
    ap.add_argument("--assignments", type=Path, required=True)
    ap.add_argument("--paper-sections", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    sources = {x["unit_id"]: x for x in read_jsonl(args.source_units)}
    groups = defaultdict(list)
    for row in read_jsonl(args.assignments):
        if row["node_id"] in sources:
            groups[row["article_id"]].append(sources[row["node_id"]])
    records, skipped = [], []
    for article_id, members in groups.items():
        query, target = chunks([x.get("text") for x in members])
        doc_id = members[0]["doc_id"]
        row = {"unit_id": article_id, "doc_id": doc_id, "unit_kind": "magazine_article",
               "member_count": len(members), "query_text": query, "target_text": target}
        (records if min(len(query.split()), len(target.split())) >= 20 else skipped).append(row)
    for section in read_jsonl(args.paper_sections):
        query, target = chunks((section.get("text") or "").splitlines())
        row = {"unit_id": section["unit_id"], "doc_id": section["doc_id"], "unit_kind": "paper_section",
               "member_count": len(section.get("member_node_ids") or []), "query_text": query, "target_text": target}
        (records if min(len(query.split()), len(target.split())) >= 20 else skipped).append(row)
    records.sort(key=lambda x: x["unit_id"])
    with (args.output / "benchmark_units.jsonl").open("w", encoding="utf-8") as stream:
        for row in records: stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"available_units": len(groups) + len(read_jsonl(args.paper_sections)),
               "eligible_units": len(records), "skipped_short_units": len(skipped),
               "magazine_articles": sum(x["unit_kind"] == "magazine_article" for x in records),
               "paper_sections": sum(x["unit_kind"] == "paper_section" for x in records),
               "documents": sorted({x["doc_id"] for x in records}), "skipped": skipped,
               "split_policy": "alternating member blocks; sentence fallback; >=20 words per disjoint side"}
    (args.output / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
