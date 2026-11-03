#!/usr/bin/env python3
"""Generate frozen-view P1/P2 KG endpoint candidates without new inference.

P1 ranks the frozen 6,520-node comparison universe by cosine similarity of
node-level aggregates of the existing view vectors.  P2 uses exactly the same
candidate space and adds a bounded graph-neighbour propagation term for nodes
with observed NEXT/PREVIOUS or noisy RELATED_OPEN context.  Graph observations
are context only: they are neither labels nor negative-example sources.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterable

import numpy as np


VERSION = "kg-link-prediction-p1-p2-v1-20261102"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREP = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102"
DEFAULT_SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
DEFAULT_OUT = ROOT / "EvidenceNet/output/kg_link_prediction_p1_p2_20261102"
DEFAULT_SMOKE = ROOT / "EvidenceNet/output/kg_link_prediction_p1_p2_smoke_20261102"
GRAPH_BLEND = 0.20
RELATION_WEIGHTS = {"RELATED_OPEN": 1.0, "NEXT": 0.75, "PREVIOUS": 0.75}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def rows(path: Path) -> list[dict[str, Any]]:
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def canonical_pair(left: str, right: str) -> tuple[str, str]:
    if left == right:
        raise ValueError("self pair is not a candidate")
    return tuple(sorted((left, right)))


def pair_id(left: str, right: str, prefix: str) -> str:
    a, b = canonical_pair(left, right)
    return prefix + hashlib.sha256((a + "\0" + b).encode()).hexdigest()[:20]


def verify_preparation(prep: Path) -> dict[str, Any]:
    manifest = read_json(prep / "manifest.json")
    for item in manifest["inputs"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("changed frozen v2 input: " + item["path"])
    for name, expected in manifest["outputs"].items():
        if sha(prep / name) != expected:
            raise ValueError("changed frozen v2 output: " + name)
    for raw, expected in manifest["code"].items():
        if sha(Path(raw)) != expected:
            raise ValueError("changed frozen v2 preparation code: " + raw)
    return manifest


def aggregate_node_vectors(
    source_ids: list[str], views: list[dict[str, Any]], view_vectors: np.ndarray
) -> tuple[np.ndarray, dict[str, int]]:
    """Mean existing normalized view vectors, then L2-normalize per node."""
    if view_vectors.ndim != 2 or len(views) != view_vectors.shape[0]:
        raise ValueError("view/vector row mismatch")
    index = {node_id: pos for pos, node_id in enumerate(source_ids)}
    sums = np.zeros((len(source_ids), view_vectors.shape[1]), dtype=np.float32)
    counts = np.zeros(len(source_ids), dtype=np.int32)
    for row_pos, view in enumerate(views):
        pos = index.get(str(view["node_id"]))
        if pos is not None:
            sums[pos] += view_vectors[row_pos]
            counts[pos] += 1
    if np.any(counts == 0):
        raise ValueError("primary source without a frozen view")
    sums /= counts[:, None]
    norms = np.linalg.norm(sums, axis=1)
    if not np.isfinite(sums).all() or np.any(norms <= 0):
        raise ValueError("invalid aggregated frozen vectors")
    sums /= norms[:, None]
    return sums, {node_id: int(counts[pos]) for pos, node_id in enumerate(source_ids)}


def build_adjacency(edges: list[dict[str, Any]], eligible: set[str]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str, str]] = set()
    for edge in edges:
        source, target, relation = str(edge["source_id"]), str(edge["target_id"]), str(edge["relation_id"])
        if relation not in RELATION_WEIGHTS or source not in eligible or target not in eligible:
            continue
        layer = str(edge["graph_layer"])
        directions = [(source, target)]
        if relation == "RELATED_OPEN":
            directions.append((target, source))
        for left, right in directions:
            key = (left, right, relation, layer)
            if key in seen:
                continue
            seen.add(key)
            adjacency[left].append({
                "neighbor_id": right,
                "relation_id": relation,
                "graph_layer": layer,
                "edge_id": edge["edge_id"],
                "weight": RELATION_WEIGHTS[relation],
            })
    return {key: sorted(value, key=lambda row: (row["relation_id"], row["neighbor_id"]))
            for key, value in adjacency.items()}


def stable_top_indices(scores: np.ndarray, target_ids: list[str], k: int) -> list[int]:
    finite = np.flatnonzero(np.isfinite(scores))
    if len(finite) < k:
        raise ValueError(f"only {len(finite)} eligible targets for TopK={k}")
    if len(finite) > k:
        finite = finite[np.argpartition(scores[finite], -k)[-k:]]
    return sorted((int(pos) for pos in finite), key=lambda pos: (-float(scores[pos]), target_ids[pos]))[:k]


def graph_scores_and_trace(
    neighbor_rows: list[dict[str, Any]], vectors_by_id: dict[str, np.ndarray], targets: np.ndarray
) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]:
    relation_sum: dict[str, np.ndarray] = {}
    relation_weight = Counter()
    total = np.zeros(targets.shape[0], dtype=np.float32)
    total_weight = 0.0
    for row in neighbor_rows:
        relation = row["relation_id"]
        similarity = targets @ vectors_by_id[row["neighbor_id"]]
        weighted = float(row["weight"]) * similarity
        relation_sum.setdefault(relation, np.zeros_like(total))
        relation_sum[relation] += weighted
        relation_weight[relation] += float(row["weight"])
        total += weighted
        total_weight += float(row["weight"])
    if not total_weight:
        raise ValueError("graph score requested without a neighbour")
    per_relation = {relation: values / relation_weight[relation]
                    for relation, values in relation_sum.items()}
    return total / total_weight, per_relation, np.asarray(
        [float(row["weight"]) for row in neighbor_rows], dtype=np.float32)


def ranking_record(
    proposer: str, source_id: str, target_id: str, score: float, text_score: float,
    rank: int, entity: dict[str, Any], target_entity: dict[str, Any], baseline: set[tuple[str, str]],
    view_count: int, graph_record: dict[str, Any] | None,
) -> dict[str, Any]:
    pair = canonical_pair(source_id, target_id)
    record = {
        "pair_id": pair_id(source_id, target_id, "P1_" if proposer == "text_only" else "P2_"),
        "source_id": source_id,
        "target_id": target_id,
        "proposed_relation": "RELATED_OPEN",
        "proposer": proposer,
        "model_version": VERSION,
        "graph_version": "kg-link-prediction-pilot-v2-20261102",
        "raw_score": score,
        "text_cosine_score": text_score,
        "rank_within_source": rank,
        "source_split": entity["document_split"],
        "candidate_scope": "same_document" if entity["document"] == target_entity["document"] else "cross_document",
        "is_new_to_baseline": pair not in baseline,
        "baseline_pair_id": None,
        "source_frozen_view_count": view_count,
        "target_filtering": "same_document_split; exclude_self; exclude_observed_RELATED_OPEN",
        "graph_context_used": graph_record is not None,
        "graph_provenance": graph_record,
        "label_used": False,
    }
    return record


def generate_rankings(
    entities: list[dict[str, Any]], vectors: np.ndarray, view_counts: dict[str, int],
    observed_edges: list[dict[str, Any]], baseline: set[tuple[str, str]], top_k: int,
    batch_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ids = [row["entity_id"] for row in entities]
    entity_by_id = {row["entity_id"]: row for row in entities}
    vector_by_id = {node_id: vectors[pos] for pos, node_id in enumerate(ids)}
    adjacency = build_adjacency(observed_edges, set(ids))
    observed_semantic = {canonical_pair(row["source_id"], row["target_id"])
                         for row in observed_edges if row["relation_id"] == "RELATED_OPEN"}
    observed_targets: dict[str, set[str]] = defaultdict(set)
    for left, right in observed_semantic:
        observed_targets[left].add(right)
        observed_targets[right].add(left)
    by_split: dict[str, list[int]] = defaultdict(list)
    for pos, entity in enumerate(entities):
        by_split[entity["document_split"]].append(pos)

    p1: list[dict[str, Any]] = []
    p2: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    split_seconds: dict[str, float] = {}
    started = time.perf_counter()
    for split in sorted(by_split):
        split_started = time.perf_counter()
        positions = by_split[split]
        split_ids = [ids[pos] for pos in positions]
        target_vectors = vectors[positions]
        split_index = {node_id: local for local, node_id in enumerate(split_ids)}
        local_by_global = {global_pos: local for local, global_pos in enumerate(positions)}
        for batch_start in range(0, len(positions), batch_size):
            batch_positions = positions[batch_start:batch_start + batch_size]
            text_matrix = vectors[batch_positions] @ target_vectors.T
            for row_pos, global_pos in enumerate(batch_positions):
                source_id = ids[global_pos]
                text_scores = text_matrix[row_pos]
                filtered = text_scores.copy()
                filtered[local_by_global[global_pos]] = -np.inf
                for target_id in observed_targets.get(source_id, ()):
                    target_local = split_index.get(target_id)
                    if target_local is not None:
                        filtered[target_local] = -np.inf
                p1_indices = stable_top_indices(filtered, split_ids, top_k)
                neighbor_rows = adjacency.get(source_id, [])
                graph_used = bool(neighbor_rows)
                relation_arrays: dict[str, np.ndarray] = {}
                if graph_used:
                    graph_score, relation_arrays, _ = graph_scores_and_trace(
                        neighbor_rows, vector_by_id, target_vectors)
                    p2_scores = (1.0 - GRAPH_BLEND) * filtered + GRAPH_BLEND * graph_score
                    p2_scores[~np.isfinite(filtered)] = -np.inf
                    p2_indices = stable_top_indices(p2_scores, split_ids, top_k)
                else:
                    p2_scores = filtered
                    p2_indices = p1_indices

                for rank, target_local in enumerate(p1_indices, 1):
                    target_id = split_ids[target_local]
                    p1.append(ranking_record(
                        "text_only", source_id, target_id, float(filtered[target_local]),
                        float(text_scores[target_local]), rank, entities[global_pos], entity_by_id[target_id],
                        baseline, view_counts[source_id], None))
                p1_rank = {split_ids[pos]: rank for rank, pos in enumerate(p1_indices, 1)}
                p2_rank = {split_ids[pos]: rank for rank, pos in enumerate(p2_indices, 1)}
                changed = p1_indices != p2_indices
                for rank, target_local in enumerate(p2_indices, 1):
                    target_id = split_ids[target_local]
                    graph_record = None
                    if graph_used:
                        contributions = {relation: float(values[target_local])
                                         for relation, values in sorted(relation_arrays.items())}
                        individual = sorted(({
                            "neighbor_id": edge["neighbor_id"],
                            "relation_id": edge["relation_id"],
                            "graph_layer": edge["graph_layer"],
                            "edge_id": edge["edge_id"],
                            "weight": edge["weight"],
                            "neighbor_target_cosine": float(target_vectors[target_local] @ vector_by_id[edge["neighbor_id"]]),
                        } for edge in neighbor_rows),
                            key=lambda item: (-item["weight"] * item["neighbor_target_cosine"],
                                              item["relation_id"], item["neighbor_id"]))
                        graph_record = {
                            "blend_weight": GRAPH_BLEND,
                            "neighbor_count": len(neighbor_rows),
                            "neighbor_relations": dict(Counter(edge["relation_id"] for edge in neighbor_rows)),
                            "graph_support_score": float((p2_scores[target_local] - (1.0 - GRAPH_BLEND) * filtered[target_local]) / GRAPH_BLEND),
                            "relation_support_scores": contributions,
                            "top_contributing_neighbors": individual[:3],
                            "p1_rank_if_in_topk": p1_rank.get(target_id),
                            "rank_changed": p1_rank.get(target_id) != rank,
                        }
                    p2.append(ranking_record(
                        "text_graph", source_id, target_id, float(p2_scores[target_local]),
                        float(text_scores[target_local]), rank, entities[global_pos], entity_by_id[target_id],
                        baseline, view_counts[source_id], graph_record))
                decisions.append({
                    "source_id": source_id,
                    "document_split": split,
                    "graph_neighborhood_status": "connected" if graph_used else "isolated",
                    "graph_context_used": graph_used,
                    "neighbor_count": len(neighbor_rows),
                    "neighbor_relations": dict(Counter(edge["relation_id"] for edge in neighbor_rows)),
                    "p2_ranking_changed": changed,
                    "p2_topk_entrants": sorted(set(p2_rank) - set(p1_rank)),
                    "p2_topk_exits": sorted(set(p1_rank) - set(p2_rank)),
                    "p1_p2_identical_fallback": not graph_used and p1_indices == p2_indices,
                })
        split_seconds[split] = time.perf_counter() - split_started
    return p1, p2, decisions, {
        "candidate_generation_seconds": time.perf_counter() - started,
        "split_seconds": split_seconds,
    }


def select_budget(rankings: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    """Apply one deterministic global unique-pair rule to either proposer."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rankings:
        key = canonical_pair(row["source_id"], row["target_id"])
        previous = best.get(key)
        order = (-row["raw_score"], row["source_id"], row["target_id"])
        if previous is None or order < (-previous["raw_score"], previous["source_id"], previous["target_id"]):
            best[key] = row
    selected = sorted(best.values(), key=lambda row: (-row["raw_score"], row["source_id"], row["target_id"]))[:budget]
    return [dict(row, global_budget_rank=rank, global_budget=budget,
                 selection_rule="highest proposer score over unique canonical TopK pairs")
            for rank, row in enumerate(selected, 1)]


