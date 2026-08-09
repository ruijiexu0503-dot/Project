from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from .config import load_config
from .hierarchical_visualize import build as build_visualization
from .io_utils import read_jsonl, write_jsonl
from .semantic_pipeline import run_full_semantic_graph, run_semantic_pilot
from .visualize import build_visualization as build_pilot_visualization


COPY_FILES = (
    "document_nodes.jsonl", "section_nodes.jsonl", "structural_edges.jsonl",
    "multimodal_structural_edges.jsonl", "visual_nodes.jsonl", "graph.json",
)


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(value).name)


def _materialize(source: Path, comparison: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(comparison / "node_enrichment_comparison.jsonl")
    candidates = {row["node_id"]: row for row in rows if row.get("status") == "ok"}
    original = read_jsonl(source / "evidence_nodes.jsonl")
    enriched = []
    for node in original:
        updated = dict(node)
        row = candidates.get(node["node_id"])
        # Preserve coverage when a comparative enrichment call was malformed.
        # The semantic runner may retry these nodes, while a usable Qwen2.5
        # baseline prevents one bad node from blocking an entire document.
        fields = row["qwen3_5_candidate"] if row else {
            "base_summary": node.get("base_summary"), "key_points": node.get("key_points", []),
            "keywords": node.get("keywords", []), "entities": node.get("entities", []),
            "discourse_role": node.get("discourse_role"),
            "formula_semantics": node.get("metadata", {}).get("formula_semantics"),
        }
        for name in ("base_summary", "key_points", "keywords", "entities", "discourse_role"):
            updated[name] = fields.get(name)
        metadata = dict(updated.get("metadata", {}))
        if fields.get("formula_semantics") is not None:
            metadata["formula_semantics"] = fields["formula_semantics"]
        metadata["enrichment_comparison_source"] = str(comparison.resolve())
        updated["metadata"] = metadata
        enriched.append(updated)
    write_jsonl(target / "evidence_nodes.jsonl", enriched)

    assignments = source / "hybrid_content_unit_assignments.jsonl"
    if assignments.exists():
        shutil.copy2(assignments, target / assignments.name)
    else:
        unit = f"{source.name}_UNIT_0001"
        write_jsonl(target / "hybrid_content_unit_assignments.jsonl",
                    [{"node_id": n["node_id"], "content_unit_id": unit} for n in enriched])
    for name in COPY_FILES:
        path = source / name
        if path.exists():
            shutil.copy2(path, target / name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build isolated semantics from comparative Qwen3.5 enrichment")
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--model", required=True)
    parser.add_argument("--source-root", default="output/evidence_graph")
    parser.add_argument("--comparison-root", default="output/enrichment_comparisons")
    parser.add_argument("--output-root", default="output/qwen35_semantic_graphs")
    parser.add_argument("--pilot", action="store_true", help="Run only the 20-30 node semantic pilot")
    args = parser.parse_args()

    model_slug = _slug(args.model)
    source = Path(args.source_root) / args.doc_id
    comparison = Path(args.comparison_root) / model_slug / args.doc_id
    graph_root = Path(args.output_root) / model_slug / "evidence_graph"
    target = graph_root / args.doc_id
    status = target / "semantic_full_status.json"
    if not (target / "evidence_nodes.jsonl").exists():
        _materialize(source, comparison, target)

    config = load_config(args.config)
    config["output"]["graph_root"] = str(graph_root.resolve())
    config["embedding"].update(
        enabled=True,
        model="/hkfs/home/project/hk-project-p0025545/dv3352/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
        input_mode="original_plus_summary",
    )
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False, generation_tokens=450,
                                retry_generation_tokens=650)
    config["relations"].update(generation_tokens=550, retry_generation_tokens=750)
    if args.pilot:
        result = run_semantic_pilot(args.doc_id, config)
        review = build_pilot_visualization(args.doc_id, config)
    else:
        result = run_full_semantic_graph(args.doc_id, config)
        review = build_visualization(args.doc_id, config)
    summary = {"doc_id": args.doc_id, "model": args.model, "status": result,
               "review": str(review), "resumed": status.exists()}
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
