#!/usr/bin/env python3
"""Discover diverse Snapshot-D QA evidence groups from formal canonical nodes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
BASE = ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/scripts/discover_snapshot_c_semantic_candidates.py"


def load_module():
    spec = importlib.util.spec_from_file_location("snapshot_d_discovery_base", BASE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def family(node):
    document = node["document_id"].lower()
    if document.startswith(tuple(f"real_{index:03d}_" for index in range(49, 72))):
        return "nih_medlineplus_magazines"
    if document.startswith("real_072_"):
        return "climate_policy_monitor"
    if document.startswith("real_073_"):
        return "ecological_adaptation_research"
    if document.startswith(("real_074_", "real_075_")):
        return "conservation_field_stories"
    if document.startswith(("short_001_", "short_004_")):
        return "cdc_health_planning"
    if document.startswith("short_002_"):
        return "education_reporting"
    if document.startswith(("short_003_", "short_016_")):
        return "governance_and_data_standards"
    if document.startswith("short_005_"):
        return "usda_portal"
    if document.startswith(("short_006_", "short_015_")):
        return "climate_finance_adaptation"
    if document.startswith("short_007_"):
        return "usgs_coastal_science"
    if document.startswith(("short_008_", "short_012_", "short_013_")):
        return "library_of_congress"
    if document.startswith(("short_009_", "short_010_", "short_011_")):
        return "noaa_strategic_ocean_planning"
    if document.startswith("short_014_"):
        return "getty_arts"
    if document.startswith("short_017_"):
        return "epa_paperless_business"
    return "other_non_nasa"


def main():
    formal = OUT / "snapshot_D_formal_canonical_nodes.jsonl"
    if not formal.is_file():
        raise FileNotFoundError(formal)
    alias = OUT / "snapshot_C_canonical_nodes.jsonl"
    if not alias.exists():
        alias.symlink_to(formal.name)
    base = load_module()
    base.OUT = OUT
    base.TARGETS = {
        "single_node": 600,
        "cross_page": 2000,
        "cross_document_two_doc": 3500,
        "cross_document_three_plus_doc": 1800,
    }
    base.MAX_DOCUMENT_USES = 600
    base.family = family
    base.main()

    source = OUT / "sampled_seeds_snapshot_C.jsonl"
    seeds = []
    with source.open(encoding="utf-8") as handle:
        for serial, line in enumerate(handle, 1):
            seed = json.loads(line)
            seed["seed_id"] = f"scale300_snapshot_d_seed::{serial:05d}"
            seed["snapshot_id"] = "snapshot_D_formal_nodes_20261119"
            seeds.append(seed)
    destination = OUT / "sampled_seeds_snapshot_D.jsonl"
    destination.write_text("".join(json.dumps(seed, ensure_ascii=False) + "\n" for seed in seeds), encoding="utf-8")
    base_summary = json.loads((OUT / "seed_discovery_snapshot_C.json").read_text(encoding="utf-8"))
    base_summary["snapshot_id"] = "snapshot_D_formal_nodes_20261119"
    base_summary["formal_node_source"] = str(formal.resolve())
    base_summary["nasa_documents_included"] = 0
    (OUT / "seed_discovery_snapshot_D.json").write_text(
        json.dumps(base_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(base_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
