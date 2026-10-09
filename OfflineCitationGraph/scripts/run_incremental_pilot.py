#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))

from offline_citation_graph.registry import CitationRegistry, extract_front_page_identifiers


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated A-first/B-later offline citation pilot")
    parser.add_argument("--config", default=str(ROOT / "config/gw150914_incremental_pilot.json"))
    parser.add_argument("--output", default=str(ROOT / "output/gw150914_incremental_pilot"))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    registry = CitationRegistry(output / "citation_registry.sqlite", reset=True)
    source = config["source"]
    source_work_id = registry.ingest_aligned_source(
        PROJECT / source["aligned_dir"], PROJECT / source["pdf"],
        [(row["scheme"], row["value"]) for row in source["identifiers"]],
        source["title"], source.get("year"), source.get("version_label"),
    )
    timeline = [{"stage": "source_only", **registry.export(output / "snapshots/01_source_only", source_work_id)}]
    for index, target in enumerate(config["later_arriving_documents"], 2):
        target_pdf = PROJECT / target["pdf"]
        detected_identifiers = extract_front_page_identifiers(target_pdf)
        if not detected_identifiers:
            raise RuntimeError(f"No target identity extracted from {target_pdf}")
        expected = {(row["scheme"], row["value"]) for row in target.get("expected_identifiers", [])}
        if expected and not expected.issubset(set(detected_identifiers)):
            raise RuntimeError(f"Target identity mismatch for {target['slug']}: expected={expected}, detected={detected_identifiers}")
        registry.ingest_target_asset(
            target_pdf, detected_identifiers,
            target["title"], target.get("year"), target.get("version_label"),
        )
        snapshot = output / "snapshots" / f"{index:02d}_after_{target['slug']}"
        timeline.append({"stage": f"after_{target['slug']}", "detected_target_identifiers": detected_identifiers,
                         **registry.export(snapshot, source_work_id)})
    final = registry.export(output, source_work_id)
    (output / "incremental_timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    registry.close()
    print(json.dumps({"final": final, "timeline": timeline}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
