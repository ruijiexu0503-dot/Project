#!/usr/bin/env python3
"""Build conservative logical cross-page tables from existing page-level tables.

The script never replaces parser output and never fabricates a cross-page bbox.
It groups page-local table segments and retains their page-local geometry.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

from bs4 import BeautifulSoup


CONTINUED = re.compile(r"\b(?:continued|cont\.?)(?:\s+on\s+next\s+page)?\b", re.I)
NEXT_PAGE = re.compile(r"\bcontinued\s+on\s+next\s+page\b", re.I)


def rows_from_table(table_html: str) -> list[list[str]]:
    soup = BeautifulSoup(table_html, "html.parser")
    return [[cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"], recursive=False)] for row in soup.find_all("tr")]


def table_html(rows: list[list[str]]) -> str:
    body = []
    for row_index, row in enumerate(rows):
        tag = "th" if row_index == 0 else "td"
        body.append("<tr>" + "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in row) + "</tr>")
    return "<table>" + "".join(body) + "</table>"


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def header_signature(rows: list[list[str]]) -> list[str]:
    return [norm(cell) for cell in rows[0]] if rows else []


def sentence_complete(text: str) -> bool:
    return bool(re.search(r"[.!?][\"')\]]?$", text.strip()))


def lowercase_start(text: str) -> bool:
    first = next((char for char in text.strip() if char.isalpha()), "")
    return bool(first and first.islower())


def page_tables(record: dict) -> list[dict]:
    elements = sorted(record["elements"], key=lambda item: item.get("reading_order", 0))
    result = []
    for index, element in enumerate(elements):
        if element.get("label") != "tab":
            continue
        before = elements[index - 1] if index > 0 and elements[index - 1].get("label") == "cap" else None
        after = elements[index + 1] if index + 1 < len(elements) and elements[index + 1].get("label") == "cap" else None
        rows = rows_from_table(element.get("text", ""))
        result.append({
            "page": record["page"],
            "page_id": record["page_id"],
            "source_reading_order": element.get("reading_order"),
            "bbox": element.get("bbox"),
            "image_size": record.get("run_summary", {}).get("image_size"),
            "caption_before": before.get("text") if before else None,
            "caption_after": after.get("text") if after else None,
            "continues_from_previous": bool(before and CONTINUED.search(before.get("text", ""))),
            "continues_to_next": bool(after and NEXT_PAGE.search(after.get("text", ""))),
            "rows": rows,
            "header_signature": header_signature(rows),
        })
    return result


def x_similarity(left: dict, right: dict) -> float:
    lw = left.get("image_size", [1, 1])[0] or 1
    rw = right.get("image_size", [1, 1])[0] or 1
    la, lb = left["bbox"][0] / lw, left["bbox"][2] / lw
    ra, rb = right["bbox"][0] / rw, right["bbox"][2] / rw
    return max(0.0, min(lb, rb) - max(la, ra)) / max(1e-9, min(lb - la, rb - ra))


def can_link(left: dict, right: dict) -> bool:
    return (
        right["page"] == left["page"] + 1
        and left["continues_to_next"]
        and right["continues_from_previous"]
        and left["header_signature"] == right["header_signature"]
        and x_similarity(left, right) >= 0.85
    )


def assemble(segments: list[dict]) -> tuple[list[list[str]], list[dict]]:
    combined = [row[:] for row in segments[0]["rows"]]
    seams = []
    for previous, current in zip(segments, segments[1:]):
        incoming = [row[:] for row in current["rows"]]
        repeated_header_removed = bool(incoming and header_signature(incoming) == previous["header_signature"])
        if repeated_header_removed:
            incoming = incoming[1:]
        merged = False
        reason = None
        if combined and incoming and len(combined[-1]) == len(incoming[0]):
            pairs = list(zip(combined[-1], incoming[0]))
            if any(lowercase_start(new) and not sentence_complete(old) for old, new in pairs if new):
                combined[-1] = [f"{old.rstrip()} {new.lstrip()}".strip() for old, new in pairs]
                incoming = incoming[1:]
                merged = True
                reason = "lowercase continuation after incomplete preceding cell"
        combined.extend(incoming)
        seams.append({
            "from_page": previous["page"],
            "to_page": current["page"],
            "repeated_header_removed": repeated_header_removed,
            "first_row_merged_with_previous_last_row": merged,
            "merge_reason": reason,
            "x_geometry_similarity": round(x_similarity(previous, current), 4),
        })
    return combined, seams


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages-jsonl", type=Path, required=True)
    parser.add_argument("--audit-assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = [json.loads(line) for line in args.pages_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    segments = [table for record in records for table in page_tables(record)]
    segments.sort(key=lambda item: (item["page"], item["source_reading_order"]))
    chains, used = [], set()
    for index, segment in enumerate(segments):
        if index in used:
            continue
        chain = [segment]
        cursor = index
        while cursor + 1 < len(segments) and can_link(chain[-1], segments[cursor + 1]):
            cursor += 1
            used.add(cursor)
            chain.append(segments[cursor])
        if len(chain) > 1:
            chains.append(chain)

    outputs, cards = [], []
    for chain_index, chain in enumerate(chains):
        rows, seams = assemble(chain)
        logical_id = f"cross_page_table_{chain_index:03d}"
        payload = {
            "logical_table_id": logical_id,
            "pages": [segment["page"] for segment in chain],
            "source_segments": [{key: value for key, value in segment.items() if key != "rows"} for segment in chain],
            "geometry_members": [{"page": segment["page"], "bbox": segment["bbox"], "bbox_source": "dolphin_page_table"} for segment in chain],
            "seams": seams,
            "assembled_rows": rows,
            "assembled_html": table_html(rows),
            "geometry_policy": "page-local members preserved; no cross-page union bbox",
            "production_modified": False,
        }
        outputs.append(payload)
        page_visuals = []
        for segment in chain:
            page = segment["page"]
            image_tags = []
            for suffix in ("source", "dolphin_layout"):
                source = args.audit_assets / f"page_{page:04d}_{suffix}.png"
                if source.exists():
                    target = args.output / source.name
                    shutil.copy2(source, target)
                    image_tags.append(f"<img src='{target.name}'>")
            visual_body = "".join(image_tags) or "<p>Overlay not copied for this chain; logical output remains available below.</p>"
            page_visuals.append(f"<div><h3>Page {page}</h3>{visual_body}</div>")
        cards.append(f"<section><h2>{logical_id}: pages {'–'.join(map(str, payload['pages']))}</h2><pre>{html.escape(json.dumps(seams, ensure_ascii=False, indent=2))}</pre><div class='pages'>{''.join(page_visuals)}</div><h3>Reconstructed logical table</h3>{payload['assembled_html']}</section>")

    with (args.output / "cross_page_tables.jsonl").open("w", encoding="utf-8") as handle:
        for payload in outputs:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    summary = {"candidate_table_segments": len(segments), "accepted_cross_page_chains": len(outputs), "pages_in_chains": sum(len(item["pages"]) for item in outputs), "production_modified": False}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    style = "<style>body{font:14px/1.45 system-ui;background:#0b1220;color:#eef4ff}header,section{max-width:1700px;margin:18px auto;background:#142138;padding:18px}.pages{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.pages img{width:100%;display:block;margin:8px 0;background:white}table{border-collapse:collapse;width:100%;background:white;color:#111}td,th{border:1px solid #555;padding:8px;vertical-align:top}pre{white-space:pre-wrap}@media(max-width:1000px){.pages{grid-template-columns:1fr}}</style>"
    report = f"<!doctype html><meta charset='utf-8'><title>Cross-page table shadow assembly</title>{style}<header><h1>Cross-page table shadow assembly</h1><p>Existing Dolphin output only. Page-local geometry is retained; no production output is changed.</p><pre>{html.escape(json.dumps(summary, indent=2))}</pre></header>{''.join(cards)}"
    (args.output / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
