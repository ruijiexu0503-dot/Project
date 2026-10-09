#!/usr/bin/env python3
"""Validate and render the isolated Dolphin-v2/DeepSeekOCR2 comparison."""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path


EXPECTED_DOCS = {
    "cladmag_2025_h2": {"page_0037", "page_0089"},
    "dlrmagazine_176_en": {"page_0015", "page_0017"},
    "cern_courier_2022_nov_dec": {"page_0009", "page_0011"},
    "cern_courier_2025_jan_feb": {"page_0004", "page_0009"},
    "cern_courier_2026_may_jun": {"page_0004", "page_0011"},
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_parser(root: Path, parser_name: str):
    prepared = root / "prepared" / parser_name
    unit_root = root / "evidence_units" / parser_name
    graph_root = root / "evidence_nodes" / parser_name
    manifest = load_json(prepared / "pipeline_manifest.json")
    manifest_pages = {
        row["document_id"]: set(row.get("pages") or []) for row in manifest.get("documents") or []
    }
    errors = []
    pages = []
    for doc_id, expected_pages in EXPECTED_DOCS.items():
        found = manifest_pages.get(doc_id, set())
        if found != expected_pages:
            errors.append({"kind": "manifest_pages", "document_id": doc_id,
                           "expected": sorted(expected_pages), "found": sorted(found)})
        node_rows = load_jsonl(graph_root / doc_id / "evidence_nodes.jsonl")
        nodes_by_page = Counter(str(row.get("page") or row.get("page_id")) for row in node_rows)
        for page in sorted(expected_pages):
            aligned_path = prepared / "aligned_json" / doc_id / f"{page}.json"
            assembly = unit_root / doc_id / page / "evidence_unit_assembly.json"
            validation = unit_root / doc_id / page / "validation.json"
            if not aligned_path.exists():
                errors.append({"kind": "missing_aligned", "document_id": doc_id, "page": page})
                continue
            payload = load_json(aligned_path)
            valid = validation.exists() and bool(load_json(validation).get("valid"))
            if not assembly.exists() or not valid:
                errors.append({"kind": "invalid_evidence_unit", "document_id": doc_id, "page": page,
                               "assembly_exists": assembly.exists(), "validation_valid": valid})
            parsed = load_json(assembly) if assembly.exists() else {}
            items = parsed.get("content_items") or []
            pages.append({
                "document_id": doc_id,
                "page": page,
                "aligned_blocks": len(payload.get("aligned_blocks") or []),
                "blocks_with_geometry": sum(bool(b.get("bbox") or b.get("geometry_members"))
                                            for b in payload.get("aligned_blocks") or []),
                "evidence_nodes": nodes_by_page.get(page, 0),
                "content_items": len(items),
                "evidence_units": sum(len(item.get("evidence_units") or []) for item in items),
                "unit_validation_valid": valid,
            })
    return {"parser": parser_name, "pages": pages, "errors": errors,
            "totals": {key: sum(row[key] for row in pages) for key in
                       ("aligned_blocks", "blocks_with_geometry", "evidence_nodes", "content_items", "evidence_units")}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    matched = load_json(root / "prepared" / "matched_input_summary.json")
    results = {name: summarize_parser(root, name) for name in ("dolphin", "deepseek")}
    errors = [error for result in results.values() for error in result["errors"]]
    summary = {
        "experiment": "dolphin_v2_vs_deepseekocr2_matched_isolated_v1",
        "production_modified": False,
        "documents": len(EXPECTED_DOCS),
        "matched_pages": sum(len(value) for value in EXPECTED_DOCS.values()),
        "input_coordinate_policy": matched.get("coordinate_policy"),
        "parsers": results,
        "valid": not errors,
        "errors": errors,
        "scope_note": "Matched source-page diagnostic; the adapter never changes either parser output.",
    }
    write_json(root / "comparison_summary.json", summary)

    lookup = {(r["document_id"], r["page"]): r for result in results.values() for r in result["pages"]}
    cards = []
    for doc_id, expected_pages in EXPECTED_DOCS.items():
        for page in sorted(expected_pages):
            parser_cards = []
            for name in ("dolphin", "deepseek"):
                row = next((r for r in results[name]["pages"] if r["document_id"] == doc_id and r["page"] == page), {})
                image = root / "evidence_units" / name / doc_id / page / "annotated_page.png"
                rel = image.relative_to(root) if image.exists() else None
                parser_cards.append(
                    f"<article><h3>{html.escape(name)}</h3>"
                    + (f"<img src='{html.escape(str(rel))}'>" if rel else "<p class='bad'>missing overlay</p>")
                    + "<dl>" + "".join(f"<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>"
                                         for k, v in row.items() if k not in {"document_id", "page"}) + "</dl></article>"
                )
            cards.append(f"<section><h2>{html.escape(doc_id)} — {html.escape(page)}</h2><div class='pair'>{''.join(parser_cards)}</div></section>")
    totals = "".join(
        f"<tr><th>{name}</th>" + "".join(f"<td>{result['totals'][key]}</td>" for key in
        ("aligned_blocks", "blocks_with_geometry", "evidence_nodes", "content_items", "evidence_units")) + "</tr>"
        for name, result in results.items()
    )
    report = f"""<!doctype html><html><head><meta charset='utf-8'><title>Dolphin vs DeepSeek</title>
<style>body{{font:14px/1.45 system-ui;background:#edf1f6;color:#162033;margin:24px}}header,section{{max-width:1500px;margin:18px auto;background:white;padding:18px;border-radius:10px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}img{{width:100%;border:1px solid #bcc6d4}}dl{{display:grid;grid-template-columns:180px 1fr}}dt,dd{{padding:3px;margin:0}}table{{border-collapse:collapse}}th,td{{padding:7px 12px;border:1px solid #ccd4df}}.bad{{color:#b00020}}</style></head><body>
<header><h1>Dolphin-v2 vs DeepSeekOCR2 — isolated matched comparison</h1>
<p>Five documents, ten matched source pages. Production was not modified. Valid: <strong>{summary['valid']}</strong>.</p>
<table><tr><th>parser</th><th>aligned blocks</th><th>with geometry</th><th>EvidenceNodes</th><th>content items</th><th>EvidenceUnits</th></tr>{totals}</table>
<p class='bad'>{html.escape(json.dumps(errors, ensure_ascii=False)) if errors else ''}</p></header>{''.join(cards)}</body></html>"""
    (root / "comparison_report.html").write_text(report, encoding="utf-8")
    print(json.dumps({"valid": not errors, "errors": errors, "output": str(root)}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
