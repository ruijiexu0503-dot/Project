#!/usr/bin/env python3
"""Step 1D: enrich aligned page JSON and export page Markdown/crops.

Canonical pipeline entrypoint. The implementation remains in
src/enrich_hybrid_aligned_and_export_page_md.py.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "src" / "enrich_hybrid_aligned_and_export_page_md.py"
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])


if __name__ == "__main__":
    main()
