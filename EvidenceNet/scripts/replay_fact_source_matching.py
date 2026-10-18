#!/usr/bin/env python3
"""One-factor, CPU-only replay of frozen fact outputs; never writes source artifacts."""
import argparse
from collections import Counter
import hashlib
import re
from pathlib import Path

from run_fact_grounded_edges import norm, validate_facts
from run_typed_node_edges import catalog
from run_node_context_edges import read, rows, write, jsonl


def layout_norm(value):
    # Only remove an explicit line-wrap hyphen between letters. Ordinary inline
    # hyphens, punctuation and entity names are not rewritten or resolved.
    value = re.sub(r'([^\W\d_])[-\u00ad][ \t]*\r?\n[ \t]*([^\W\d_])', r'\1\2', value)
    return norm(value)


def outcome(value, lookup, normalizer):
    try:
        bound = validate_facts(value, lookup, subject_normalizer=normalizer)
        return {'valid': True, 'facts': len(bound), 'error': None}
    except (ValueError, KeyError, TypeError) as exc:
        return {'valid': False, 'facts': None, 'error': str(exc)}


def replay(source, output):
    if output.exists():
        raise ValueError('Use a fresh output directory')
    frozen = read(source/'verification_manifest.json')['artifact_sha256']
    for name, expected in frozen.items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != expected:
            raise ValueError('source_artifact_changed:'+name)
    nodes = {n['id']: n for n in rows(source/'units.jsonl')}
    policy = read(source/'eligibility.json')
    cases = []
    for path in sorted((source/'facts').glob('*.json')):
        record = read(path); nid = record['node_id']
        _, lookup = catalog(nodes[nid], policy[nid], 'N', source)
        # Replay the last parsed extraction as saved; no model regeneration,
        # support check or relation decision is performed in this experiment.
        value = record['extraction']['value']
        before = outcome(value, lookup, norm)
        after = outcome(value, lookup, layout_norm)
        matches = []
        facts = value.get('facts', []) if isinstance(value, dict) else []
        for i, fact in enumerate(facts if isinstance(facts, list) else []):
            if not isinstance(fact, dict): continue
            subject = fact.get('subject'); anchor = lookup.get(fact.get('subject_evidence_id'))
            if not isinstance(subject, str) or not anchor or anchor['kind'] != 'TEXT': continue
            old = norm(subject) in norm(anchor['quote'])
            new = layout_norm(subject) in layout_norm(anchor['quote'])
            if old != new:
                matches.append({'fact_index': i, 'subject': subject, 'anchor': anchor,
                                'before_match': old, 'after_match': new})
        cases.append({'node_id': nid, 'before': before, 'after': after,
                      'changed_subject_matches': matches,
                      'original_extraction_valid': record['extraction']['valid']})
    summary = {'source': str(source.resolve()), 'nodes': len(cases),
               'factor': 'explicit_line_wrap_hyphen_only',
               'before_valid': sum(c['before']['valid'] for c in cases),
               'after_valid': sum(c['after']['valid'] for c in cases),
               'recovered_nodes': [c['node_id'] for c in cases if not c['before']['valid'] and c['after']['valid']],
               'regressed_nodes': [c['node_id'] for c in cases if c['before']['valid'] and not c['after']['valid']],
               'changed_subject_matches': sum(len(c['changed_subject_matches']) for c in cases),
               'remaining_errors': dict(Counter(c['after']['error'] for c in cases if not c['after']['valid'])),
               'semantic_quality_evaluated': False, 'model_rerun': False,
               'source_sha256_verified': len(frozen), 'production_modified': False}
    output.mkdir(parents=True)
    jsonl(output/'cases.jsonl', cases);write(output/'summary.json', summary)
    print(summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args();replay(args.source, args.output)