def summarize(
    p1: list[dict[str, Any]], p2: list[dict[str, Any]], p1_budget: list[dict[str, Any]],
    p2_budget: list[dict[str, Any]], decisions: list[dict[str, Any]], baseline: set[tuple[str, str]],
    timings: dict[str, Any], node_count: int, top_k: int, budget: int,
) -> dict[str, Any]:
    def pairs(values: list[dict[str, Any]]) -> set[tuple[str, str]]:
        return {canonical_pair(row["source_id"], row["target_id"]) for row in values}
    p1_pairs, p2_pairs = pairs(p1_budget), pairs(p2_budget)
    connected = [row for row in decisions if row["graph_context_used"]]
    isolated = [row for row in decisions if not row["graph_context_used"]]
    if any(not row["p1_p2_identical_fallback"] for row in isolated):
        raise ValueError("isolated P2 source differs from P1")
    connected_ids = {row["source_id"] for row in connected}
    return {
        "version": VERSION,
        "execution_boundary": {
            "parsing_run": False, "ocr_run": False, "node_generation_run": False,
            "embedding_run": False, "ultra_run": False, "gpu_used": False,
            "human_labels_used": False,
        },
        "fairness": {
            "primary_nodes": node_count, "source_nodes_each": node_count,
            "top_k_per_source": top_k, "ranking_rows_each": node_count * top_k,
            "global_budget_each": budget,
            "same_target_filtering": True, "same_budget_selection_rule": True,
            "isolated_p2_equals_p1": True,
        },
        "p1_text_only": {
            "budget_pairs": len(p1_pairs), "baseline_overlap": len(p1_pairs & baseline),
            "new_to_baseline": len(p1_pairs - baseline),
        },
        "p2_text_graph": {
            "budget_pairs": len(p2_pairs), "baseline_overlap": len(p2_pairs & baseline),
            "new_to_baseline": len(p2_pairs - baseline),
            "budget_pairs_with_connected_source": sum(row["source_id"] in connected_ids for row in p2_budget),
        },
        "p1_p2_difference": {
            "shared_budget_pairs": len(p1_pairs & p2_pairs),
            "p1_only_budget_pairs": len(p1_pairs - p2_pairs),
            "p2_only_budget_pairs": len(p2_pairs - p1_pairs),
        },
        "graph_use": {
            "connected_sources": len(connected), "isolated_sources": len(isolated),
            "connected_source_fraction": len(connected) / len(decisions),
            "connected_sources_with_changed_topk": sum(row["p2_ranking_changed"] for row in connected),
            "isolated_sources_with_changed_topk": sum(row["p2_ranking_changed"] for row in isolated),
            "neighbour_relations": dict(sum((Counter(row["neighbor_relations"]) for row in connected), Counter())),
            "interpretation": "Observed graph is ranking context only; no edge is a gold label and absence is not negative evidence.",
        },
        "timing": timings,
        "metrics_not_reported": ["precision", "recall", "retrieval_improvement"],
    }


