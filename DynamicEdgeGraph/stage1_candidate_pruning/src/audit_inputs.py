"""Audit actual Stage 1 inputs and HF query/page coverage."""
from __future__ import annotations
import argparse, json, platform, subprocess, time
from pathlib import Path
import numpy as np
from .common import load_config, node_record, read_jsonl, repo_path, resolve_hf_file, run_dir, sha256, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    out = run_dir(config)
    out.mkdir(parents=True, exist_ok=True)
    paths = {key: repo_path(str(config[key])) for key in
             ("node_path", "text_view_path", "embedding_path")}
    for key in ("hf_questions_path", "hf_evidences_path"):
        paths[key] = resolve_hf_file(config, key)
    records, errors = [], []
    for key, path in paths.items():
        item = {"path": str(path), "exists": path.exists()}
        if path.exists() and path.is_file():
            item["bytes"] = path.stat().st_size
            item["sha256"] = sha256(path)
        else:
            errors.append(f"missing:{key}:{path}")
        records.append((key, item))
    all_nodes = []
    if paths["node_path"].exists():
        for i, row in enumerate(read_jsonl(paths["node_path"])):
            try: all_nodes.append(node_record(row, i))
            except ValueError as exc: errors.append(str(exc))
    nodes = all_nodes[:int(config["max_nodes"])] if config.get("max_nodes") else all_nodes
    vector_shape = None
    if paths["embedding_path"].exists():
        vectors = np.load(paths["embedding_path"], mmap_mode="r", allow_pickle=False)
        vector_shape = list(vectors.shape)
        if len(vectors) != len(all_nodes):
            errors.append(f"vector_node_count_mismatch:{len(vectors)}:{len(all_nodes)}")
    ids = [row["node_id"] for row in nodes]
    duplicate_ids = len(ids) - len(set(ids))
    duplicate_note = "view-level duplicate node IDs are retained for frozen-view retrieval and canonicalized at union"
    pages = {(n["document_id"], str(n["page_number"])) for n in nodes}
    hf_rows = []
    if paths["hf_questions_path"].exists():
        evidence_by_query = {}
        if paths["hf_evidences_path"].exists():
            evidence_by_query = {str(r.get("question_id")): r for r in read_jsonl(paths["hf_evidences_path"])}
        for question in read_jsonl(paths["hf_questions_path"]):
            evidences = question.get("evidences", [])
            if not evidences:
                evidences = evidence_by_query.get(str(question.get("question_id")), {}).get("evidences", [])
            mapped = [e for e in evidences if (str(e.get("document_id")), str(e.get("page_number"))) in pages]
            hf_rows.append({"query_id": question.get("question_id"), "source": (question.get("dataset_source_types") or ["unknown"])[0],
                            "evidence_structure": question.get("question_type"), "evidence_count": len(evidences),
                            "mapped_evidence_count": len(mapped), "status": "eligible" if mapped else "unmapped"})
    audit = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "config": config,
        "platform": platform.platform(), "inputs": dict(records), "node_count": len(all_nodes),
        "selected_node_count": len(nodes),
        "unique_node_ids": len(set(ids)), "duplicate_node_ids": duplicate_ids, "embedding_shape": vector_shape,
        "page_keys": len(pages),         "hf_query_count": len(hf_rows), "hf_expected_query_count": 120,
        "hf_eligible_query_count": sum(r["status"] == "eligible" for r in hf_rows),
        "errors": errors, "limitations": ["HF query evidence is page-level and is not Node-Node edge ground truth.",
                       duplicate_note],
    }
    (out / "input_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    write_jsonl(out / "hf_120_coverage.jsonl", sorted(hf_rows, key=lambda x: str(x["query_id"])))
    print(json.dumps({"output": str(out), "node_count": len(all_nodes), "selected_node_count": len(nodes),
                      "hf_query_count": len(hf_rows), "errors": errors}))


if __name__ == "__main__":
    main()
