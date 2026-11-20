"""Produce a fixed, query-independent Pilot-local candidate pair table."""
from __future__ import annotations
import argparse, collections, random
from audit_inputs import node_records
from common import load_config, run_dir, stable_pair_id, write_json, write_jsonl

def node_doc_page(node):
    parts = node["node_id"].rsplit("_", 3)
    if len(parts) != 4 or not parts[1].isdigit(): raise ValueError(f"unparseable frozen Pilot node ID: {node['node_id']}")
    return parts[0], int(parts[1])
def make_pairs(nodes, config):
    grouped = collections.defaultdict(list)
    for node in nodes.values(): grouped[node_doc_page(node)].append(node)
    candidates = {}
    window = int(config.get("page_window", 1))
    for (doc, page), members in sorted(grouped.items()):
        for other_page in range(page, page + window + 1):
            for left in members:
                for right in grouped.get((doc, other_page), []):
                    if left["node_id"] >= right["node_id"]: continue
                    pair_id = stable_pair_id(left["node_id"], right["node_id"], config["node_id_namespace"])
                    candidates[pair_id] = {"pair_id": pair_id, "source_node_id": left["node_id"], "target_node_id": right["node_id"], "source_document_id": doc, "target_document_id": doc, "source_page": page, "target_page": other_page, "source_modality": left.get("unit_type"), "target_modality": right.get("unit_type"), "candidate_origin": ["pilot_local_candidate"], "candidate_policy": "same_document_page_window", "node_id_namespace": config["node_id_namespace"], "dataset_id": config["dataset_id"], "dataset_revision": config["dataset_revision"], "stage1_policy": None, "route_support": None, "abc_flags": None, "review_status": "UNREVIEWED"}
    rows = list(candidates.values()); random.Random(int(config.get("seed", 17))).shuffle(rows)
    return rows[:int(config.get("max_pairs", len(rows)))]
def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args(); config = load_config(args.config)
    _, _, nodes, duplicates = node_records(config)
    if duplicates: raise ValueError(f"duplicate Pilot node IDs: {duplicates[:3]}")
    pairs = make_pairs(nodes, config); out = run_dir(config); out.mkdir(parents=True, exist_ok=True)
    count = write_jsonl(out / "pairs.jsonl", pairs); write_json(out / "pair_manifest.json", {"pairs": count, "candidate_origin": "pilot_local_candidate", "query_used": False, "gold_labels_used": False, "seed": config.get("seed"), "max_pairs": config.get("max_pairs")}); print(count)
if __name__ == "__main__": main()
