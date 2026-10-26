#!/usr/bin/env python3
"""Post-node semantic discovery pipeline; see current/EDGE_PIPELINE.md."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from run_evidence_edge_pipeline import main

if __name__ == '__main__':
    main()
