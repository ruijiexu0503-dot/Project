#!/usr/bin/env python3
"""Build a read-only Dolphin-v2 vs DeepSeekOCR2 magazine parsing audit."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = PROJECT_ROOT / "EvidenceNet/output/dolphin_deepseek_matched_pipeline_v1"
PDF_PATHS = {
    "cladmag_2025_h2": PROJECT_ROOT / "data/incoming/CLADmag_2025_H2.pdf",
    "dlrmagazine_176_en": PROJECT_ROOT / "data/incoming/DLRmagazine_176_EN.pdf",
    "cern_courier_2022_nov_dec": PROJECT_ROOT / "data/processed/CERNCourier2022NovDec-digitaledition.pdf",
    "cern_courier_2025_jan_feb": PROJECT_ROOT / "data/processed/CERNCourier2025JanFeb-digitaledition.pdf",
    "cern_courier_2026_may_jun": PROJECT_ROOT / "data/processed/CERNCourier2026MayJun-digitaledition.pdf",
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower().replace("\u00ad", "")
    text = re.sub(r"-\s+", "", text)
    return re.findall(r"[^\W_]+", text, flags=re.UNICODE)


def overlap_metrics(reference: str, prediction: str) -> dict:
    ref = Counter(tokens(reference))
    pred = Counter(tokens(prediction))
    overlap = sum((ref & pred).values())
    ref_n, pred_n = sum(ref.values()), sum(pred.values())
    recall = overlap / ref_n if ref_n else None
    precision = overlap / pred_n if pred_n else None
    f1 = None
    if precision is not None and recall is not None and precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "native_tokens": ref_n,
        "parser_tokens": pred_n,
        "overlap_tokens": overlap,
        "token_recall": recall,
        "token_precision": precision,
        "token_f1": f1,
    }


def parser_stats(path: Path, native_text: str) -> dict:
    payload = read_json(path)
    blocks = payload.get("aligned_blocks", [])
    text = "\n".join(
        str(row.get("text") or row.get("markdown") or "")
        for row in blocks
        if row.get("block_type") != "image"
    )
    roles = Counter(str(row.get("role") or row.get("label") or row.get("block_type") or "unknown") for row in blocks)
    bbox_count = sum(isinstance(row.get("bbox"), list) and len(row["bbox"]) == 4 for row in blocks)
    visuals = sum(
        row.get("block_type") == "image" or str(row.get("role") or row.get("label") or "").lower() in {"fig", "figure", "image"}
        for row in blocks
    )
    return {
        "blocks": len(blocks),
        "bbox_blocks": bbox_count,
        "bbox_rate": bbox_count / len(blocks) if blocks else None,
        "visual_blocks": visuals,
        "role_distribution": dict(roles),
        **overlap_metrics(native_text, text),
    }


def fmt(value):
    return "—" if value is None else f"{value:.3f}"


def summarize_counts(counts: Counter) -> dict:
    recall = counts["overlap_tokens"] / counts["native_tokens"] if counts["native_tokens"] else None
    precision = counts["overlap_tokens"] / counts["parser_tokens"] if counts["parser_tokens"] else None
    f1 = 2 * recall * precision / (recall + precision) if recall is not None and precision is not None and recall + precision else None
    return {
        **dict(counts),
        "bbox_rate": counts["bbox_blocks"] / counts["blocks"] if counts["blocks"] else None,
        "token_recall": recall,
        "token_precision": precision,
        "token_f1": f1,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--output", type=Path, default=PROJECT_ROOT / "parsing/audits/dolphin_vs_deepseek_magazines_v1")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.root / "prepared/matched_input_summary.json"
    selected = read_json(summary_path)["comparison_pages"]
    pdfs = {doc_id: fitz.open(path) for doc_id, path in PDF_PATHS.items()}
    pages, cards = [], []
    aggregate = defaultdict(Counter)
    document_aggregate = defaultdict(lambda: defaultdict(Counter))

    for row in selected:
        doc_id, page_id = row["document_id"], row["page"]
        page_number = int(page_id.rsplit("_", 1)[1])
        native_text = pdfs[doc_id][page_number - 1].get_text("text")
        parser_rows = {}
        copied = {}
        for parser in ("dolphin", "deepseek"):
            aligned = args.root / f"prepared/{parser}/aligned_json/{doc_id}/{page_id}.json"
            stats = parser_stats(aligned, native_text)
            # Visuals are stored out-of-band by the DeepSeek adapter, so use
            # the matched manifest's equivalent visual-bundle count for both.
            stats["visual_bundles"] = int(row[parser]["visual_bundles"])
            parser_rows[parser] = stats
            image = args.root / f"evidence_units/{parser}/{doc_id}/{page_id}/annotated_page.png"
            target = args.output / "pages" / f"{doc_id}_{page_id}_{parser}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image, target)
            copied[parser] = target.relative_to(args.output).as_posix()
            for key in ("native_tokens", "parser_tokens", "overlap_tokens", "blocks", "bbox_blocks", "visual_bundles"):
                aggregate[parser][key] += stats[key]
                document_aggregate[doc_id][parser][key] += stats[key]

        page_row = {"document_id": doc_id, "page": page_id, "native_text_characters": len(native_text), **parser_rows}
        pages.append(page_row)
        d, s = parser_rows["dolphin"], parser_rows["deepseek"]
        cards.append(f"""
        <section><h2>{html.escape(doc_id)} · {html.escape(page_id)}</h2>
        <table><thead><tr><th>Parser</th><th>blocks</th><th>bbox</th><th>visuals</th><th>token recall</th><th>token precision</th><th>token F1</th></tr></thead><tbody>
        <tr><td>Dolphin-v2</td><td>{d['blocks']}</td><td>{d['bbox_blocks']}/{d['blocks']}</td><td>{d['visual_bundles']}</td><td>{fmt(d['token_recall'])}</td><td>{fmt(d['token_precision'])}</td><td>{fmt(d['token_f1'])}</td></tr>
        <tr><td>DeepSeekOCR2</td><td>{s['blocks']}</td><td>{s['bbox_blocks']}/{s['blocks']}</td><td>{s['visual_bundles']}</td><td>{fmt(s['token_recall'])}</td><td>{fmt(s['token_precision'])}</td><td>{fmt(s['token_f1'])}</td></tr></tbody></table>
        <div class='images'><figure><img src='{copied['dolphin']}'><figcaption>Dolphin-v2</figcaption></figure><figure><img src='{copied['deepseek']}'><figcaption>DeepSeekOCR2</figcaption></figure></div></section>""")

    totals = {parser: summarize_counts(counts) for parser, counts in aggregate.items()}
    document_totals = {
        doc_id: {parser: summarize_counts(counts) for parser, counts in parser_counts.items()}
        for doc_id, parser_counts in document_aggregate.items()
    }
    summary = {
        "experiment": "dolphin_v2_vs_deepseekocr2_magazine_parser_audit_v1",
        "documents": sorted({row["document_id"] for row in pages}),
        "page_count": len(pages),
        "metric_note": "Token overlap uses born-digital PDF text as a page-level reference; it measures coverage, not reading order or semantic grouping accuracy.",
        "totals": totals,
        "document_totals": document_totals,
        "pages": pages,
        "production_modified": False,
    }
    (args.output / "comparison_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = f"""<!doctype html><html><head><meta charset='utf-8'><title>Dolphin vs DeepSeek magazine audit</title><style>
    body{{font:14px/1.45 system-ui;background:#101827;color:#edf2ff;margin:20px}}header,section{{max-width:1600px;margin:20px auto;background:#1b2638;padding:18px;border-radius:10px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px;border-bottom:1px solid #40506a;text-align:left}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}}figure{{margin:0}}img{{width:100%;background:white}}figcaption{{text-align:center;padding:6px}}pre{{white-space:pre-wrap}}@media(max-width:900px){{.images{{grid-template-columns:1fr}}}}</style></head><body>
    <header><h1>Dolphin-v2 vs DeepSeekOCR2 · five-magazine matched-page audit</h1><p>Same source pages; existing parser outputs only. No model rerun.</p><pre>{html.escape(json.dumps(totals, ensure_ascii=False, indent=2))}</pre></header>{''.join(cards)}</body></html>"""
    (args.output / "comparison_report.html").write_text(report, encoding="utf-8")
    for document in pdfs.values():
        document.close()
    print(json.dumps({"output": str(args.output), "totals": totals}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
