from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

from .canonical_pipeline import materialize_canonical_graph
from .canonical_visualize import build_visualization
from .config import load_config
from .io_utils import write_json


REQUIRED_FILES = {
    "document_nodes.jsonl", "section_nodes.jsonl", "evidence_nodes.jsonl",
    "visual_nodes.jsonl", "structural_edges.jsonl",
}


def _magazine_assignments(graph_root: Path, doc_id: str) -> Path | None:
    candidate = graph_root.parent / "non_llm_commercial_experiment" / doc_id / "assignments.jsonl"
    return candidate if candidate.exists() else None


def materialize_corpus(config: dict) -> dict:
    graph_root = Path(config["output"]["graph_root"])
    canonical_root = Path((config.get("canonicalization") or {}).get("output_root")
                          or graph_root.parent / "canonical_graph")
    documents = []
    failures = []
    for source in sorted(path for path in graph_root.iterdir() if path.is_dir()):
        if not REQUIRED_FILES.issubset({path.name for path in source.iterdir()}):
            continue
        assignment_path = _magazine_assignments(graph_root, source.name)
        try:
            report = materialize_canonical_graph(source.name, config, assignment_path)
            visualization = build_visualization(source.name, config)
            summary = report["canonicalization"]
            validation = report["validation"]
            documents.append({
                "doc_id": source.name,
                "assignment_source": report["assignment_source"],
                "input_evidence": summary["input_evidence_nodes"],
                "canonical_evidence": summary["canonical_evidence_nodes"],
                "multimodal_composites": summary["multimodal_composites"],
                "text_only_tables": summary["text_only_table_composites"],
                "missing_visual_figures": summary["missing_visual_figure_targets"],
                "absorbed_evidence": len(summary["absorbed_evidence_nodes"]),
                "unlinked_visuals": summary["unlinked_visual_nodes"],
                "ambiguous_visual_ids": len(summary["ambiguous_visual_node_ids"]),
                "references": validation["discourse_edge_count"],
                "shadow_references": validation["shadow_discourse_edge_count"],
                "unresolved_cues": validation["unresolved_reference_cues"],
                "structural_edges": validation["structural_edge_count"],
                "semantic_edges": validation["semantic_edge_count"],
                "unresolved_semantic_edges": validation.get("unresolved_semantic_edge_count", 0),
                "valid": validation["error_count"] == 0,
                "errors": validation["error_count"],
                "warnings": validation["warning_count"],
                "html": visualization["output"],
            })
        except Exception as exc:  # Keep the corpus run going and report the exact document.
            failures.append({"doc_id": source.name, "error": f"{type(exc).__name__}: {exc}"})

    totals = {
        "documents": len(documents),
        "valid_documents": sum(row["valid"] for row in documents),
        "failed_documents": len(failures),
        "input_evidence": sum(row["input_evidence"] for row in documents),
        "canonical_evidence": sum(row["canonical_evidence"] for row in documents),
        "multimodal_composites": sum(row["multimodal_composites"] for row in documents),
        "text_only_tables": sum(row["text_only_tables"] for row in documents),
        "missing_visual_figures": sum(row["missing_visual_figures"] for row in documents),
        "absorbed_evidence": sum(row["absorbed_evidence"] for row in documents),
        "references": sum(row["references"] for row in documents),
        "semantic_edges": sum(row["semantic_edges"] for row in documents),
        "unresolved_semantic_edges": sum(row["unresolved_semantic_edges"] for row in documents),
        "shadow_references": sum(row["shadow_references"] for row in documents),
        "unresolved_cues": sum(row["unresolved_cues"] for row in documents),
        "ambiguous_visual_ids": sum(row["ambiguous_visual_ids"] for row in documents),
    }
    warning_distribution = Counter()
    for row in documents:
        report_path = canonical_root / row["doc_id"] / "canonicalization_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        warning_distribution.update(
            warning["type"] for warning in report["canonicalization"]["warnings"]
        )
    result = {
        "method": "production_canonical_graph_corpus_run_v1",
        "uses_llm_or_vlm": False,
        "production_reference_rules": ["explicit_label"],
        "totals": totals,
        "warning_distribution": dict(sorted(warning_distribution.items())),
        "documents": documents,
        "failures": failures,
    }
    canonical_root.mkdir(parents=True, exist_ok=True)
    write_json(canonical_root / "corpus_report.json", result)
    lines = [
        "# Canonical graph corpus report", "",
        "No LLM/VLM/GPU was used. Raw graphs were preserved.", "",
        "| Document | Evidence | Canonical | Multimodal | REFERENCES | Semantic | Semantic unresolved | Ref shadow | Ref unresolved | Valid |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in documents:
        lines.append(
            f"| {row['doc_id']} | {row['input_evidence']} | {row['canonical_evidence']} | "
            f"{row['multimodal_composites']} | {row['references']} | {row['semantic_edges']} | "
            f"{row['unresolved_semantic_edges']} | {row['shadow_references']} | {row['unresolved_cues']} | "
            f"{'PASS' if row['valid'] else 'FAIL'} |"
        )
    if failures:
        lines += ["", "## Failures", ""] + [
            f"- `{row['doc_id']}`: {row['error']}" for row in failures
        ]
    (canonical_root / "corpus_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    cards = "".join(
        f'''<a class="doc" href="{html.escape(row['doc_id'])}/canonical_graph.html">
        <h2>{html.escape(row['doc_id'])}</h2>
        <div class="metrics"><b>{row['canonical_evidence']}</b><span>Evidence</span><b>{row['references']}</b><span>REFERENCES</span><b>{row['semantic_edges']}</b><span>semantic</span><b>{row['unresolved_cues'] + row['unresolved_semantic_edges']}</b><span>unresolved</span></div>
        <p>{row['missing_visual_figures']} missing figure assets · {row['ambiguous_visual_ids']} ambiguous visual IDs · {'PASS' if row['valid'] else 'FAIL'}</p></a>'''
        for row in documents
    )
    index = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Canonical graph corpus</title><style>
    :root{{--bg:#08111f;--panel:#111e31;--line:#2c405e;--text:#edf4ff;--muted:#92a6c2;--accent:#65d4ad}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}}header{{padding:28px 32px;border-bottom:1px solid var(--line);background:#0c1727}}h1{{margin:0 0 7px;font-size:24px}}header p,.doc p{{color:var(--muted)}}main{{padding:24px 32px;display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}}.doc{{display:block;text-decoration:none;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:17px;transition:.15s}}.doc:hover{{border-color:var(--accent);transform:translateY(-2px)}}.doc h2{{font-size:15px;margin:0 0 14px;overflow-wrap:anywhere}}.metrics{{display:grid;grid-template-columns:repeat(4,auto);gap:4px 12px;align-items:end}}.metrics b{{font-size:20px;color:var(--accent)}}.metrics span{{grid-row:2;color:var(--muted);font-size:11px}}.doc p{{margin:13px 0 0}}
    </style></head><body><header><h1>EvidenceNet canonical graph corpus</h1><p>{totals['documents']} documents · {totals['canonical_evidence']:,} canonical Evidence nodes · {totals['references']} production REFERENCES · {totals['semantic_edges']} mapped semantic edges · no new LLM/VLM/GPU run</p></header><main>{cards}</main></body></html>'''
    (canonical_root / "index.html").write_text(index, encoding="utf-8")
    result["index_html"] = str(canonical_root / "index.html")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize all current canonical Evidence graphs")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    result = materialize_corpus(load_config(args.config))
    print(json.dumps({"totals": result["totals"], "failures": result["failures"]}, indent=2))


if __name__ == "__main__":
    main()
