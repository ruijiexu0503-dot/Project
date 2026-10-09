#!/usr/bin/env python3
"""Publish a compact HTML audit from raw Dolphin-v2 working files."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path


PILOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PILOT_DIR.parents[2]
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=PILOT_DIR / "cases.json")
    parser.add_argument("--work", type=Path, default=PILOT_DIR / "work")
    parser.add_argument("--output", type=Path, default=PILOT_DIR / "output")
    args = parser.parse_args()

    manifest = json.loads(args.cases.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    cases_output = args.output / "cases"
    cases_output.mkdir(parents=True, exist_ok=True)
    cards = []
    summary = {
        "experiment": manifest["experiment"],
        "production_modified": False,
        "published_artifacts_only": True,
        "case_count_requested": len(manifest["cases"]),
        "cases": [],
    }
    for case in manifest["cases"]:
        case_id = case["case_id"]
        case_dir = args.work / case_id
        result_path = case_dir / "output_json" / f"{case_id}.json"
        run_path = case_dir / "run_summary.json"
        if not result_path.exists() or not run_path.exists():
            continue
        elements = json.loads(result_path.read_text(encoding="utf-8"))
        run = json.loads(run_path.read_text(encoding="utf-8"))
        dolphin_overlay = case_dir / "layout_visualization" / f"{case_id}_layout.png"
        dolphin_markdown = case_dir / "markdown" / f"{case_id}.md"
        deepseek_overlay = PROJECT_ROOT / case["deepseek_overlay"]

        published_case = cases_output / case_id
        published_case.mkdir(parents=True, exist_ok=True)
        deepseek_filename = f"deepseek_layout{deepseek_overlay.suffix.lower()}"
        shutil.copy2(dolphin_overlay, published_case / "dolphin_layout.png")
        shutil.copy2(deepseek_overlay, published_case / deepseek_filename)
        shutil.copy2(result_path, published_case / "dolphin_result.json")
        shutil.copy2(dolphin_markdown, published_case / "dolphin_result.md")
        shutil.copy2(run_path, published_case / "case_summary.json")
        source_figures = case_dir / "markdown" / "figures"
        if source_figures.is_dir() and any(source_figures.iterdir()):
            shutil.copytree(source_figures, published_case / "figures", dirs_exist_ok=True)
        previews = []
        for element in elements:
            text = str(element.get("text") or "").replace("\n", " ")
            previews.append(
                f"<tr><td>{element.get('reading_order')}</td><td>{html.escape(str(element.get('label')))}</td>"
                f"<td><code>{html.escape(str(element.get('bbox')))}</code></td><td>{html.escape(text[:260])}</td></tr>"
            )
        focus = ", ".join(case["audit_focus"])
        cards.append(f"""
        <section><h2>{html.escape(case_id)}</h2>
        <p><b>Type:</b> {html.escape(case['document_type'])} · <b>Focus:</b> {html.escape(focus)} · <b>Dolphin elements:</b> {len(elements)} · <b>Runtime:</b> {run['elapsed_seconds']}s</p>
        <div class="images"><figure><img src="cases/{case_id}/{deepseek_filename}"><figcaption>Existing DeepSeekOCR2 / current provenance view</figcaption></figure>
        <figure><img src="cases/{case_id}/dolphin_layout.png"><figcaption>Dolphin-v2 layout + reading-order indices</figcaption></figure></div>
        <p><a href="cases/{case_id}/dolphin_result.md">Dolphin Markdown</a> · <a href="cases/{case_id}/dolphin_result.json">Dolphin JSON</a> · <a href="cases/{case_id}/case_summary.json">case summary</a></p>
        <details><summary>Dolphin elements in predicted reading order</summary><table><thead><tr><th>#</th><th>label</th><th>bbox</th><th>content preview</th></tr></thead><tbody>{''.join(previews)}</tbody></table></details>
        </section>""")
        summary["cases"].append(run)

    report = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dolphin-v2 vs DeepSeekOCR2 parsing pilot</title>
    <style>body{{margin:20px;background:#0c1422;color:#eaf0fa;font:14px/1.5 system-ui,sans-serif}}header,section{{max-width:1700px;margin:18px auto;padding:18px;background:#172235;border:1px solid #34445e;border-radius:12px}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}figure{{margin:0}}img{{display:block;width:100%;height:auto;background:#fff}}figcaption{{padding:7px;text-align:center;color:#b9c7da}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #34445e;padding:7px;text-align:left;vertical-align:top}}details{{margin-top:14px}}a,code{{color:#bdd1ff}}@media(max-width:900px){{.images{{grid-template-columns:1fr}}}}</style></head><body>
    <header><h1>Dolphin-v2 vs DeepSeekOCR2 · cross-document parsing pilot</h1><p>Published audit artifacts only. Raw official-model output and checkpoints remain in the separate work directory.</p></header>{''.join(cards)}</body></html>"""
    summary["case_count_completed"] = len(summary["cases"])
    (args.output / "dolphin_v2_vs_deepseekocr2_report.html").write_text(report, encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(args.cases, args.output / "manifest.json")


if __name__ == "__main__":
    main()
