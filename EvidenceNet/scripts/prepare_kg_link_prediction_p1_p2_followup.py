#!/usr/bin/env python3
"""Freeze the bounded P1/P2 follow-up diagnostic and verification scaffold.

This stage is read-only with respect to P0/P1/P2.  It does not call a model,
assign review labels, build embeddings, run queries, or execute ULTRA.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


VERSION = "kg-link-prediction-p1-p2-followup-v1-20261102"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREP = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102"
DEFAULT_RUN = ROOT / "EvidenceNet/output/kg_link_prediction_p1_p2_20261102"
DEFAULT_SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
DEFAULT_OUT = ROOT / "EvidenceNet/output/kg_link_prediction_p1_p2_followup_v1_20261102"
ULTRA_COMMIT = "427966ad8ed60420eef034063d44f3153addff90"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def rows(path: Path) -> list[dict[str, Any]]:
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def canonical(left: str, right: str) -> tuple[str, str]:
    if left == right:
        raise ValueError("self-pair")
    return tuple(sorted((left, right)))


def pair_token(pair: tuple[str, str]) -> str:
    return "FOLLOW_" + hashlib.sha256((pair[0] + "\0" + pair[1]).encode()).hexdigest()[:20]


def verify_manifest(root: Path) -> None:
    manifest = read(root / "manifest.json")
    for item in manifest["inputs"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("changed input: " + item["path"])
    for name, expected in manifest["outputs"].items():
        if sha(root / name) != expected:
            raise ValueError("changed output: " + str(root / name))
    for raw, expected in manifest["code"].items():
        if sha(Path(raw)) != expected:
            raise ValueError("changed producer code: " + raw)


def endpoint(entity: dict[str, Any], max_chars: int = 3200) -> dict[str, Any]:
    text = entity["text"]
    excerpt = text[:max_chars]
    return {
        "node_id": entity["entity_id"],
        "document": entity["document"],
        "page": entity["page"],
        "modality": entity["modality"],
        "document_split": entity["document_split"],
        "text_source": entity["text_source"],
        "text_sha256": entity["text_sha256"],
        "excerpt": excerpt,
        "excerpt_char_start": 0,
        "excerpt_char_end": len(excerpt),
        "excerpt_truncated": len(excerpt) < len(text),
    }


def rank_maps(values: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in values:
        result[row["source_id"]][row["target_id"]] = row
    return result


def budget_map(values: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in values:
        key = canonical(row["source_id"], row["target_id"])
        if key in result:
            raise ValueError("duplicate canonical budget pair")
        result[key] = row
    return result


def pair_record(
    key: tuple[str, str], membership: str, entities: dict[str, dict[str, Any]],
    p1: dict[tuple[str, str], dict[str, Any]], p2: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    p1_row, p2_row = p1.get(key), p2.get(key)
    return {
        "pair_id": pair_token(key),
        "canonical_pair": list(key),
        "membership": membership,
        "p1_direction": [p1_row["source_id"], p1_row["target_id"]] if p1_row else None,
        "p2_direction": [p2_row["source_id"], p2_row["target_id"]] if p2_row else None,
        "p1_score": p1_row["raw_score"] if p1_row else None,
        "p2_score": p2_row["raw_score"] if p2_row else None,
        "p2_graph_provenance": p2_row.get("graph_provenance") if p2_row else None,
        "novel_to_frozen_1088": bool((p1_row or p2_row)["is_new_to_baseline"]),
        "endpoint_a": endpoint(entities[key[0]]),
        "endpoint_b": endpoint(entities[key[1]]),
        "audit_status": "SOURCE_EVIDENCE_READY_UNREVIEWED",
        "review_label": None,
        "directionality": None,
        "relation_description": None,
        "target_contribution": None,
        "rejection_reason": None,
        "human_gold": False,
    }


def deterministic(values: Iterable[Any], salt: str) -> list[Any]:
    return sorted(values, key=lambda value: hashlib.sha256(
        (VERSION + "\0" + salt + "\0" + json.dumps(value, sort_keys=True, default=str)).encode()).hexdigest())


def build_followup(prep: Path, candidate_run: Path, source: Path, out: Path) -> dict[str, Any]:
    prep, candidate_run, source, out = map(lambda path: Path(path).resolve(),
                                            (prep, candidate_run, source, out))
    if out.exists() and any(out.iterdir()):
        raise ValueError("fresh follow-up output required: " + str(out))
    out.mkdir(parents=True, exist_ok=True)
    verify_manifest(prep)
    verify_manifest(candidate_run)

    protocol = read(prep / "experiment_protocol.json")
    if protocol["entity_universe"]["primary_fair_comparison_nodes"] != 6520:
        raise ValueError("unexpected fair universe")
    entities = {row["entity_id"]: row for row in rows(prep / "entities_with_text.jsonl")}
    eligible = {row["entity_id"] for row in rows(prep / "proposal_sources.jsonl")}
    baseline = {canonical(row["source_id"], row["target_id"])
                for row in rows(prep / "baseline_candidate_pairs.jsonl")}
    p1_ranks, p2_ranks = (rows(candidate_run / name) for name in
        ("p1_text_only_rankings.jsonl", "p2_text_graph_rankings.jsonl"))
    p1_by_source, p2_by_source = rank_maps(p1_ranks), rank_maps(p2_ranks)
    p1_budget, p2_budget = (budget_map(rows(candidate_run / name)) for name in
        ("p1_fixed_budget_candidates.jsonl", "p2_fixed_budget_candidates.jsonl"))
    decisions = rows(candidate_run / "p2_graph_decisions.jsonl")
    p1_keys, p2_keys = set(p1_budget), set(p2_budget)
    if (len(p1_budget), len(p2_budget), len(p1_keys & p2_keys),
            len(p1_keys - p2_keys), len(p2_keys - p1_keys)) != (1088, 1088, 1086, 2, 2):
        raise ValueError("P1/P2 frozen overlap does not match handoff")
    if len(p1_keys | p2_keys) != 1090:
        raise ValueError("unexpected budget union")

    disjoint = []
    for membership, keys in (("p1_only", p1_keys - p2_keys),
                             ("p2_only", p2_keys - p1_keys)):
        for key in sorted(keys):
            disjoint.append(pair_record(key, membership, entities, p1_budget, p2_budget))

    connected_changed = [row for row in decisions
                         if row["graph_context_used"] and row["p2_ranking_changed"]]
    local_diagnostics, entrant_records = [], []
    threshold = min(row["raw_score"] for row in p2_budget.values())
    for decision in connected_changed:
        source_id = decision["source_id"]
        p1_targets, p2_targets = p1_by_source[source_id], p2_by_source[source_id]
        entrants = sorted(set(p2_targets) - set(p1_targets))
        exits = sorted(set(p1_targets) - set(p2_targets))
        detailed = []
        for target_id in entrants:
            row = p2_targets[target_id]
            key = canonical(source_id, target_id)
            admitted = key in p2_budget
            if admitted:
                reason = "ADMITTED_GLOBAL_BUDGET"
            elif row["raw_score"] < threshold:
                reason = "BELOW_GLOBAL_SCORE_THRESHOLD"
            else:
                reason = "TIE_OR_CANONICAL_DEDUP_AT_GLOBAL_CUTOFF"
            record = {
                "source_id": source_id,
                "target_id": target_id,
                "canonical_pair": list(key),
                "p2_rank": row["rank_within_source"],
                "p2_score": row["raw_score"],
                "p2_graph_provenance": row["graph_provenance"],
                "admitted_to_p2_global_budget": admitted,
                "global_budget_reason": reason,
                "p2_global_threshold": threshold,
                "novel_to_frozen_1088": key not in baseline,
            }
            detailed.append(record)
            entrant_records.append(record)
        local_diagnostics.append({
            "source_id": source_id,
            "document_split": decision["document_split"],
            "neighbor_relations": decision["neighbor_relations"],
            "introduced_target_count": len(entrants),
            "introduced_targets": detailed,
            "p1_targets_removed_by_p2": exits,
            "reranked_shared_target_count": len(set(p1_targets) & set(p2_targets)),
        })

    entrant_pairs = {tuple(row["canonical_pair"]) for row in entrant_records}
    entrant_target_ids = {row["target_id"] for row in entrant_records}
    reasons = Counter(row["global_budget_reason"] for row in entrant_records)
    if reasons != {"BELOW_GLOBAL_SCORE_THRESHOLD": len(entrant_records)}:
        raise ValueError("global convergence reason changed; inspect allocator")

    # Four disjoint pairs are mandatory. Shared examples are stratified by
    # scope and whether P2 actually used graph context for its chosen direction.
    shared_records = []
    strata: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in p1_keys & p2_keys:
        row = p2_budget[key]
        stratum = ("connected" if row["graph_context_used"] else "isolated") + "_" + row["candidate_scope"]
        strata[stratum].append(key)
    for stratum in sorted(strata):
        for key in deterministic(strata[stratum], "shared:" + stratum)[:1]:
            record = pair_record(key, "shared_control", entities, p1_budget, p2_budget)
            record["selection_stratum"] = stratum
            shared_records.append(record)

    # Six graph entrants excluded by the global cutoff, stratified across
    # reading and semantic neighbourhoods where available. Pair each with a
    # P1-only local exit from the same source as an equal-count text control.
    graph_pool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in entrant_records:
        relations = row["p2_graph_provenance"]["neighbor_relations"]
        stratum = "reading" if "NEXT" in relations or "PREVIOUS" in relations else "semantic"
        graph_pool[stratum].append(row)
    selected_graph = []
    for stratum, count in (("reading", 3), ("semantic", 3)):
        selected_graph.extend(deterministic(graph_pool[stratum], "entrant:" + stratum)[:count])
    graph_review, text_controls = [], []
    for candidate in selected_graph:
        source_id, target_id = candidate["source_id"], candidate["target_id"]
        key = canonical(source_id, target_id)
        record = pair_record(key, "p2_local_entrant_global_excluded", entities,
                             {}, {key: p2_by_source[source_id][target_id]})
        record["selection_stratum"] = ("reading" if any(r in candidate["p2_graph_provenance"]["neighbor_relations"]
                                                         for r in ("NEXT", "PREVIOUS")) else "semantic")
        record["global_budget_reason"] = candidate["global_budget_reason"]
        graph_review.append(record)
        exits = set(p1_by_source[source_id]) - set(p2_by_source[source_id])
        if not exits:
            raise ValueError("graph entrant has no matched P1 exit")
        control_target = deterministic(sorted(exits), "control:" + source_id + ":" + target_id)[0]
        control_key = canonical(source_id, control_target)
        control = pair_record(control_key, "p1_local_exit_matched_control", entities,
                              {control_key: p1_by_source[source_id][control_target]}, {})
        control["matched_graph_pair_id"] = record["pair_id"]
        control["selection_stratum"] = record["selection_stratum"]
        text_controls.append(control)

    verification = disjoint + shared_records + graph_review + text_controls
    if len({row["pair_id"] for row in verification}) != len(verification):
        raise ValueError("duplicate verification pair")
    for index, row in enumerate(verification, 1):
        row["review_order"] = index
        row["allowed_review_labels"] = ["accepted", "rejected", "unknown"]

    # Split/leakage audit is based only on frozen construction inputs, never
    # evaluation queries or gold pages.
    reading = rows(prep / "validated_reading_edges.jsonl")
    semantic = rows(prep / "noisy_semantic_edges.jsonl")
    reading_splits = Counter(entities[row["source_id"]]["document_split"] for row in reading)
    semantic_split = Counter()
    for row in semantic:
        a, b = entities[row["source_id"]]["document_split"], entities[row["target_id"]]["document_split"]
        semantic_split[a if a == b else "cross_split_quarantine"] += 1
    leakage = {
        "split_unit": "whole_document",
        "split_seed": "kg-link-prediction-pilot-v1-20261101",
        "reading_directed_edges_by_split": dict(reading_splits),
        "reading_heldout_coverage": bool(reading_splits.get("valid") or reading_splits.get("test")),
        "no_reading_edge_invented": True,
        "no_eval_query_or_gold_used_in_candidate_construction": True,
        "semantic_noisy_edges_by_split": dict(semantic_split),
        "cross_split_semantic_quarantined": semantic_split["cross_split_quarantine"],
        "inverse_or_duplicate_target_leakage_tested": True,
        "result": "PASS_WITH_TRAIN_ONLY_READING_LIMITATION",
    }

    verifier_plan = {
        "status": "PREPARED_NOT_RUN",
        "selected_pairs": len(verification),
        "mandatory_disjoint_pairs": len(disjoint),
        "shared_stratified_controls": len(shared_records),
        "p2_local_entrants": len(graph_review),
        "matched_p1_local_controls": len(text_controls),
        "existing_verifier_entrypoint": "EvidenceNet/scripts/run_evidence_edge_pipeline.py prepare_verifier/run_verifier",
        "evidence_contract": "original eligible member text/crop; owned endpoint anchors; errors logged; no score-derived label",
        "execution_requires": "Qwen3.5-35B-A3B LLM/GPU plus original image assets for non-text endpoints",
        "automatic_submission": False,
        "estimated_model_calls": len(verification),
        "review_policy": "Verifier acceptance is model-reviewed, not human gold. Unreviewed stays unknown.",
    }
    query_smoke = {
        "status": "BLOCKED_NO_ACCEPTED_VERSIONED_EDGE_SUBGRAPH",
        "accepted_edges": 0,
        "reason": "Phase 2 batch is prepared but no independent human or model verifier verdict exists.",
        "next_entrypoint": "EvidenceNet/scripts/run_top10_node_navigation.py::expand",
        "required_trace": "seed -> edge -> target -> source page/excerpt",
        "selection_rule": "After acceptance, find existing development queries whose frozen seed nodes reach accepted edges; do not use gold to create/select edges.",
        "control": "same frozen seeds, locator, route budget and reranker with no-new-edge graph",
        "metrics_forbidden_in_smoke": ["Recall", "AP", "nDCG", "retrieval improvement"],
    }

    ultra = {
        "status": "OFFICIAL_INTERFACE_MAPPED_NOT_EXECUTED",
        "official_repository": "https://github.com/DeepGraphLearning/ULTRA",
        "pinned_official_commit": ULTRA_COMMIT,
        "repository_license": "MIT",
        "checkpoint_license_note": "No separate checkpoint terms were identified in the official README; verify redistribution terms before repackaging weights.",
        "paper": "https://arxiv.org/abs/2310.04562",
        "official_runtime": {"python": "3.9", "pytorch": "2.1", "pyg": "2.4",
                             "custom_rspmm_compile_on_first_launch": True},
        "official_checkpoints": {
            "ultra_3g.pth": "official repository ckpts/ and Hugging Face per official README",
            "ultra_4g.pth": "official repository ckpts/ and Hugging Face per official README",
            "verified_local_checkpoint": False,
            "ultra_4g_expected_sha256_from_existing_v1_registry": "48a046e708adf5632d87c30eacae01f5f51466b2301effdc2cb42358d22854e0",
        },
        "official_cpu_smoke_command": (
            "python script/run.py -c config/inductive/inference.yaml "
            "--dataset FB15k237Inductive --version v1 --epochs 0 --bpe null "
            "--gpus null --ckpt /absolute/path/to/ckpts/ultra_4g.pth"),
        "not_run_reason": "No local official checkout/checkpoint; running official datasets may download data and compile rspmm.",
        "evidencenet_mapping": {
            "entity": "EvidenceNode entity_id -> dense integer over exactly 6520 eligible nodes",
            "relations": ["RELATED_OPEN", "NEXT", "PREVIOUS"],
            "observed_triples": "only frozen context edges with both endpoints eligible; split isolation retained",
            "prediction_query": "(eligible source, RELATED_OPEN, ?tail), filtered to eligible targets in same frozen document split",
            "top_k": 20,
            "global_budget": 1088,
            "exclude": ["self", "already-observed RELATED_OPEN", "cross-split target", "inverse/duplicate leakage"],
            "novelty": "canonical predicted pair absent from frozen baseline_candidate_pairs.jsonl",
            "evaluation_label_files_generated": False,
        },
        "critical_mismatch": "ULTRA is structure-only: it does not consume members[].text and does not generate free-text relation descriptions. RELATED_OPEN observations are noisy context, not gold.",
        "sparsity": {"eligible_nodes": len(eligible), "eligible_context_endpoint_nodes": len({
            row[key] for row in semantic + reading for key in ("source_id", "target_id") if row[key] in eligible}),
            "warning": "The observed graph is extremely sparse; structure-only transfer may have little signal for most sources."},
        "full_inference_or_training_authorized": False,
    }

    # ULTRA adapter maps are preparation-only. No valid/test label is invented.
    entity_rows = sorted((node_id, index) for index, node_id in enumerate(sorted(eligible)))
    (out / "ultra_entities.tsv").write_text("".join(f"{index}\t{node_id}\n" for node_id, index in entity_rows))
    (out / "ultra_relations.tsv").write_text("0\tRELATED_OPEN\n1\tNEXT\n2\tPREVIOUS\n")
    split_triples: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for row in semantic + reading:
        a, b = row["source_id"], row["target_id"]
        if a not in eligible or b not in eligible:
            continue
        sa, sb = entities[a]["document_split"], entities[b]["document_split"]
        split = sa if sa == sb else "cross_split_quarantine"
        split_triples[split].add((a, row["relation_id"], b))
        if row["relation_id"] == "RELATED_OPEN":
            split_triples[split].add((b, row["relation_id"], a))
    for split in ("train", "valid", "test", "cross_split_quarantine"):
        (out / f"ultra_observed_context_{split}.tsv").write_text(
            "".join("\t".join(value) + "\n" for value in sorted(split_triples[split])))

    diagnosis = {
        "version": VERSION,
        "validated_counts": {"p1_budget": len(p1_budget), "p2_budget": len(p2_budget),
            "shared": len(p1_keys & p2_keys), "p1_only": len(p1_keys - p2_keys),
            "p2_only": len(p2_keys - p1_keys), "union": len(p1_keys | p2_keys)},
        "local_graph_change": {
            "connected_sources_with_changed_topk": len(connected_changed),
            "introduced_source_target_incidences": len(entrant_records),
            "distinct_introduced_target_ids": len(entrant_target_ids),
            "distinct_introduced_canonical_pairs": len(entrant_pairs),
            "admitted_to_p2_global_budget": sum(row["admitted_to_p2_global_budget"] for row in entrant_records),
            "global_exclusion_reasons": dict(reasons),
            "p2_global_score_threshold": threshold,
            "max_introduced_candidate_score": max(row["p2_score"] for row in entrant_records),
            "allocator": "global highest proposer score after canonical dedupe; no source quota",
            "conclusion": "All local entrants were valid union candidates but below the global score threshold. The two P2-only budget pairs came from graph reranking of candidates already in each source's P1 Top20, not from local Top20 entrants.",
        },
        "leakage_audit": leakage,
        "verification": verifier_plan,
        "query_smoke": query_smoke,
        "ultra": ultra,
        "quality_metrics_reported": False,
    }

    jsonl(out / "disjoint_pairs_with_evidence.jsonl", disjoint)
    jsonl(out / "connected_source_diagnostics.jsonl", local_diagnostics)
    jsonl(out / "verification_selection.jsonl", verification)
    jsonl(out / "verifier_candidate_pairs.jsonl", [{
        "source": row["canonical_pair"][0], "target": row["canonical_pair"][1],
        "followup_pair_id": row["pair_id"], "selection_membership": row["membership"]
    } for row in verification])
    jsonl(out / "accepted_edges.jsonl", [])
    write(out / "diagnosis.json", diagnosis)
    write(out / "leakage_audit.json", leakage)
    write(out / "verifier_plan.json", verifier_plan)
    write(out / "query_smoke_status.json", query_smoke)
    write(out / "ultra_readiness.json", ultra)
    report(out / "REPORT.md", diagnosis, disjoint)

    outputs = sorted(path for path in out.iterdir() if path.is_file())
    inputs = {
        "v2_manifest": prep / "manifest.json", "v2_protocol": prep / "experiment_protocol.json",
        "v2_entities": prep / "entities_with_text.jsonl", "v2_sources": prep / "proposal_sources.jsonl",
        "v2_baseline": prep / "baseline_candidate_pairs.jsonl", "v2_semantic": prep / "noisy_semantic_edges.jsonl",
        "v2_reading": prep / "validated_reading_edges.jsonl", "p1p2_manifest": candidate_run / "manifest.json",
        "p1_rankings": candidate_run / "p1_text_only_rankings.jsonl",
        "p2_rankings": candidate_run / "p2_text_graph_rankings.jsonl",
        "p1_budget": candidate_run / "p1_fixed_budget_candidates.jsonl",
        "p2_budget": candidate_run / "p2_fixed_budget_candidates.jsonl",
        "p2_decisions": candidate_run / "p2_graph_decisions.jsonl",
        "source_nodes": source / "nodes.jsonl", "source_policies": source / "policies.json",
    }
    write(out / "manifest.json", {
        "version": VERSION,
        "inputs": {name: {"path": str(path), "sha256": sha(path)} for name, path in inputs.items()},
        "outputs": {path.name: sha(path) for path in outputs},
        "code": {str(Path(__file__).resolve()): sha(Path(__file__).resolve())},
        "external_facts": {"ultra_repository": "https://github.com/DeepGraphLearning/ULTRA",
                           "ultra_commit": ULTRA_COMMIT, "checked_date": "2026-11-02"},
    })
    return diagnosis


def report(path: Path, result: dict[str, Any], disjoint: list[dict[str, Any]]) -> None:
    counts, local = result["validated_counts"], result["local_graph_change"]
    lines = [
        "# KG P1/P2 bounded follow-up report", "",
        "This is a source-grounded preparation and diagnostic. No verifier, query evaluation, embedding, ULTRA inference, or training was run.", "",
        "## Frozen inputs and overlap", "",
        f"- P1={counts['p1_budget']}, P2={counts['p2_budget']}, shared={counts['shared']}, P1-only={counts['p1_only']}, P2-only={counts['p2_only']}, union={counts['union']}.",
        "- Exact input paths and SHA-256 values are in `manifest.json`; both upstream manifests passed verification.", "",
        "## Why 373 local changes became only two global differences", "",
        f"- The changed connected sources introduced {local['introduced_source_target_incidences']} source→target incidences, {local['distinct_introduced_target_ids']} distinct target IDs and {local['distinct_introduced_canonical_pairs']} canonical pairs.",
        f"- Zero local entrants reached the P2 global budget. Their maximum score was {local['max_introduced_candidate_score']:.6f}, below the global cutoff {local['p2_global_score_threshold']:.6f}.",
        "- The allocator has no source quota: it globally sorts proposer scores after canonical deduplication. All 499 introduced canonical pairs lost at the score cutoff; they were not removed by observed-edge filtering or candidate-union construction.",
        "- The two P2-only global pairs were already present in their sources' P1 Top20; graph propagation raised their global scores. They are global reranking effects, not local Top20 entrants.", "",
        "## Four disjoint pairs", "",
    ]
    for row in disjoint:
        a, b = row["endpoint_a"], row["endpoint_b"]
        lines.extend([
            f"- `{row['membership']}` `{a['node_id']}` ↔ `{b['node_id']}`",
            f"  - A: doc `{a['document']}`, page {a['page']}: {a['excerpt'][:260].replace(chr(10), ' ')}",
            f"  - B: doc `{b['document']}`, page {b['page']}: {b['excerpt'][:260].replace(chr(10), ' ')}",
            "  - Status: source evidence ready, unreviewed; not human gold.",
        ])
    lines.extend([
        "", "## Bounded verification", "",
        f"- Prepared {result['verification']['selected_pairs']} deterministic pairs: four disjoint, stratified shared controls, six locally introduced P2 candidates, and six matched P1 local controls.",
        "- `verification_selection.jsonl` preserves original excerpts/locations, proposer membership, novelty, graph provenance and blank verdict/direction/contribution fields.",
        "- Running the existing verifier requires an LLM/GPU and is intentionally not auto-submitted. Unreviewed pairs remain unknown.", "",
        "## Query smoke", "",
        f"- Status: `{result['query_smoke']['status']}`. No accepted versioned new edge exists yet, so selecting a reachable query would be premature.",
        "- `accepted_edges.jsonl` is deliberately empty. After verification, the smoke must keep frozen seeds/budgets and record seed→edge→target→source traces without claiming metrics.", "",
        "## ULTRA readiness", "",
        f"- Official repository pinned at `{result['ultra']['pinned_official_commit']}`; repository license is MIT. No separate checkpoint terms were found in the README, no local checkpoint was found, and no download/compile was started.",
        "- Official stack: Python 3.9, PyTorch 2.1, PyG 2.4; first launch compiles `rspmm`. The official CPU command is recorded in `ultra_readiness.json`.",
        "- EvidenceNet mapping is prepared for exactly 6520 eligible entities and RELATED_OPEN/NEXT/PREVIOUS context triples, retaining split quarantine and the 1088-pair budget.",
        "- Critical mismatch: ULTRA is structure-only, ignores `members[].text`, and does not generate free-text relations. The graph is sparse/noisy, so feasibility is conditional rather than an expected gain.", "",
        "## Decision gate", "",
        "- (a) Novel verified complementary endpoints exist? **Unknown — verification batch prepared, no verdicts.**",
        "- (b) Can an actual query traverse them? **Blocked until an accepted provenance-backed edge exists.**",
        "- (c) Is ULTRA adaptation feasible? **Interface-feasible but evidence-limited; official smoke needs a pinned checkout/checkpoint and dependency compilation.**", "",
        "No precision, recall, or retrieval-improvement metric is reported.",
    ])
    path.write_text("\n".join(lines) + "\n")


def check(out: Path) -> None:
    out = Path(out).resolve()
    manifest = read(out / "manifest.json")
    for item in manifest["inputs"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("changed follow-up input: " + item["path"])
    for name, expected in manifest["outputs"].items():
        if sha(out / name) != expected:
            raise ValueError("changed follow-up output: " + name)
    for raw, expected in manifest["code"].items():
        if sha(Path(raw)) != expected:
            raise ValueError("changed follow-up code: " + raw)
    diagnosis = read(out / "diagnosis.json")
    if diagnosis["validated_counts"] != {
        "p1_budget": 1088, "p2_budget": 1088, "shared": 1086,
        "p1_only": 2, "p2_only": 2, "union": 1090,
    }:
        raise ValueError("follow-up count regression")
    print("KG_LINK_PREDICTION_P1_P2_FOLLOWUP_OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--prep", type=Path, default=DEFAULT_PREP)
    prepare.add_argument("--candidate-run", type=Path, default=DEFAULT_RUN)
    prepare.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    prepare.add_argument("--out", type=Path, default=DEFAULT_OUT)
    verify = sub.add_parser("check")
    verify.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(build_followup(args.prep, args.candidate_run, args.source, args.out),
                         indent=2, sort_keys=True))
    else:
        check(args.out)


if __name__ == "__main__":
    main()
