#!/usr/bin/env python3
"""Step 2A: build deterministic EvidenceNodes from aligned parsing output.

Usage from the EvidenceNet directory, for example:
    python pipeline_steps/step2_a_evidencenet_build_nodes.py \
        --doc-id <DOC_ID> --config config/evidence_graph.yaml

This is a thin canonical entrypoint around the existing evidence_graph CLI.
"""

from __future__ import annotations

from pathlib import Path
import sys


def main() -> None:
    evidence_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(evidence_root))
    from evidence_graph.cli import main as cli_main

    cli_main(["build-nodes", *sys.argv[1:]])


if __name__ == "__main__":
    main()
