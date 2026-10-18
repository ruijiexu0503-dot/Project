#!/usr/bin/env python3
"""Adapt Dolphin elements to EvidenceNode source atoms without gold labels."""
import argparse
import json
import math
import shutil
from collections import Counter
from pathlib import Path

from dolphin_text import POLICY as SEMANTIC_TEXT_POLICY, normalize_dolphin_text_with_decisions


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def adapt(elements, row, summary, document):
    width, height = summary['image_size']
    atoms, visuals = [], []
    labels = Counter()
    break_counts = Counter()
    for index, element in enumerate(elements):
        label = str(element.get('label') or 'unknown')
        labels[label] += 1
        bbox = element.get('bbox')
        if (not isinstance(bbox, list) or len(bbox) != 4
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bbox)
                or not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height)):
            raise ValueError(f'Invalid Dolphin bbox: {row}/{index}: {bbox}')
        aid = f'D{index + 1:04d}'
        geometry = [{'member_id': f'{aid}_geometry', 'bbox': bbox,
                     'bbox_source': 'dolphin_v2_resized_image_pixels'}]
        if label == 'fig':
            visuals.append({'visual_bundle_id': f'V{index + 1:04d}', 'bbox': bbox,
                            'layout_label': label, 'geometry_members': geometry,
                            'native_components': [], 'parser_order': element.get('reading_order', index)})
            continue
        # Wikipedia page titles can be mislabeled as header. Preserve as structure
        # using source type and location only; never use query/evidence annotations.
        wiki_title = (document['data_source'] == 'wiki' and label == 'header'
                      and bbox[1] >= .025 * height and bbox[3] <= .15 * height)
        kind = ('heading' if label.startswith('sec') or label == 'title' or wiki_title
                else 'furniture' if label in {'header', 'foot', 'footer', 'page_num', 'page_number'}
                else 'caption' if label == 'cap' else 'table' if label == 'tab' else 'text')
        text = str(element.get('text') or '')
        semantic_text, semantic_breaks = normalize_dolphin_text_with_decisions(text, label)
        break_counts.update(item['decision'] for item in semantic_breaks)
        atoms.append({'atom_id': aid, 'atom_type': kind,
                      'layout_role': 'heading' if wiki_title else label,
                      'text_preview': text, 'semantic_preview': semantic_text,
                      'text_length': len(text), 'semantic_text_length': len(semantic_text),
                      'deepseek_order': element.get('reading_order', index),
                      'text_fragments': [{'fragment_id': f'{aid}_F001', 'source_atom_id': aid,
                                          'char_start': 0, 'char_end': len(text), 'text': text,
                                          'semantic_text': semantic_text,
                                          'semantic_text_policy': SEMANTIC_TEXT_POLICY,
                                          'semantic_text_breaks': semantic_breaks}],
                      'geometry_members': geometry, 'source_element_index': index})
    return {'document_id': row['document_id'], 'page': int(row['page_number']),
            'atoms': atoms, 'visual_bundles': visuals,
            'document_title': document.get('title', ''),
            'page_headings': [a['semantic_preview'] for a in atoms if a['atom_type'] == 'heading'],
            'source_parser': 'Dolphin-v2', 'bbox_coordinate_space': 'resized_image_pixels',
            'semantic_text_policy': SEMANTIC_TEXT_POLICY,
            'semantic_text_break_counts': dict(break_counts),
            'raw_text_is_immutable_source': True,
            'image_size': [width, height], 'scale_to_original': summary['scale_to_original'],
            'official_image_sha256': row['sha256'], 'label_distribution': dict(labels)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', type=Path, required=True)
    parser.add_argument('--documents', type=Path, required=True)
    parser.add_argument('--parsed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--batch-size', type=int, default=4)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error('batch-size must be positive')
    documents = {r['document_id']: r for r in rows(args.documents)}
    tasks = []
    for row in rows(args.pages):
        task = f"{row['document_id']}/page_{int(row['page_number']):04d}"
        source = args.parsed / task
        summary = json.loads((source / 'run_summary.json').read_text())
        if summary['status'] != 'complete' or summary['config']['source_sha256'] != row['sha256']:
            raise ValueError(f'Incomplete or stale parsing: {task}')
        elements = json.loads((source / 'output_json' / f"page_{int(row['page_number']):04d}.json").read_text())
        rep = adapt(elements, row, summary, documents[row['document_id']])
        target = args.output / task
        target.mkdir(parents=True, exist_ok=True)
        destination = target / 'input_representation.json'
        encoded = json.dumps(rep, ensure_ascii=False, indent=2) + '\n'
        if destination.exists() and destination.read_text() != encoded:
            raise ValueError(f'Changed frozen representation: {task}')
        destination.write_text(encoded)
        shutil.copy2(source / 'original.png', target / 'original.png')
        tasks.append(task)
    manifest = {'tasks': tasks, 'pages': len(tasks), 'batch_size': args.batch_size,
                'batches': [tasks[i:i + args.batch_size] for i in range(0, len(tasks), args.batch_size)],
                'source_pages': str(args.pages.resolve()), 'uses_gold_annotations': False,
                'semantic_text_policy': SEMANTIC_TEXT_POLICY,
                'raw_text_is_immutable_source': True}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'pages': len(tasks), 'batches': len(manifest['batches'])}))


if __name__ == '__main__':
    main()
