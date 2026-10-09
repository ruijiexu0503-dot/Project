#!/usr/bin/env python3
"""Stage exact source renders for corpus pages used by the relation-first shadow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]


def render(pdf_path, page_number, output):
    with pymupdf.open(pdf_path) as document:
        page = document[page_number - 1]
        scale = 1600 / max(page.rect.width, page.rect.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    output.parent.mkdir(parents=True, exist_ok=True); image.save(output)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--sources', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output = args.output.resolve()
    rows = json.loads(args.sources.read_text(encoding='utf-8'))['sources']; staged = []
    for row in rows:
        if row['mode'] != 'corpus': continue
        target = args.output / row['document_id'] / f"{row['page']}.png"
        render(ROOT / row['pdf'], row['page_number'], target)
        staged.append({'document_id': row['document_id'], 'page': row['page'], 'image': str(target)})
    (args.output / 'manifest.json').write_text(json.dumps(staged, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'staged': len(staged), 'output': str(args.output), 'production_modified': False}))


if __name__ == '__main__': main()
