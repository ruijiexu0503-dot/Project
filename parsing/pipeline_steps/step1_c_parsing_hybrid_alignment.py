#!/usr/bin/env python3
"""Step 1C: align DeepSeek OCR blocks with layout detections.

Canonical pipeline entrypoint. The implementation remains in
src/hybrid_align_deepseek_layout.py.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "src" / "hybrid_align_deepseek_layout.py"
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])


if __name__ == "__main__":
    main()
