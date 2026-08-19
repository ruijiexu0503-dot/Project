#!/usr/bin/env python3
"""Step 1A: run DeepSeek-OCR parsing on split-rendered pages.

Canonical pipeline entrypoint. The implementation remains in
src/deepseekocr2_parsing/parse_incoming_deepseekocr2_bbox.py so existing imports,
experiments, and history are not broken.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "src" / "deepseekocr2_parsing" / "parse_incoming_deepseekocr2_bbox.py"
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])


if __name__ == "__main__":
    main()