def write_report(path: Path, summary: dict[str, Any], smoke: bool) -> None:
    p1, p2, diff, graph = (summary[key] for key in
                            ("p1_text_only", "p2_text_graph", "p1_p2_difference", "graph_use"))
    lines = [
        "# P1/P2 candidate generation report" + (" — CPU smoke" if smoke else ""), "",
        "This run reused frozen embedding views. It did not run parsing, OCR, node generation, embedding, ULTRA, GPU training, or human-label evaluation.", "",
        "## Fair candidate generation", "",
        f"- Sources/targets: {summary['fairness']['primary_nodes']} frozen-view nodes, restricted to the same document split.",
        f"- Per proposer: TopK={summary['fairness']['top_k_per_source']} per source; global unique-pair budget={summary['fairness']['global_budget_each']}.",
        "- Both proposers exclude self-pairs and already-observed noisy `RELATED_OPEN` pairs. Missing graph edges are never negatives.", "",
        "## Fixed-budget difference", "",
        f"- P1 Text-only: {p1['budget_pairs']} pairs; {p1['baseline_overlap']} overlap the frozen 1088-pair baseline and {p1['new_to_baseline']} are outside it.",
        f"- P2 Text+Graph: {p2['budget_pairs']} pairs; {p2['baseline_overlap']} overlap the baseline and {p2['new_to_baseline']} are outside it.",
        f"- P1/P2 share {diff['shared_budget_pairs']} budget pairs; P1-only={diff['p1_only_budget_pairs']}, P2-only={diff['p2_only_budget_pairs']}.", "",
        "## Actual graph use", "",
        f"- Connected sources: {graph['connected_sources']}; fully isolated sources: {graph['isolated_sources']}.",
        f"- Connected sources whose TopK changed: {graph['connected_sources_with_changed_topk']}; isolated sources whose TopK changed: {graph['isolated_sources_with_changed_topk']}.",
        f"- Directed adjacency entries used by relation: `{json.dumps(graph['neighbour_relations'], sort_keys=True)}`.",
        "- P2 uses a typed-neighbour propagation term only for connected sources. Isolated P2 rankings are asserted identical to P1, and are reported separately so they cannot hide local graph effects.", "",
        "## Interpretation boundary", "",
        "No candidate precision, recall, or retrieval-improvement claim is reported because independent human review labels do not yet exist. `RELATED_OPEN` observations are noisy context, not gold.",
    ]
    path.write_text("\n".join(lines) + "\n")


