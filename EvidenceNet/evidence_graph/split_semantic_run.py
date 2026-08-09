from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .candidate_generator import generate_semantic_candidates
from .comparative_semantic_run import _materialize, _slug
from .config import load_config
from .embeddings import generate_document_embeddings
from .hierarchical_visualize import build as build_visualization
from .io_utils import read_json, read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_verifier import verify_semantic_relations
from .semantic_pipeline import _semantic_stats, _validate_semantic


BGE_M3 = "/hkfs/home/project/hk-project-p0025545/dv3352/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"


def _paths(args):
    slug = _slug(args.model)
    enrichment_slug = _slug(args.enrichment_model or args.model)
    source = Path(args.source_root) / args.doc_id
    comparison = Path(args.comparison_root) / enrichment_slug / args.doc_id
    graph_root = Path(args.output_root) / slug / "evidence_graph"
    target = graph_root / args.doc_id
    return source, comparison, graph_root, target


def _configuration(args, graph_root):
    config = load_config(args.config)
    config["output"]["graph_root"] = str(graph_root.resolve())
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False, generation_tokens=450,
                                retry_generation_tokens=650)
    config["relations"].update(generation_tokens=550, retry_generation_tokens=750)
    config["embedding"].update(enabled=True, model=BGE_M3, input_mode="original_plus_summary")
    return config


def preprocess(args):
    source, comparison, graph_root, target = _paths(args)
    if not (target / "evidence_nodes.jsonl").exists():
        _materialize(source, comparison, target)
    config = _configuration(args, graph_root)
    nodes = read_jsonl(target / "evidence_nodes.jsonl")
    assignments = read_jsonl(target / "hybrid_content_unit_assignments.jsonl")
    unit_by_node = {row["node_id"]: row["content_unit_id"] for row in assignments}
    selected = {node["node_id"] for node in nodes}
    embeddings, metadata = generate_document_embeddings(
        nodes, selected, config["embedding"]["input_mode"], config["embedding"]["model"])
    full_cfg = {**config["candidates"], **config.get("full_semantic", {})}
    candidates = generate_semantic_candidates(nodes, embeddings, full_cfg, unit_by_node)
    write_jsonl(target / "semantic_full_embedding_vectors.jsonl", embeddings)
    write_json(target / "semantic_full_embedding_metadata.json", metadata)
    write_jsonl(target / "semantic_full_candidates.jsonl", candidates)
    result = {"doc_id": args.doc_id, "stage": "cpu_preprocess", "nodes": len(nodes),
              "candidates": len(candidates), "completed_at": datetime.now(timezone.utc).isoformat()}
    write_json(target / "semantic_cpu_preprocess_status.json", result)
    print(json.dumps(result, indent=2), flush=True)


def verify(args):
    _, _, graph_root, target = _paths(args)
    config = _configuration(args, graph_root)
    nodes = read_jsonl(target / "evidence_nodes.jsonl")
    candidates = read_jsonl(target / "semantic_full_candidates.jsonl")
    status_path = target / "semantic_gpu_verify_status.json"
    status = read_json(status_path) if status_path.exists() else {"doc_id": args.doc_id, "verified_groups": []}
    groups = defaultdict(list)
    for candidate in candidates:
        group = (candidate["content_unit_a"] if candidate["content_unit_scope"] == "WITHIN_CONTENT_UNIT"
                 else "CROSS_CONTENT_UNIT_BRIDGES")
        groups[group].append(candidate)
    accepted = read_jsonl(target / "semantic_full_edges.jsonl") if (target / "semantic_full_edges.jsonl").exists() else []
    rejected = read_jsonl(target / "semantic_full_rejected.jsonl") if (target / "semantic_full_rejected.jsonl").exists() else []
    unsupported = read_jsonl(target / "semantic_full_unsupported.jsonl") if (target / "semantic_full_unsupported.jsonl").exists() else []
    malformed = read_jsonl(target / "semantic_full_malformed.jsonl") if (target / "semantic_full_malformed.jsonl").exists() else []
    llm = create_llm(config["enrichment"])
    for group, group_candidates in groups.items():
        if group in status["verified_groups"]:
            continue
        a, r, u, m = verify_semantic_relations(
            group_candidates, nodes, llm, config["relations"]["acceptance_threshold"],
            config["relations"].get("batch_size", 2), config["relations"].get("generation_tokens", 550),
            config["relations"].get("retry_generation_tokens", 750))
        accepted += a; rejected += r; unsupported += u; malformed += m
        write_jsonl(target / "semantic_full_edges.jsonl", accepted)
        write_jsonl(target / "semantic_full_rejected.jsonl", rejected)
        write_jsonl(target / "semantic_full_unsupported.jsonl", unsupported)
        write_jsonl(target / "semantic_full_malformed.jsonl", malformed)
        status["verified_groups"].append(group)
        status.update(last_group=group, accepted=len(accepted), rejected=len(rejected))
        write_json(status_path, status)
        print({"verified_group": group, "candidates": len(group_candidates), "accepted": len(a)}, flush=True)
    status.update(complete=True, completed_at=datetime.now(timezone.utc).isoformat(),
                  accepted=len(accepted), rejected=len(rejected), malformed=len(malformed))
    write_json(status_path, status)
    print(json.dumps(status, indent=2), flush=True)


def postprocess(args):
    _, _, graph_root, target = _paths(args)
    config = _configuration(args, graph_root)
    nodes = read_jsonl(target / "evidence_nodes.jsonl")
    candidates = read_jsonl(target / "semantic_full_candidates.jsonl")
    accepted = read_jsonl(target / "semantic_full_edges.jsonl")
    rejected = read_jsonl(target / "semantic_full_rejected.jsonl")
    unsupported = read_jsonl(target / "semantic_full_unsupported.jsonl")
    malformed = read_jsonl(target / "semantic_full_malformed.jsonl")
    validation = _validate_semantic(args.doc_id, nodes, accepted,
                                    config["relations"]["acceptance_threshold"], malformed)
    stats = _semantic_stats(nodes, candidates, accepted, rejected, unsupported)
    write_json(target / "semantic_full_validation_report.json", validation)
    write_json(target / "semantic_full_statistics.json", stats)
    review = build_visualization(args.doc_id, config)
    print(json.dumps({"doc_id": args.doc_id, "stage": "cpu_postprocess", "review": str(review),
                      "accepted": len(accepted), "valid": validation["valid"]}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("preprocess", "verify", "postprocess"))
    parser.add_argument("--doc-id", required=True); parser.add_argument("--model", required=True)
    parser.add_argument(
        "--enrichment-model",
        help="Model whose saved node-enrichment comparison should be materialized; defaults to --model",
    )
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--source-root", default="output/evidence_graph")
    parser.add_argument("--comparison-root", default="output/enrichment_comparisons")
    parser.add_argument("--output-root", default="output/qwen35_semantic_graphs")
    args = parser.parse_args()
    {"preprocess": preprocess, "verify": verify, "postprocess": postprocess}[args.stage](args)


if __name__ == "__main__":
    main()
