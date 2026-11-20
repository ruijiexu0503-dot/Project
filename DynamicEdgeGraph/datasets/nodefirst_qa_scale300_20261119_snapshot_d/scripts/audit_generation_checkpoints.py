#!/usr/bin/env python3
"""Report strict-normalization outcomes for in-progress generation checkpoints."""

import importlib.util
import json
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
BASE = ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/scripts/generate_snapshot_c_shard.py"


def main():
    spec = importlib.util.spec_from_file_location("checkpoint_audit_generator", BASE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    seeds = {
        item["seed_id"]: item
        for item in (json.loads(line) for line in open(OUT / "sampled_seeds_snapshot_D_generation_v2.jsonl", encoding="utf-8") if line.strip())
    }
    outcomes = Counter()
    by_category = Counter()
    examples = []
    checkpoint_root = OUT / "checkpoints/generation_snapshot_D"
    files = sorted(checkpoint_root.glob("shard_*/*.json"))
    for path in files:
        record = json.loads(path.read_text(encoding="utf-8"))
        suffix = path.stem.rsplit("_", 1)[-1]
        seed_id = f"scale300_snapshot_d_seed::{suffix}"
        seed = seeds.get(seed_id)
        if seed is None or "parsed" not in record:
            outcomes["MODEL_OR_SEED_ERROR"] += 1
            continue
        draft, reason = module.normalize(seed, record["parsed"])
        outcome = "VALID" if draft else reason or "INVALID"
        outcomes[outcome] += 1
        if draft:
            by_category[seed["target_category"]] += 1
        examples.append({"seed_id": seed_id, "decision": record["parsed"].get("decision"), "outcome": outcome})
    result = {
        "checkpoint_files": len(files),
        "outcomes": dict(outcomes),
        "valid_by_category": dict(by_category),
        "recent_examples": examples[-10:],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
