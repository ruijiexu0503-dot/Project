from __future__ import annotations

import argparse
import json

from .config import load_config
from .pipeline import build_nodes
from .semantic_pipeline import (run_semantic_pilot, verify_existing_pilot, adjudicate_existing_pilot,
                                enrich_existing_formulas, run_content_unit_segmentation, run_full_semantic_graph)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a Phase 1 document-internal Evidence Graph")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("build-nodes", "validate", "run", "semantic-pilot", "semantic-full", "verify-pilot", "rebuild-verify-pilot", "adjudicate-pilot", "enrich-formulas", "segment-content-units"):
        p = sub.add_parser(command)
        p.add_argument("--doc-id", required=True); p.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command == "semantic-pilot":
        print(json.dumps(run_semantic_pilot(args.doc_id, config), indent=2)); return
    if args.command == "semantic-full":
        print(json.dumps(run_full_semantic_graph(args.doc_id, config), indent=2)); return
    if args.command == "verify-pilot":
        print(json.dumps(verify_existing_pilot(args.doc_id, config), indent=2)); return
    if args.command == "rebuild-verify-pilot":
        print(json.dumps(verify_existing_pilot(args.doc_id, config, rebuild_candidates=True), indent=2)); return
    if args.command == "adjudicate-pilot":
        print(json.dumps(adjudicate_existing_pilot(args.doc_id, config), indent=2)); return
    if args.command == "enrich-formulas":
        print(json.dumps(enrich_existing_formulas(args.doc_id, config), indent=2)); return
    if args.command == "segment-content-units":
        print(json.dumps(run_content_unit_segmentation(args.doc_id, config), indent=2)); return
    # Phase 1 is deterministic and cheap; validate rebuilds to avoid validating stale artifacts.
    result = build_nodes(args.doc_id, config)
    print(json.dumps({"output": result["output"], "statistics": result["statistics"],
                      "validation": result["validation"]["summary"]}, indent=2))


if __name__ == "__main__": main()
