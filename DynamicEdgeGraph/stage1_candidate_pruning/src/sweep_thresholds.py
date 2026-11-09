"""Sweep independent route gates over already retrieved candidates."""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from .common import load_config, read_jsonl, run_dir


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args()
    config = load_config(args.config); out = run_dir(config)
    route_rows = {}
    for route in config["routes"]:
        path = out / "route_candidates" / f"{route}.jsonl"
        route_rows[route] = list(read_jsonl(path)) if path.exists() else []
    thresholds = {route: config.get("dense_thresholds", [0.0])
                  for route in config.get("vector_routes", {})}
    thresholds["bm25"] = config.get("bm25_thresholds", [0.0])
    thresholds["structural"] = [0.0]
    n = len({r["source_id"] for rows in route_rows.values() for r in rows})
    possible = n * (n - 1) // 2
    fields = ["route", "threshold", "retrieval_ceiling_pairs", "retained_pairs", "pruning_rate",
              "observed_candidate_recall", "gold_denominator"]
    route_pairs = {
        route: {(min(r["source_id"], r["target_id"]), max(r["source_id"], r["target_id"])) for r in rows}
        for route, rows in route_rows.items()
    }
    with (out / "threshold_sweep.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for route, rows in route_rows.items():
            for threshold in thresholds.get(route, [0.0]):
                pairs = {(min(r["source_id"], r["target_id"]), max(r["source_id"], r["target_id"]))
                         for r in rows if r["raw_score"] >= float(threshold)}
                writer.writerow({"route": route, "threshold": threshold,
                                 "retrieval_ceiling_pairs": len({(min(r["source_id"], r["target_id"]), max(r["source_id"], r["target_id"])) for r in rows}),
                                 "retained_pairs": len(pairs),
                                 "pruning_rate": None if not possible else 1 - len(pairs) / possible,
                                 "observed_candidate_recall": None, "gold_denominator": 0})
        gate_values = {
            route: (0.5 if route in config.get("vector_routes", {}) else
                    5.0 if route == "bm25" else 0.0)
            for route in route_rows
        }
        gated = set()
        for route, rows in route_rows.items():
            gated.update(
                (min(r["source_id"], r["target_id"]), max(r["source_id"], r["target_id"]))
                for r in rows if r["raw_score"] >= gate_values[route]
            )
        writer.writerow({"route": "OR_UNION",
                         "threshold": json.dumps(gate_values, sort_keys=True),
                         "retrieval_ceiling_pairs": len(set().union(*route_pairs.values())),
                         "retained_pairs": len(gated),
                         "pruning_rate": None if not possible else 1 - len(gated) / possible,
                         "observed_candidate_recall": None, "gold_denominator": 0})
    overlap = {}
    pair_sets = {route: {(min(r["source_id"], r["target_id"]), max(r["source_id"], r["target_id"])) for r in rows}
                 for route, rows in route_rows.items()}
    for route, pairs in pair_sets.items():
        overlap[route] = {"candidate_count": len(pairs), "unique_candidates": len(pairs - set().union(*(v for k, v in pair_sets.items() if k != route)))}
    for left, left_pairs in pair_sets.items():
        for right, right_pairs in pair_sets.items():
            if left < right: overlap[f"{left}∩{right}"] = len(left_pairs & right_pairs)
    (out / "route_overlap.json").write_text(json.dumps(overlap, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(out), "routes": {k: len(v) for k, v in route_rows.items()}}))


if __name__ == "__main__": main()
