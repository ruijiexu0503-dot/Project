#!/usr/bin/env python3
"""Run the strict Node-first generator against Snapshot D in resumable shards."""

import importlib.util
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
BASE = ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/scripts/generate_snapshot_c_shard.py"


def main():
    spec = importlib.util.spec_from_file_location("snapshot_d_generator_base", BASE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.OUT = OUT
    module.SEED_FILENAME = "sampled_seeds_snapshot_D_generation_v2.jsonl"
    module.OUTPUT_TAG = "snapshot_D"
    module.DRAFT_PREFIX = "scale300_snapshot_d"
    module.main()


if __name__ == "__main__":
    main()
