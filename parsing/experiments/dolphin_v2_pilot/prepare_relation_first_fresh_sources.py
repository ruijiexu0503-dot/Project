#!/usr/bin/env python3
"""Render only missing representative pages for the cross-data relation shadow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]


def render_pdf(pdf_path: Path, page_number: int, output: Path) -> None:
    with pymupdf.open(pdf_path) as document:
        page = document[page_number - 1]
        scale = 1600 / max(page.rect.width, page.rect.height)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        image = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.sources = args.sources.resolve()
    args.output = args.output.resolve()
    rows = json.loads(args.sources.read_text(encoding='utf-8'))['sources']
    cases, rendered = [], []
    for row in rows:
        if row['mode'] == 'fresh':
            case_id = row.get('case_id', f"relation_{row['document_id']}")
            target = args.output / 'images' / f'{case_id}.png'
            render_pdf(ROOT / row['pdf'], row['page_number'], target)
            cases.append({'case_id': case_id, 'document_type': 'cross_data_source',
                          'input_image': str(target.relative_to(ROOT)), 'audit_focus': ['relation_first_evidence']})
            rendered.append({'document_id': row['document_id'], 'page': row['page'], 'case_id': case_id,
                             'image': str(target), 'kind': 'pdf'})
        elif row['mode'] == 'fresh_image':
            source = ROOT / row['image']
            cases.append({'case_id': f"relation_{row['document_id']}", 'document_type': 'raster_poster',
                          'input_image': str(source.relative_to(ROOT)), 'audit_focus': ['native_raster_poster']})
            rendered.append({'document_id': row['document_id'], 'page': row['page'],
                             'case_id': f"relation_{row['document_id']}", 'image': str(source), 'kind': 'raster'})
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'fresh_cases.json').write_text(json.dumps({'experiment': 'relation_first_fresh_source_parse_v1',
        'production_modified': False, 'cases': cases}, indent=2) + '\n', encoding='utf-8')
    (args.output / 'fresh_sources.json').write_text(json.dumps(rendered, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'fresh_cases': len(cases), 'output': str(args.output), 'production_modified': False}))


if __name__ == '__main__':
    main()
