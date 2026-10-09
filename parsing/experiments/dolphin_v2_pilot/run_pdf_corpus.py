#!/usr/bin/env python3
"""Checkpointed full-PDF Dolphin-v2 parsing with compact published output."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import pymupdf
import torch
from PIL import Image


PILOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PILOT_DIR.parents[2]
VENDOR_DIR = PILOT_DIR / "vendor" / "Dolphin"
sys.path.insert(0, str(VENDOR_DIR))

from demo_page import DOLPHIN, process_elements  # noqa: E402
from utils.utils import save_outputs, setup_output_dirs  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def render_page(page: pymupdf.Page, max_side: int = 1600) -> Image.Image:
    scale = max_side / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def publish_document(
    document: dict,
    pdf: pymupdf.Document,
    document_work: Path,
    output_root: Path,
) -> dict:
    document_id = document["document_id"]
    published = output_root / document_id
    published.mkdir(parents=True, exist_ok=True)
    figures_output = published / "figures"
    audit_output = published / "audit_pages"
    audit_output.mkdir(parents=True, exist_ok=True)

    page_records = []
    markdown_pages = []
    labels: Counter[str] = Counter()
    failed_pages = []
    elapsed = 0.0
    audit_cards = []
    audit_pages = set(document.get("audit_pages", []))

    for page_number in range(1, len(pdf) + 1):
        page_id = f"page_{page_number:04d}"
        page_work = document_work / "pages" / page_id
        result_path = page_work / "output_json" / f"{page_id}.json"
        run_path = page_work / "run_summary.json"
        if not result_path.exists() or not run_path.exists():
            failed_pages.append(page_number)
            continue

        elements = json.loads(result_path.read_text(encoding="utf-8"))
        run = json.loads(run_path.read_text(encoding="utf-8"))
        elapsed += float(run.get("elapsed_seconds", 0.0))
        labels.update(run.get("label_distribution", {}))
        page_records.append(
            {
                "document_id": document_id,
                "page": page_number,
                "page_id": page_id,
                "elements": elements,
                "run_summary": run,
            }
        )

        markdown_path = page_work / "markdown" / f"{page_id}.md"
        if markdown_path.exists():
            page_markdown = markdown_path.read_text(encoding="utf-8")
            page_markdown = page_markdown.replace("figures/", f"figures/{page_id}/")
            markdown_pages.append(f"\n\n<!-- page: {page_number} -->\n\n{page_markdown}")
        source_figures = page_work / "markdown" / "figures"
        if source_figures.is_dir() and any(source_figures.iterdir()):
            shutil.copytree(source_figures, figures_output / page_id, dirs_exist_ok=True)

        if page_number in audit_pages:
            source_name = f"{page_id}_source.png"
            overlay_name = f"{page_id}_dolphin_layout.png"
            render_page(pdf[page_number - 1]).save(audit_output / source_name)
            shutil.copy2(
                page_work / "layout_visualization" / f"{page_id}_layout.png",
                audit_output / overlay_name,
            )
            audit_cards.append(
                f"<section><h2>Page {page_number}</h2><div class='images'>"
                f"<figure><img src='audit_pages/{source_name}'><figcaption>Source PDF page</figcaption></figure>"
                f"<figure><img src='audit_pages/{overlay_name}'><figcaption>Dolphin-v2 layout and reading order</figcaption></figure>"
                f"</div><p>{len(elements)} elements · {html.escape(str(run.get('label_distribution', {})))}</p></section>"
            )

    with (published / "pages.jsonl").open("w", encoding="utf-8") as handle:
        for record in page_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    (published / "document.md").write_text("".join(markdown_pages), encoding="utf-8")

    summary = {
        "document_id": document_id,
        "document_type": document["document_type"],
        "input_pdf": document["input_pdf"],
        "total_pages": len(pdf),
        "completed_pages": len(page_records),
        "failed_or_unresolved_pages": failed_pages,
        "element_count": sum(len(record["elements"]) for record in page_records),
        "label_distribution": dict(labels),
        "inference_seconds": round(elapsed, 3),
        "audit_pages": sorted(audit_pages),
        "production_modified": False,
    }
    write_json(published / "summary.json", summary)
    source_metadata = PROJECT_ROOT / document["source_metadata"]
    shutil.copy2(source_metadata, published / "source_metadata.json")
    report = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(document_id)} · Dolphin-v2 audit</title><style>body{{margin:20px;background:#0b1422;color:#eef4ff;font:14px/1.5 system-ui,sans-serif}}header,section{{max-width:1700px;margin:18px auto;padding:18px;background:#152238;border:1px solid #354965;border-radius:12px}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}figure{{margin:0}}img{{display:block;width:100%;background:white}}figcaption{{padding:6px;text-align:center;color:#b8c8dc}}a{{color:#9bc6ff}}@media(max-width:900px){{.images{{grid-template-columns:1fr}}}}</style></head><body><header><h1>{html.escape(document_id)}</h1><p>{len(page_records)}/{len(pdf)} pages completed · {sum(len(record['elements']) for record in page_records)} elements · full parsed content: <a href='document.md'>Markdown</a> · <a href='pages.jsonl'>page JSONL</a> · <a href='summary.json'>summary</a></p></header>{''.join(audit_cards)}</body></html>"""
    (published / "report.html").write_text(report, encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=PILOT_DIR / "government_financial_documents.json")
    parser.add_argument("--model", type=Path, default=PILOT_DIR / "models" / "Dolphin-v2")
    parser.add_argument("--work", type=Path, default=PILOT_DIR / "work" / "government_financial_v1")
    parser.add_argument("--output", type=Path, default=PILOT_DIR / "output" / "government_financial_v1")
    parser.add_argument("--max-batch-size", type=int, default=2)
    parser.add_argument("--document-id")
    parser.add_argument("--page-start", type=int, default=1)
    parser.add_argument("--page-end", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--defer-publish",
        action="store_true",
        help="Write page checkpoints only; publish after all parallel chunks finish.",
    )
    parser.add_argument(
        "--publish-only",
        action="store_true",
        help="Build document and corpus outputs from existing page checkpoints without loading Dolphin.",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    progress_name = f"progress_{args.document_id}.json" if args.document_id else "progress.json"
    progress_path = args.work / progress_name
    progress = (
        json.loads(progress_path.read_text(encoding="utf-8"))
        if progress_path.exists()
        else {"experiment": manifest["experiment"], "documents": {}}
    )

    model = None
    if not args.publish_only:
        print(f"Loading Dolphin-v2 from {args.model}", flush=True)
        model = DOLPHIN(str(args.model))
    corpus_summaries = []

    selected_documents = manifest["documents"]
    if args.document_id:
        selected_documents = [
            document
            for document in selected_documents
            if document["document_id"] == args.document_id
        ]
    if not selected_documents:
        raise SystemExit(f"Unknown document_id: {args.document_id}")

    for document in selected_documents:
        document_id = document["document_id"]
        pdf_path = PROJECT_ROOT / document["input_pdf"]
        document_work = args.work / document_id
        pdf = pymupdf.open(pdf_path)
        progress["documents"].setdefault(document_id, {"total_pages": len(pdf), "pages": {}})

        for page_index in range(len(pdf)) if not args.publish_only else ():
            page_number = page_index + 1
            if page_number < args.page_start:
                continue
            if args.page_end is not None and page_number > args.page_end:
                continue
            page_id = f"page_{page_number:04d}"
            page_work = document_work / "pages" / page_id
            result_path = page_work / "output_json" / f"{page_id}.json"
            if args.resume and result_path.exists():
                print(f"[skip] {document_id} {page_id}", flush=True)
                continue

            setup_output_dirs(str(page_work))
            started = time.time()
            progress["documents"][document_id]["pages"][page_id] = {"status": "running"}
            write_json(progress_path, progress)
            try:
                image = render_page(pdf[page_index])
                assert model is not None
                layout_raw = model.chat("Parse the reading order of this document.", image)
                (page_work / "layout_raw.txt").write_text(layout_raw, encoding="utf-8")
                elements = process_elements(
                    layout_raw, image, model, args.max_batch_size, str(page_work), page_id
                )
                save_outputs(elements, image, page_id, str(page_work), post_process=False)
                labels = Counter(str(element.get("label", "UNKNOWN")) for element in elements)
                run_summary = {
                    "document_id": document_id,
                    "page": page_number,
                    "status": "complete",
                    "elapsed_seconds": round(time.time() - started, 3),
                    "image_size": list(image.size),
                    "element_count": len(elements),
                    "label_distribution": dict(labels),
                }
                write_json(page_work / "run_summary.json", run_summary)
                progress["documents"][document_id]["pages"][page_id] = run_summary
                print(f"[done] {document_id} {page_id}: {len(elements)} elements", flush=True)
            except Exception as exc:
                failure = {
                    "document_id": document_id,
                    "page": page_number,
                    "status": "failed",
                    "error": repr(exc),
                    "elapsed_seconds": round(time.time() - started, 3),
                }
                write_json(page_work / "failure.json", failure)
                progress["documents"][document_id]["pages"][page_id] = failure
                print(f"[failed] {document_id} {page_id}: {exc!r}", flush=True)
            finally:
                write_json(progress_path, progress)
                torch.cuda.empty_cache()

        if not args.defer_publish:
            corpus_summaries.append(
                publish_document(document, pdf, document_work, args.output)
            )
        pdf.close()

    if args.defer_publish:
        progress["status"] = "checkpointed"
        write_json(progress_path, progress)
        return

    all_document_summaries = []
    for document in manifest["documents"]:
        summary_path = args.output / document["document_id"] / "summary.json"
        if summary_path.exists():
            all_document_summaries.append(
                json.loads(summary_path.read_text(encoding="utf-8"))
            )

    corpus_summary = {
        "experiment": manifest["experiment"],
        "documents": all_document_summaries,
        "total_pages": sum(item["total_pages"] for item in all_document_summaries),
        "completed_pages": sum(item["completed_pages"] for item in all_document_summaries),
        "production_modified": False,
    }
    write_json(args.output / "summary.json", corpus_summary)
    shutil.copy2(args.manifest, args.output / "manifest.json")
    links = "".join(
        f"<li><a href='{item['document_id']}/report.html'>{html.escape(item['document_id'])}</a> — {item['completed_pages']}/{item['total_pages']} pages</li>"
        for item in all_document_summaries
    )
    corpus_title = manifest.get("title", "Dolphin-v2 document corpus")
    corpus_description = manifest.get(
        "description",
        "Full-document isolated parsing; no production output was modified.",
    )
    index = f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(corpus_title)}</title><style>body{{max-width:900px;margin:40px auto;background:#0b1422;color:#eef4ff;font:16px/1.6 system-ui}}a{{color:#9bc6ff}}</style></head><body><h1>{html.escape(corpus_title)}</h1><p>{html.escape(corpus_description)}</p><ul>{links}</ul><p><a href='summary.json'>Corpus summary</a> · <a href='manifest.json'>Manifest</a></p></body></html>"""
    (args.output / "index.html").write_text(index, encoding="utf-8")
    progress["status"] = (
        "complete"
        if len(all_document_summaries) == len(manifest["documents"])
        and all(item["completed_pages"] == item["total_pages"] for item in all_document_summaries)
        else "partial"
    )
    write_json(progress_path, progress)


if __name__ == "__main__":
    main()
