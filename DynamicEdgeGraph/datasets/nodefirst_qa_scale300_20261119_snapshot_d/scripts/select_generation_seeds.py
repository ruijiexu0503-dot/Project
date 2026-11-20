#!/usr/bin/env python3
"""Freeze the highest-ranked Snapshot-D evidence groups for generation v2."""

import json
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
TARGETS = {
    "single_node": 240,
    "cross_page": 1800,
    "cross_document_two_doc": 2700,
    "cross_document_three_plus_doc": 1400,
}


def main():
    selected = []
    counts = Counter()
    with (OUT / "sampled_seeds_snapshot_D.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            seed = json.loads(line)
            category = seed["target_category"]
            if counts[category] < TARGETS[category]:
                selected.append(seed)
                counts[category] += 1
    if dict(counts) != TARGETS:
        raise RuntimeError(f"Seed target shortfall: {counts}")
    destination = OUT / "sampled_seeds_snapshot_D_generation_v2.jsonl"
    destination.write_text("".join(json.dumps(seed, ensure_ascii=False) + "\n" for seed in selected), encoding="utf-8")
    summary = {"source_seed_count": sum(1 for line in open(OUT / "sampled_seeds_snapshot_D.jsonl") if line.strip()), "selected": len(selected), "by_category": dict(counts)}
    (OUT / "generation_seed_selection_v2.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
