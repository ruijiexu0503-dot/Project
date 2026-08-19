#!/usr/bin/env python3
"""Step 1B: run document layout detection on split-rendered page images.

Canonical pipeline entrypoint. The implementation remains in
src/layout_detection/run_pp_doclayout_detection.py.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "src" / "layout_detection" / "run_pp_doclayout_detection.py"
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])


if __name__ == "__main__":
    main()
