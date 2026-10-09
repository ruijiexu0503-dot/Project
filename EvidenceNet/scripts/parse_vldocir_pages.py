#!/usr/bin/env python3
"""Parse official VL-DocIR images with Dolphin, preserving page IDs and coordinates."""
import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / 'parsing/experiments/dolphin_v2_pilot'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=PILOT / 'models/Dolphin-v2')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=18)
    parser.add_argument('--max-side', type=int, default=2000)
    args = parser.parse_args()
    if args.offset < 0 or args.limit < 1 or args.max_side < 1:
        parser.error('Invalid page range or image size')
    pages = list(map(json.loads, args.pages.read_text().splitlines()))[args.offset:args.offset + args.limit]
    if not pages:
        raise ValueError('Empty page selection')
    sys.path.insert(0, str(PILOT / 'vendor/Dolphin'))
    from demo_page import DOLPHIN, process_elements
    from utils.utils import save_outputs, setup_output_dirs
    model = DOLPHIN(str(args.model))
    failures = []
    for row in pages:
        page_id = f"page_{int(row['page_number']):04d}"
        work = args.output / row['document_id'] / page_id
        summary = work / 'run_summary.json'
        config = {'source_sha256': row['sha256'], 'max_side': args.max_side,
                  'model': str(args.model.resolve())}
        if summary.exists():
            previous = json.loads(summary.read_text())
            if previous.get('status') == 'complete' and previous.get('config') == config:
                print(f'[skip] {work}', flush=True)
                continue
            raise ValueError(f'Incompatible checkpoint: {summary}')
        started = time.monotonic()
        setup_output_dirs(str(work))
        try:
            with Image.open(row['image_path']) as source:
                image = source.convert('RGB')
            original_size = image.size
            image.thumbnail((args.max_side, args.max_side), Image.Resampling.LANCZOS)
            image.save(work / 'original.png')
            layout = model.chat('Parse the reading order of this document.', image)
            (work / 'layout_raw.txt').write_text(layout)
            elements = process_elements(layout, image, model, 2, str(work), page_id)
            if not elements:
                raise ValueError('Dolphin returned no elements')
            save_outputs(elements, image, page_id, str(work), post_process=False)
            result = {**row, 'status': 'complete', 'config': config,
                      'original_image_size': list(original_size), 'image_size': list(image.size),
                      'bbox_coordinate_space': 'resized_image_pixels',
                      'scale_to_original': [original_size[0] / image.width, original_size[1] / image.height],
                      'element_count': len(elements), 'elapsed_seconds': time.monotonic() - started}
            summary.write_text(json.dumps(result, indent=2))
            print(f'[done] {work}: {len(elements)} elements', flush=True)
        except Exception as exc:
            failures.append({'document_id': row['document_id'], 'page_number': row['page_number'], 'error': str(exc)})
            (work / 'failure.json').write_text(json.dumps(failures[-1], indent=2))
            print(f'[failed] {work}: {exc}', flush=True)
    if failures:
        raise SystemExit(f'{len(failures)} pages failed; see failure.json checkpoints')


if __name__ == '__main__':
    main()
