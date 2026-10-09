#!/usr/bin/env python3
"""Evaluate known regression labels, never treat them as independent holdout GT."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path): return json.loads(path.read_text())


def evaluate(root):
    pages = {}
    valid = []
    for audit in root.glob('batch_*/audit.json'):
        valid.extend(read(audit)['pages'])
        for row in read(audit)['pages']:
            pages[row['task']] = [json.loads(line) for line in (audit.parent/'hybrid'/row['task']/'evidence_nodes.jsonl').read_text().splitlines()]
    def joined(task, a, b):
        return any({a, b} <= set(n['source_atom_ids']) for n in pages[task])
    review = read(ROOT/'EvidenceNet/config/reviews/node_generation/hybrid_49page_stress_review_20261007.json')
    wrong = [row for row in review['incorrect_joins'] if row[0] in pages and joined(*row)]
    correct = [row for row in review['correct_flagged_continuations'] if row[0] in pages and joined(*row)]
    mixed = read(ROOT/'EvidenceNet/config/reviews/node_generation/hybrid_mixed_material_review_20261007.json')['pages']
    required = []; missing = []; captions = []; structural = []
    for task, nodes in pages.items():
        key = task.split('/', 1)[1]
        if key not in mixed: continue
        gold = mixed[key]
        for a, b in gold.get('required_continuation_pairs', []):
            required.append([task, a, b])
            if not joined(task, a, b): missing.append([task, a, b])
        for v, a in gold.get('clear_visual_caption_pairs', []):
            captions.append(any(v in n['source_visual_bundle_ids'] and a in n['source_atom_ids'] for n in nodes))
        structural.extend([task, a] for a in gold.get('structural_atom_ids', []) if any(a in n['source_atom_ids'] for n in nodes))
    report = {'pages': len(pages), 'valid_pages': sum(r['valid'] for r in valid),
              'table_atoms_in_valid_pages': sum(r['tables'] for r in valid if r['valid']),
              'known_wrong_merges_remaining': wrong,
              'known_wrong_pairs_evaluated': sum(r[0] in pages for r in review['incorrect_joins']),
              'correct_cross_figure_continuations_retained': correct,
              'required_mixed_continuations': len(required), 'missing_mixed_continuations': missing,
              'correct_mixed_caption_pairs': sum(captions), 'mixed_caption_pairs': len(captions),
              'reviewed_structural_leaks': structural,
              'independent_holdout': False, 'production_promotion': False}
    (root/'regression_evaluation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('root', type=Path)
    evaluate(p.parse_args().root)
