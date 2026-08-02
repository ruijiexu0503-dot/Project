from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl, write_jsonl
from .model_benchmark import DOCUMENTS
from .semantic_pipeline import run_full_semantic_graph


COPY_FILES = (
    "document_nodes.jsonl", "section_nodes.jsonl", "structural_edges.jsonl",
    "multimodal_structural_edges.jsonl", "visual_nodes.jsonl", "graph.json",
)


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.rstrip("/").split("/")[-1])


def _prepare_document(source: Path, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(source / "evidence_nodes.jsonl")
    cleaned = []
    for original in nodes:
        node = dict(original)
        node.update(base_summary=None, key_points=[], keywords=[], entities=[], discourse_role=None, embedding=None)
        metadata = dict(node.get("metadata", {}))
        metadata.pop("enrichment", None); metadata.pop("formula_semantics", None)
        node["metadata"] = metadata
        cleaned.append(node)
    write_jsonl(target / "evidence_nodes.jsonl", cleaned)
    assignments = source / "hybrid_content_unit_assignments.jsonl"
    if assignments.exists():
        shutil.copy2(assignments, target / assignments.name)
    else:
        unit = f"{source.name}_UNIT_0001"
        write_jsonl(target / "hybrid_content_unit_assignments.jsonl",
                    [{"node_id": n["node_id"], "content_unit_id": unit} for n in cleaned])
    for name in COPY_FILES:
        path = source / name
        if path.exists(): shutil.copy2(path, target / name)


def main():
    parser = argparse.ArgumentParser(description="Isolated full semantic runs for four representative documents")
    parser.add_argument("--model", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--source-root", default="output/evidence_graph")
    parser.add_argument("--output-root", default="output/model_full_runs")
    parser.add_argument("--document-kind", choices=sorted(DOCUMENTS),
                        help="Run only one representative document")
    parser.add_argument("--reset", action="store_true", help="Recreate isolated inputs; otherwise resume")
    parser.add_argument("--fast-structured", action="store_true",
                        help="Disable thinking and use compact JSON token budgets")
    args = parser.parse_args()
    model_root = Path(args.output_root) / _slug(args.model)
    graph_root = model_root / "evidence_graph"
    source_root = Path(args.source_root)
    selected_documents = ({args.document_kind: DOCUMENTS[args.document_kind]}
                          if args.document_kind else DOCUMENTS)
    for doc_id in selected_documents.values():
        target = graph_root / doc_id
        if args.reset and target.exists(): shutil.rmtree(target)
        if not (target / "evidence_nodes.jsonl").exists():
            _prepare_document(source_root / doc_id, target)
    config = load_config(args.config)
    config["output"]["graph_root"] = str(graph_root.resolve())
    config["enrichment"]["model"] = str(Path(args.model).resolve())
    config["enrichment"]["require_cuda"] = True
    if args.fast_structured:
        config["enrichment"].update(enable_thinking=False, max_new_tokens=768,
                                     generation_tokens=450, retry_generation_tokens=650)
        config["relations"].update(generation_tokens=550, retry_generation_tokens=750)
    results = {}
    for kind, doc_id in selected_documents.items():
        results[kind] = run_full_semantic_graph(doc_id, config)
        (model_root / f"run_summary_{kind}.json").write_text(
            json.dumps(results[kind], indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__": main()
