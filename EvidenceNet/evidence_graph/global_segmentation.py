from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .io_utils import read_jsonl, write_json, write_jsonl
from .segmentation_ground_truth import evaluate, materialize


def optimise(nodes, vectors, diagnostics, title_rows, penalty, max_nodes):
    n = len(nodes)
    matrix = np.asarray(vectors, dtype=np.float32)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
    prefix = np.vstack([np.zeros((1, matrix.shape[1]), dtype=np.float32), np.cumsum(matrix, axis=0)])
    gram = prefix @ prefix.T
    prefix_norm = np.diag(gram)
    # squared norm of the vector sum for every half-open interval [i, j)
    sum_norm2 = prefix_norm[:, None] + prefix_norm[None, :] - 2 * gram

    order_by_id = {node["node_id"]: node["document_order"] for node in nodes}
    diagnostic_by_start = {order_by_id[row["right_id"]]: row for row in diagnostics}
    title_by_start = {}
    for row in title_rows:
        order = row.get("associated_order")
        if not order: continue
        title_by_start.setdefault(order, []).append(row)

    boundary_reward = np.zeros(n + 1, dtype=np.float64)
    boundary_details = {}
    for start in range(2, n + 1):
        diagnostic = diagnostic_by_start.get(start, {})
        raw = float(diagnostic.get("boundary_score", 0.0))
        reward = 1.15 * max(0.0, raw - .30)
        reasons = ["context_change"] if raw >= .55 else []
        if diagnostic.get("page_change"):
            reward += .08; reasons.append("page_change")
        if diagnostic.get("anaphoric_start"):
            reward -= .32; reasons.append("anaphoric_penalty")
        if diagnostic.get("running_metadata") or diagnostic.get("placeholder"):
            reward -= .8; reasons.append("metadata_penalty")
        for title in title_by_start.get(start, []):
            margin = float(title.get("context_margin", 0.0))
            if (title.get("detection") == "explicit_heading"
                    and title.get("classification") == "LIKELY_STARTS_NEW_ITEM"):
                reward += min(.55, .18 + 1.5 * max(0.0, margin)); reasons.append("validated_title")
            elif title.get("classification") in {"LIKELY_SUBHEADING_OR_PREVIOUS_CONTEXT", "SECTION_OR_RUNNING_LABEL"}:
                reward -= .20; reasons.append("non_item_heading_penalty")
        boundary_reward[start - 1] = reward
        boundary_details[start] = {"reward": round(reward, 5), "reasons": reasons}

    dp = np.full(n + 1, np.inf); previous = np.full(n + 1, -1, dtype=np.int32); dp[0] = -penalty
    for end in range(1, n + 1):
        starts = np.arange(max(0, end - max_nodes), end)
        lengths = end - starts
        # Normalised spherical SSE. The mild log-length term prevents long,
        # topically drifting spans from being rewarded merely for averaging.
        sse = lengths - np.maximum(0.0, sum_norm2[starts, end]) / lengths
        segment_cost = sse + .035 * lengths * np.log1p(lengths)
        start_rewards = np.where(starts == 0, 0.0, boundary_reward[starts])
        costs = dp[starts] + segment_cost + penalty - start_rewards
        best = int(np.argmin(costs)); dp[end] = costs[best]; previous[end] = starts[best]

    cuts = [] ; end = n
    while end > 0:
        start = int(previous[end])
        if start > 0: cuts.append(start + 1)  # document order of first node in new segment
        end = start
    cuts = sorted(cuts)
    assignments = []; segment = 1; cut_set = set(cuts)
    for node in nodes:
        if node["document_order"] in cut_set: segment += 1
        assignments.append({"node_id": node["node_id"], "segment_id": f"SEGMENT_{segment:04d}",
                            "content_item_id": f"ITEM_{segment:04d}"})
    evidence = [{"start_document_order": order, **boundary_details.get(order, {})} for order in cuts]
    return assignments, evidence, float(dp[n])


def main():
    parser = argparse.ArgumentParser(description="Global document segmentation with dynamic programming")
    parser.add_argument("--nodes", required=True); parser.add_argument("--embeddings", required=True)
    parser.add_argument("--diagnostics", required=True); parser.add_argument("--title-audit", required=True)
    parser.add_argument("--output-dir", required=True); parser.add_argument("--max-segment-nodes", type=int, default=120)
    parser.add_argument("--penalties", default="0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.3,2.6,3.0")
    args = parser.parse_args(); output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    nodes = sorted(read_jsonl(args.nodes), key=lambda row: row["document_order"])
    vector_by_id = {row["node_id"]: row["vector"] for row in read_jsonl(args.embeddings)}
    vectors = [vector_by_id[node["node_id"]] for node in nodes]
    diagnostics = read_jsonl(args.diagnostics); titles = read_jsonl(args.title_audit)
    reference = materialize(nodes); order_by_id = {row["node_id"]: row["document_order"] for row in nodes}
    trials = []
    for penalty in [float(value) for value in args.penalties.split(",")]:
        assignments, boundaries, objective = optimise(nodes, vectors, diagnostics, titles, penalty, args.max_segment_nodes)
        scored = [{**row, "document_order": order_by_id[row["node_id"]]} for row in assignments]
        trials.append({"penalty": penalty, "segments": len(boundaries) + 1, "objective": round(objective, 5),
                       "assignments": assignments, "boundaries": boundaries,
                       "exact": evaluate(reference, scored, 0), "tolerance_1": evaluate(reference, scored, 1)})
    # Select the centre of the longest stable plateau in segment count. Ground
    # truth is deliberately not consulted by this selection rule.
    groups = []
    for trial in trials:
        if groups and abs(groups[-1][-1]["segments"] - trial["segments"]) <= 2: groups[-1].append(trial)
        else: groups.append([trial])
    stable = max(groups, key=lambda group: len(group))
    chosen = stable[len(stable) // 2]
    write_jsonl(output / "assignments.jsonl", chosen.pop("assignments"))
    write_jsonl(output / "boundaries.jsonl", chosen.pop("boundaries"))
    compact = [{k: v for k, v in trial.items() if k not in {"assignments", "boundaries"}} for trial in trials]
    report = {"method": "global_spherical_sse_dynamic_programming_v1",
              "selection": "centre of longest stable segment-count plateau; no ground-truth selection",
              "chosen": chosen, "trials": compact}
    write_json(output / "evaluation.json", report); print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
