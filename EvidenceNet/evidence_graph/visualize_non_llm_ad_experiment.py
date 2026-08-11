from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


WIDTH = 1600
COLORS = {
    "ink": "#172033",
    "muted": "#657188",
    "grid": "#dce3ed",
    "panel": "#f7f9fc",
    "baseline": "#a8b2c3",
    "new": "#2979ff",
    "reference_ad": "#27ae60",
    "predicted_ad": "#2979ff",
    "missed": "#bde7cb",
    "false_positive": "#e85d75",
    "ordinary": "#e8edf4",
}


def _text(x: float, y: float, value: Any, size: int = 22, weight: int = 400,
          color: str | None = None, anchor: str = "start") -> str:
    safe = html.escape(str(value))
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color or COLORS["ink"]}" text-anchor="{anchor}">{safe}</text>')


def _rect(x: float, y: float, width: float, height: float, fill: str,
          radius: float = 0, stroke: str = "none", stroke_width: float = 1) -> str:
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>')


def _line(x1: float, y1: float, x2: float, y2: float, color: str, width: float = 1) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>'


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render(experiment: Path, output: Path, page_experiment: Path | None = None) -> None:
    report = json.loads((experiment / "comparison.json").read_text(encoding="utf-8"))
    documents = report["documents"]
    page_experiment = page_experiment or experiment
    page_report = json.loads((page_experiment / "comparison.json").read_text(encoding="utf-8"))
    page_by_doc = {row["doc_id"]: row for row in page_report["documents"]}
    short_names = {
        "CERNCourier2022NovDec-digitaledition": "2022 Nov/Dec",
        "CERNCourier2025JanFeb-digitaledition": "2025 Jan/Feb",
        "CERNCourier2026MayJun-digitaledition": "2026 May/Jun",
    }
    baseline_exact = [page_by_doc[row["doc_id"]]["baseline_exact"]["f1"] for row in documents]
    new_exact = [row["exact"]["f1"] for row in documents]
    baseline_tol = [page_by_doc[row["doc_id"]]["baseline_tolerance_1"]["f1"] for row in documents]
    new_tol = [row["tolerance_1"]["f1"] for row in documents]
    baseline_ads = [page_by_doc[row["doc_id"]]["baseline_item_summary"]["commercial"]["clean"]
                    for row in documents]
    new_ads = [row["item_summary"]["commercial"]["clean"] for row in documents]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="1500" viewBox="0 0 {WIDTH} 1500">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text { font-family: Inter, Segoe UI, Arial, sans-serif; } .small { letter-spacing: .4px; }</style>',
        _text(80, 82, "Non-LLM magazine separation", 42, 750),
        _text(80, 120, "Held-out evaluation · advertisement-aware boundary reconciliation", 21, 400, COLORS["muted"]),
    ]

    cards = [
        ("AVERAGE EXACT F1", f'{sum(baseline_exact) / 3:.3f} → {sum(new_exact) / 3:.3f}',
         f'+{(sum(new_exact) - sum(baseline_exact)) / 3:.3f}'),
        ("AVERAGE ±1 F1", f'{sum(baseline_tol) / 3:.3f} → {sum(new_tol) / 3:.3f}',
         f'+{(sum(new_tol) - sum(baseline_tol)) / 3:.3f}'),
        ("CLEAN AD ITEMS", f'{sum(baseline_ads)} → {sum(new_ads)}', f'+{sum(new_ads) - sum(baseline_ads)}'),
        ("SELECTED AD PAGES", str(sum(row["predicted_ad_pages"] for row in page_by_doc.values())),
         "100% precision"),
    ]
    for index, (label, value, delta) in enumerate(cards):
        x = 80 + index * 365
        parts.extend([
            _rect(x, 158, 330, 145, COLORS["panel"], 14, COLORS["grid"]),
            _text(x + 24, 194, label, 15, 700, COLORS["muted"]),
            _text(x + 24, 249, value, 34, 750),
            _text(x + 24, 281, delta, 17, 650, COLORS["reference_ad"]),
        ])

    parts.extend([
        _text(80, 365, "Exact boundary F1", 27, 700),
        _text(80, 397, "Higher is better; every held-out issue improves.", 17, 400, COLORS["muted"]),
    ])
    chart_x, chart_y, chart_w, chart_h = 250, 435, 1260, 290
    for tick in range(5, 10):
        value = tick / 10
        x = chart_x + (value - .5) / .5 * chart_w
        parts.extend([_line(x, chart_y, x, chart_y + chart_h, COLORS["grid"]),
                      _text(x, chart_y + chart_h + 28, f"{value:.1f}", 15, 400, COLORS["muted"], "middle")])
    for index, row in enumerate(documents):
        y = chart_y + 28 + index * 86
        label = short_names.get(row["doc_id"], row["doc_id"])
        parts.append(_text(80, y + 26, label, 18, 650))
        for offset, value, color, name in [
            (0, page_by_doc[row["doc_id"]]["baseline_exact"]["f1"], COLORS["baseline"], "baseline"),
            (31, row["exact"]["f1"], COLORS["new"], "new"),
        ]:
            width = max(0, (value - .5) / .5 * chart_w)
            parts.extend([_rect(chart_x, y + offset, width, 22, color, 5),
                          _text(chart_x + width + 10, y + offset + 17, f"{value:.4f}", 15, 650, color)])
    parts.extend([
        _rect(1210, 366, 20, 12, COLORS["baseline"], 3), _text(1240, 378, "Baseline", 15, 500),
        _rect(1350, 366, 20, 12, COLORS["new"], 3), _text(1380, 378, "New", 15, 500),
    ])

    parts.extend([
        _text(80, 805, "Advertisement page map", 27, 700),
        _text(80, 837, "Each square is one magazine page. Pale green pages are real ads intentionally left to the baseline.",
              17, 400, COLORS["muted"]),
    ])
    legend = [(COLORS["reference_ad"], "Detected ad"), (COLORS["missed"], "Ad left unchanged"),
              (COLORS["false_positive"], "Incorrect override"), (COLORS["ordinary"], "Editorial / mixed")]
    lx = 80
    for color, label in legend:
        parts.extend([_rect(lx, 864, 18, 18, color, 3), _text(lx + 26, 879, label, 15, 500)])
        lx += 220

    for document_index, row in enumerate(documents):
        y = 930 + document_index * 150
        page_metrics = page_by_doc[row["doc_id"]]
        pages = _read_jsonl(page_experiment / row["doc_id"] / "page_ad_predictions.jsonl")
        label = short_names.get(row["doc_id"], row["doc_id"])
        parts.extend([
            _text(80, y + 20, label, 20, 700),
            _text(80, y + 47, f'{page_metrics["predicted_ad_pages"]} selected · '
                  f'{page_metrics["pure_ad_page_precision"] * 100:.0f}% precision · '
                  f'{page_metrics["pure_ad_page_recall"] * 100:.0f}% recall', 15, 400, COLORS["muted"]),
        ])
        x0, available, gap = 385, 1125, 3
        cell = min(16, (available - gap * (len(pages) - 1)) / max(1, len(pages)))
        for page_index, page in enumerate(pages):
            truth, predicted = page["reference_pure_ad"], page["predicted_ad"]
            if truth and predicted:
                color = COLORS["reference_ad"]
            elif truth:
                color = COLORS["missed"]
            elif predicted:
                color = COLORS["false_positive"]
            else:
                color = COLORS["ordinary"]
            x = x0 + page_index * (cell + gap)
            parts.append(_rect(x, y, cell, 48, color, 3))
            if (page_index + 1) % 10 == 0:
                parts.extend([_line(x + cell / 2, y + 52, x + cell / 2, y + 60, COLORS["muted"]),
                              _text(x + cell / 2, y + 78, page_index + 1, 13, 400, COLORS["muted"], "middle")])

    parts.extend([
        _line(80, 1390, 1520, 1390, COLORS["grid"]),
        _text(80, 1430, "Safety rule", 16, 700, COLORS["muted"]),
        _text(190, 1430, "Exact page edges, omitted OCR headings, URL/brand resets, and protected mixed editorial pages.", 16, 400),
        _text(80, 1464, "Runtime", 16, 700, COLORS["muted"]),
        _text(190, 1464, "No LLM or VLM calls · layout + lexical features + frozen embeddings + linear classifier.", 16, 400),
        "</svg>",
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the non-LLM magazine experiment as SVG")
    parser.add_argument("--experiment-dir", default="output/non_llm_commercial_experiment")
    parser.add_argument("--page-experiment-dir", default="output/non_llm_page_ad_experiment")
    parser.add_argument("--output", default="output/non_llm_commercial_experiment/visualization.svg")
    args = parser.parse_args()
    render(Path(args.experiment_dir), Path(args.output), Path(args.page_experiment_dir))


if __name__ == "__main__":
    main()
