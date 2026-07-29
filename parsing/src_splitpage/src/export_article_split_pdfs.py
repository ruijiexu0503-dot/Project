#!/usr/bin/env python3
"""Export one PDF per article/subdocument range from article_split_plan.json."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import fitz


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_name(text: Any, fallback: str) -> str:
    value = str(text or "").strip() or fallback
    value = re.sub(r"[^\w.\-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("._")
    return value[:90] or fallback


def find_source_pdf(doc_id: str, split_pages_root: Path) -> Path:
    doc_dir = split_pages_root / doc_id
    manifest_path = doc_dir / "split_manifest.json"

    if manifest_path.exists():
        manifest = load_json(manifest_path)
        output_pdf = manifest.get("output_pdf")
        if output_pdf and Path(output_pdf).exists():
            return Path(output_pdf)

    split_pdf = doc_dir / f"{doc_id}_split.pdf"
    if split_pdf.exists():
        return split_pdf

    unsplit_pdf = doc_dir / f"{doc_id}.pdf"
    if unsplit_pdf.exists():
        return unsplit_pdf

    pdfs = sorted(doc_dir.glob("*.pdf"))
    if pdfs:
        return pdfs[0]

    raise FileNotFoundError(f"No source PDF found for {doc_id} under {doc_dir}")


def export_range(
    src_pdf: Path,
    dst_pdf: Path,
    page_start: int,
    page_end: int,
    start_y_norm: float | None = None,
    end_y_norm: float | None = None,
) -> int:
    with fitz.open(str(src_pdf)) as src:
        page_count = len(src)
        start = max(0, int(page_start))
        end = min(page_count - 1, int(page_end))

        if start > end:
            raise ValueError(
                f"Invalid page range {page_start}-{page_end} for {src_pdf} with {page_count} pages"
            )

        if start_y_norm in (None, 0, 0.0) and end_y_norm is None:
            out = fitz.open()
            out.insert_pdf(src, from_page=start, to_page=end)
        else:
            out = fitz.open()
            for page_no in range(start, end + 1):
                src_page = src[page_no]
                clip = fitz.Rect(src_page.rect)

                if page_no == start and start_y_norm is not None:
                    clip.y0 = src_page.rect.y0 + max(0.0, min(0.98, float(start_y_norm))) * src_page.rect.height
                if page_no == end and end_y_norm is not None:
                    clip.y1 = src_page.rect.y0 + max(0.02, min(1.0, float(end_y_norm))) * src_page.rect.height

                if clip.y1 <= clip.y0:
                    continue

                out_page = out.new_page(width=clip.width, height=clip.height)
                out_page.show_pdf_page(out_page.rect, src, page_no, clip=clip)

            if len(out) == 0:
                raise ValueError(
                    f"Empty clipped range for {src_pdf}: pages {page_start}-{page_end}, "
                    f"start_y_norm={start_y_norm}, end_y_norm={end_y_norm}"
                )

        dst_pdf.parent.mkdir(parents=True, exist_ok=True)
        out.save(str(dst_pdf))
        out.close()
        return end - start + 1


def export_plan(plan_path: Path, split_pages_root: Path, out_root: Path, include_non_export: bool) -> list[str]:
    plan = load_json(plan_path)
    doc_id = plan["doc_id"]
    src_pdf = find_source_pdf(doc_id, split_pages_root)
    doc_out_dir = out_root / doc_id
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    rows = ["doc_id\tsubdoc_id\texport\tpage_range\tpage_region\tpage_count\ttitle\tpdf_path"]
    exported = 0

    for idx, subdoc in enumerate(plan.get("subdocuments") or [], start=1):
        should_export = bool(subdoc.get("export", True))
        if not should_export and not include_non_export:
            continue

        page_start = int(subdoc["page_start"])
        page_end = int(subdoc["page_end"])
        start_y_norm = subdoc.get("start_y_norm")
        end_y_norm = subdoc.get("end_y_norm")
        title = subdoc.get("title") or subdoc.get("type") or "article"
        subdoc_id = subdoc.get("subdoc_id") or f"article_subdoc_{idx:03d}"
        human_range = f"{page_start + 1}-{page_end + 1}"
        if (start_y_norm not in (None, 0, 0.0)) or end_y_norm is not None:
            page_region = f"y={float(start_y_norm or 0.0):.3f}-{float(end_y_norm or 1.0):.3f}"
        else:
            page_region = "full"
        filename = f"{idx:03d}_{human_range}_{safe_name(title, subdoc_id)}.pdf"
        dst_pdf = doc_out_dir / filename

        page_count = export_range(
            src_pdf,
            dst_pdf,
            page_start,
            page_end,
            start_y_norm=start_y_norm,
            end_y_norm=end_y_norm,
        )
        exported += 1
        rows.append(
            "\t".join(
                [
                    doc_id,
                    str(subdoc_id),
                    str(should_export).lower(),
                    human_range,
                    page_region,
                    str(page_count),
                    str(title or ""),
                    str(dst_pdf),
                ]
            )
        )

    summary_path = doc_out_dir / "article_pdf_ranges.tsv"
    summary_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"[OK] {doc_id}: exported {exported} PDF(s) from {src_pdf}")
    print(f"[OK] summary: {summary_path}")
    return rows[1:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-root", default="output/article_split_plans")
    parser.add_argument("--split-pages-root", default="output/split_pages")
    parser.add_argument("--out-root", default="output/article_split_pdfs")
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--include-non-export", action="store_true")
    args = parser.parse_args()

    plan_root = Path(args.plan_root)
    split_pages_root = Path(args.split_pages_root)
    out_root = Path(args.out_root)

    if args.doc_id:
        plan_paths = [plan_root / args.doc_id / "article_split_plan.json"]
    else:
        plan_paths = sorted(plan_root.glob("*/article_split_plan.json"))

    if not plan_paths:
        raise SystemExit(f"No article_split_plan.json files found under {plan_root}")

    all_rows = ["doc_id\tsubdoc_id\texport\tpage_range\tpage_region\tpage_count\ttitle\tpdf_path"]
    for plan_path in plan_paths:
        if not plan_path.exists():
            print(f"[WARN] missing plan: {plan_path}")
            continue
        all_rows.extend(
            export_plan(
                plan_path=plan_path,
                split_pages_root=split_pages_root,
                out_root=out_root,
                include_non_export=args.include_non_export,
            )
        )

    out_root.mkdir(parents=True, exist_ok=True)
    combined = out_root / "article_pdf_ranges.tsv"
    combined.write_text("\n".join(all_rows) + "\n", encoding="utf-8")
    print(f"[DONE] combined summary: {combined}")


if __name__ == "__main__":
    main()