def run(prep: Path, source: Path, output: Path, smoke_nodes: int | None = None,
        batch_size: int = 64) -> dict[str, Any]:
    prep, source, output = Path(prep).resolve(), Path(source).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("fresh output required: " + str(output))
    output.mkdir(parents=True, exist_ok=True)
    total_started = time.perf_counter()
    prep_manifest = verify_preparation(prep)
    protocol = read_json(prep / "experiment_protocol.json")
    if protocol["version"] != "kg-link-prediction-pilot-v2-20261102":
        raise ValueError("unexpected preparation protocol")
    top_k = int(protocol["budget"]["top_k_per_source"])
    budget = int(protocol["budget"]["global_verifier_budget"])
    entities_all = {row["entity_id"]: row for row in rows(prep / "entities_with_text.jsonl")}
    source_rows = rows(prep / "proposal_sources.jsonl")
    source_ids = sorted(row["entity_id"] for row in source_rows)
    if len(source_ids) != protocol["entity_universe"]["primary_fair_comparison_nodes"]:
        raise ValueError("primary universe count changed")
    if smoke_nodes is not None:
        if smoke_nodes <= top_k:
            raise ValueError("smoke node count must exceed TopK")
        selected: list[str] = []
        # Preserve graph-connected examples, then deterministically fill from every split.
        smoke_edges = rows(prep / "observed_context_edges.jsonl")
        connected_by_relation: dict[str, set[str]] = defaultdict(set)
        for edge in smoke_edges:
            for key in ("source_id", "target_id"):
                if edge[key] in source_ids:
                    connected_by_relation[edge["relation_id"]].add(edge[key])
        split_names = ("train", "valid", "test")
        quotas = {split: smoke_nodes // len(split_names) for split in split_names}
        for split in split_names[:smoke_nodes % len(split_names)]:
            quotas[split] += 1
        for split in split_names:
            candidates = [node_id for node_id in source_ids if entities_all[node_id]["document_split"] == split]
            preferred: list[str] = []
            # Include each observed relation type in smoke whenever its endpoints occur in the split.
            for relation in ("NEXT", "PREVIOUS", "RELATED_OPEN"):
                preferred.extend(node_id for node_id in candidates
                                 if node_id in connected_by_relation[relation] and node_id not in preferred)
            ordered = preferred + [node_id for node_id in candidates if node_id not in preferred]
            selected.extend(ordered[:quotas[split]])
        source_ids = sorted(selected)
        # A split must remain large enough for TopK after filtering.
        counts = Counter(entities_all[node_id]["document_split"] for node_id in source_ids)
        if any(value <= top_k + 1 for value in counts.values()):
            raise ValueError("smoke selection too small within a split")
        budget = min(budget, max(1, len(source_ids) * top_k // 4))
    entities = [entities_all[node_id] for node_id in source_ids]

    views = rows(source / "views.jsonl")
    frozen_vectors = np.load(source / "view_vectors.npy", mmap_mode="r", allow_pickle=False)
    vectors, view_counts = aggregate_node_vectors(source_ids, views, frozen_vectors)
    baseline_rows = rows(prep / "baseline_candidate_pairs.jsonl")
    baseline = {canonical_pair(row["source_id"], row["target_id"]) for row in baseline_rows}
    observed_edges = rows(prep / "observed_context_edges.jsonl")
    p1, p2, decisions, timings = generate_rankings(
        entities, vectors, view_counts, observed_edges, baseline, top_k, batch_size)
    expected = len(source_ids) * top_k
    if len(p1) != expected or len(p2) != expected:
        raise ValueError("incomplete TopK rankings")
    p1_budget, p2_budget = select_budget(p1, budget), select_budget(p2, budget)
    if len(p1_budget) != budget or len(p2_budget) != budget:
        raise ValueError("candidate budget not filled")
    timings["total_seconds_before_output_hashing"] = time.perf_counter() - total_started
    summary = summarize(p1, p2, p1_budget, p2_budget, decisions, baseline, timings,
                        len(source_ids), top_k, budget)

    write_jsonl(output / "p1_text_only_rankings.jsonl", p1)
    write_jsonl(output / "p2_text_graph_rankings.jsonl", p2)
    write_jsonl(output / "p1_fixed_budget_candidates.jsonl", p1_budget)
    write_jsonl(output / "p2_fixed_budget_candidates.jsonl", p2_budget)
    write_jsonl(output / "p2_graph_decisions.jsonl", decisions)
    write_json(output / "summary.json", summary)
    run_protocol = {
        "version": VERSION,
        "frozen_preparation_version": protocol["version"],
        "smoke": smoke_nodes is not None,
        "smoke_nodes": smoke_nodes,
        "node_vector": "L2-normalized mean of existing L2-normalized frozen view vectors",
        "p1_score": "cosine(node_source, node_target)",
        "p2_score": f"{1-GRAPH_BLEND:.2f} * text_cosine + {GRAPH_BLEND:.2f} * weighted_mean(cosine(graph_neighbor, target))",
        "graph_relation_weights": RELATION_WEIGHTS,
        "candidate_filtering": protocol["common_candidate_space"],
        "budget": {"top_k_per_source": top_k, "global_verifier_budget": budget,
                   "selection_rule": "highest proposer score over unique canonical TopK pairs"},
        "truth_policy": protocol["truth_policy"],
        "labels_used": False,
    }
    write_json(output / "run_protocol.json", run_protocol)
    write_report(output / "REPORT.md", summary, smoke_nodes is not None)
    output_files = sorted(path for path in output.iterdir() if path.is_file())
    inputs = {
        "v2_manifest": prep / "manifest.json",
        "v2_protocol": prep / "experiment_protocol.json",
        "v2_entities": prep / "entities_with_text.jsonl",
        "v2_sources": prep / "proposal_sources.jsonl",
        "v2_baseline": prep / "baseline_candidate_pairs.jsonl",
        "v2_context_edges": prep / "observed_context_edges.jsonl",
        "frozen_views": source / "views.jsonl",
        "frozen_view_vectors": source / "view_vectors.npy",
    }
    manifest = {
        "version": VERSION,
        "frozen_v2_manifest_sha256": sha(prep / "manifest.json"),
        "frozen_v2_outputs": prep_manifest["outputs"],
        "inputs": {name: {"path": str(path), "sha256": sha(path)} for name, path in inputs.items()},
        "outputs": {path.name: sha(path) for path in output_files},
        "code": {str(Path(__file__).resolve()): sha(Path(__file__).resolve())},
    }
    write_json(output / "manifest.json", manifest)
    return summary


def check(output: Path) -> None:
    output = Path(output).resolve()
    manifest = read_json(output / "manifest.json")
    for item in manifest["inputs"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("changed candidate input: " + item["path"])
    for name, expected in manifest["outputs"].items():
        if sha(output / name) != expected:
            raise ValueError("changed candidate output: " + name)
    for raw, expected in manifest["code"].items():
        if sha(Path(raw)) != expected:
            raise ValueError("changed candidate code: " + raw)
    summary = read_json(output / "summary.json")
    if not summary["fairness"]["isolated_p2_equals_p1"]:
        raise ValueError("failed isolated-source fairness assertion")
    print("KG_LINK_PREDICTION_P1_P2_OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("smoke", "run"):
        item = sub.add_parser(name)
        item.add_argument("--prep", type=Path, default=DEFAULT_PREP)
        item.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
        item.add_argument("--out", type=Path, default=DEFAULT_SMOKE if name == "smoke" else DEFAULT_OUT)
        item.add_argument("--batch-size", type=int, default=64)
        if name == "smoke":
            item.add_argument("--nodes", type=int, default=96)
    verify = sub.add_parser("check")
    verify.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "check":
        check(args.out)
    else:
        result = run(args.prep, args.source, args.out,
                     smoke_nodes=args.nodes if args.command == "smoke" else None,
                     batch_size=args.batch_size)
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
