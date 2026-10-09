#!/usr/bin/env python3
"""Step 2C: assemble article membership and reading order across page snapshots."""
from __future__ import annotations

from pathlib import Path
import sys

EVIDENCENET_ROOT = Path(__file__).resolve().parents[1]
if str(EVIDENCENET_ROOT) not in sys.path:
    sys.path.insert(0, str(EVIDENCENET_ROOT))

from evidence_graph.document_article_graph import main


if __name__ == "__main__":
    main()
