#!/usr/bin/env python3
"""Freeze all 49 v7 shadow pages as source-addressed hybrid stress inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "EvidenceNet/output/relation_first_corpus_shadow_v7_cpu"
OUTPUT = ROOT / "EvidenceNet/output/hybrid_49page_stress_prepared_20261007"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--batches", type=int, default=7)
    args = parser.parse_args()
    source_root, output = args.source_root.resolve(), args.output.resolve()
    sources = sorted(source_root.glob("shard_*/*/*/input_representation.json"))
    if len(sources) != 49:
        raise ValueError(f"Expected the frozen v7 49-page corpus, found {len(sources)} pages")
    if args.batches < 1 or args.batches > len(sources):
        raise ValueError("Invalid batch count")
    rows = []
    for source in sources:
        task = str(source.parent.relative_to(source_root))
        rep = json.loads(source.read_text(encoding="utf-8"))
        image = Path(rep["source_image"]).resolve()
        if not image.is_file():
            raise FileNotFoundError(image)
        with Image.open(image) as page:
            page.verify()
        target = output / task
        target.mkdir(parents=True, exist_ok=True)
        for index, atom in enumerate(rep["atoms"]):
            atom.setdefault("deepseek_order", index)
        for visual in rep["visual_bundles"]:
            visual.setdefault("native_components", [])
        prepared = target / "input_representation.json"
        prepared.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        link = target / "original.png"
        if link.is_symlink() or link.exists():
            if link.resolve() != image:
                raise ValueError(f"Page image mismatch: {link}")
        else:
            link.symlink_to(image)
        atoms = rep["atoms"]
        visuals = rep["visual_bundles"]
        rows.append({"task": task, "source_representation": str(source),
                     "source_representation_sha256": sha(source), "source_image": str(image),
                     "source_image_sha256": sha(image), "atoms": len(atoms),
                     "text_atoms": sum(a["atom_type"] == "text" for a in atoms),
                     "captions": sum(a["atom_type"] == "caption" for a in atoms),
                     "table_atoms": sum(a["atom_type"] == "table" for a in atoms),
                     "visuals": len(visuals),
                     "prior_relation_stage_failed": (source.parent / "failure.json").exists()})
    # Balance crop calls and candidate-set size while retaining every source page.
    buckets = [[] for _ in range(args.batches)]
    costs = [0.0] * args.batches
    capacity = (len(rows) + args.batches - 1) // args.batches
    for row in sorted(rows, key=lambda x: (-3*x["visuals"] - x["text_atoms"] / 5, x["task"])):
        i = min((i for i in range(args.batches) if len(buckets[i]) < capacity),
                key=lambda i: (costs[i], len(buckets[i]), i))
        buckets[i].append(row["task"])
        costs[i] += 3*row["visuals"] + row["text_atoms"] / 5
    manifest = {"tasks": [row["task"] for row in rows], "pages": rows,
                "batches": buckets, "batch_cost_estimates": costs,
                "normalization": "only add parser-order index and empty native-components field; retain original source atoms, fragments, geometries, and visuals",
                "production_modified": False}
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pages": len(rows), "batches": [len(b) for b in buckets],
                      "visuals": sum(r["visuals"] for r in rows),
                      "tables": sum(r["table_atoms"] for r in rows),
                      "prior_failures": sum(r["prior_relation_stage_failed"] for r in rows),
                      "output": str(output)}))


if __name__ == "__main__":
    main()
