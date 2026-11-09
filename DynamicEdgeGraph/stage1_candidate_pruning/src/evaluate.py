"""Evaluate candidate overlap and honest downstream HF page coverage."""
from __future__ import annotations
import argparse, json, platform, subprocess, time
from .common import load_config, read_jsonl, repo_path, run_dir, write_jsonl


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args()
    config = load_config(args.config); out = run_dir(config)
    coverage = list(read_jsonl(out / "hf_120_coverage.jsonl")) if (out / "hf_120_coverage.jsonl").exists() else []
    union = list(read_jsonl(out / "candidate_union.jsonl")) if (out / "candidate_union.jsonl").exists() else []
    results = [{"query_id": row["query_id"], "source": row["source"], "evidence_structure": row["evidence_structure"],
                "status": row["status"], "page_recall": None, "note": "Page labels are not Node-Node edge labels."}
               for row in coverage]
    write_jsonl(out / "hf_120_results.jsonl", results)
    metrics = {
        "node_node_track": {"gold_positive_pairs": None, "candidate_recall": None,
                            "reason": "No independently verified Node-Node gold set configured; recall is not claimable."},
        "query_evidence_track": {"queries_seen": len(coverage),
                                 "eligible_queries": sum(r["status"] == "eligible" for r in coverage),
                                 "page_metrics": None,
                                 "reason": "Current implementation records mapping coverage only; query labels are not edge gold."},
        "candidate_union_pairs": len(union), "run_id": config["run_id"],
        "hardware": platform.platform(), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "stage1_metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    try: commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path("."), text=True).strip()
    except (OSError, subprocess.CalledProcessError): commit = None
    resources = out / "route_resources.json"
    manifest = {"run_id": config["run_id"], "config": config, "git_commit": commit,
                "seed": config.get("seed"), "models": {"dense_qwen3_0_6b": "Qwen3-Embedding-0.6B:frozen",
                "bm25": "local-inverted-index", "structural": "document-page-window"}}
    if resources.exists():
        manifest["route_resources"] = json.loads(resources.read_text(encoding="utf-8"))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    report = out / "reports" / "summary.md"; report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(f"""# Stage 1 run `{config['run_id']}`

## Status

The run generated bounded Dense, BM25, and structural candidate routes. The
node--node gold-positive set was not configured, so candidate recall and route
novelty are intentionally **not reported**. The HF labels remain a separate
query-to-page coverage audit (`{len(coverage)}` queries, `{sum(r['status'] == 'eligible' for r in coverage)}` eligible).

## Reproducibility

See `manifest.json`, `input_audit.json`, `threshold_sweep.csv`, and
`route_overlap.json`. No embedding or existing EvidenceNet artifact was
modified. Thresholds must be selected on an independent reviewed pair set
before claiming a pruning operating point.
""", encoding="utf-8")
    print(json.dumps({"output": str(out), "metrics": str(out / "stage1_metrics.json")}))


if __name__ == "__main__": main()
