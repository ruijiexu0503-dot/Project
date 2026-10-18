#!/usr/bin/env python3
"""Matched page-level retrieval controls for a frozen VL-DocIR corpus."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from evaluate_vldocir import evaluate, page, rows
from dolphin_text import atom_text

ROOT = Path(__file__).resolve().parents[2]
ARMS = ('page_mean', 'page_windows', 'parser_atoms', 'parser_atoms_visual',
        'hybrid_text', 'hybrid_visual')


def document_model_input(unit):
    """Allowlisted content only; IDs, geometry and development metadata stay outside."""
    if not isinstance(unit.get('text'), str) or not isinstance(unit.get('context'), str):
        raise ValueError('Document model input requires text and context strings')
    return {'title_context': unit['context'], 'content': unit['text']}


def query_model_input(query):
    if not isinstance(query.get('question'), str):
        raise ValueError('Query model input requires a question string')
    return 'Instruct: Retrieve document pages containing evidence to answer the question.\nQuery: ' + query['question']


def text_of(atom):
    return atom_text(atom, semantic=True)


def collect_units(source, nodes):
    from run_hybrid_node_v2 import audit
    manifest = json.loads((source / 'manifest.json').read_text())
    units = {arm: [] for arm in ARMS}
    mappings, stats = [], defaultdict(int)
    def add(arm, pid, uid, text, context):
        if text.strip():
            units[arm].append({'page': pid, 'unit_id': uid, 'text': text, 'context': context})
    for batch, tasks in enumerate(manifest['batches']):
        target = nodes / f'batch_{batch}'
        if not json.loads((target / 'audit.json').read_text())['valid']:
            raise ValueError(f'Invalid node batch: {batch}')
        descriptions = {}
        for row in rows(target / 'baseline/visual_descriptions.jsonl'):
            crop = Path(row['crop'])
            if hashlib.sha256(crop.read_bytes()).hexdigest() != row['crop_sha256']:
                raise ValueError('Stale visual description crop')
            descriptions[row['task'], row['visual_id']] = row['description']
        for task in tasks:
            if not audit(task, source, target / 'hybrid')['valid']:
                raise ValueError(f'Current node coverage failed: {task}')
            rep = json.loads((source / task / 'input_representation.json').read_text())
            run = json.loads((target / 'hybrid' / task / 'run_summary.json').read_text())
            expected_hashes = {'input_representation': hashlib.sha256((source / task / 'input_representation.json').read_bytes()).hexdigest(),
                               'source_image': hashlib.sha256((source / task / 'original.png').read_bytes()).hexdigest()}
            if not run['decision_valid'] or run['input_hashes'] != expected_hashes:
                raise ValueError(f'Stale or invalid hybrid result: {task}')
            pid = (str(rep['document_id']), str(rep['page']))
            # Only document/page titles parsed from source or dataset document metadata.
            # All arms receive the same context, including titles excluded from evidence.
            context = '\n'.join([str(rep['document_title'])] + rep['page_headings'])
            eligible = [a for a in sorted(rep['atoms'], key=lambda a: a['deepseek_order'])
                        if a['atom_type'] != 'furniture']
            page_text = '\n'.join(text_of(a) for a in eligible)
            for arm in ('page_mean', 'page_windows'):
                add(arm, pid, task, page_text or context, context)
            for atom in eligible:
                for arm in ('parser_atoms', 'parser_atoms_visual'):
                    add(arm, pid, f"{task}/{atom['atom_id']}", text_of(atom), context)
            for visual in rep['visual_bundles']:
                vid = visual['visual_bundle_id']
                add('parser_atoms_visual', pid, f'{task}/{vid}', descriptions[task, vid], context)
            for row in rows(target / 'hybrid' / task / 'evidence_nodes.jsonl'):
                mappings.append({'node_id': row['node_id'], 'source_pages': [
                    {'document_id': pid[0], 'page_number': int(pid[1])}]})
                semantic = row.get('semantic_text', row['plain_text'])
                add('hybrid_text', pid, row['node_id'], semantic, context)
                text = '\n'.join(s for s in (semantic, row.get('visual_description')) if s)
                add('hybrid_visual', pid, row['node_id'], text, context)
                stats['nodes'] += 1
            # Structural headings remain separately addressable for title-only queries.
            # The same source headings are already eligible in parser controls.
            for atom in eligible:
                if atom['atom_type'] == 'heading':
                    for arm in ('hybrid_text', 'hybrid_visual'):
                        add(arm, pid, f"{task}/structural/{atom['atom_id']}", text_of(atom), context)
            stats['pages'] += 1
            stats['visuals'] += len(rep['visual_bundles'])
    if len({r['node_id'] for r in mappings}) != len(mappings):
        raise ValueError('Duplicate EvidenceNode ID')
    return units, mappings, dict(stats)


def windows(tokens, size=384, stride=320):
    if not tokens:
        return [[]]
    result = []
    for start in range(0, len(tokens), stride):
        result.append(tokens[start:start + size])
        if start + size >= len(tokens):
            break
    return result


def with_special_tokens(tokenizer, ids):
    """Apply the tokenizer's template to existing IDs without retokenizing windows."""
    legacy = getattr(tokenizer, 'build_inputs_with_special_tokens', None)
    if callable(legacy):
        return legacy(ids)
    suffix = getattr(tokenizer, '_vldocir_special_suffix', None)
    if suffix is None:
        # Qwen3-Embedding appends EOS. Verify the loaded tokenizer's actual
        # template rather than assuming its EOS ID or decoding token windows.
        suffix = tokenizer.encode('', add_special_tokens=True)
        for text in ('Tokenizer template probe', '科学 evidence <|endoftext|>'):
            plain = tokenizer.encode(text, add_special_tokens=False)
            if tokenizer.encode(text, add_special_tokens=True) != plain + suffix:
                raise ValueError('Unsupported tokenizer special-token template')
        if tokenizer.num_special_tokens_to_add(pair=False) != len(suffix):
            raise ValueError('Inconsistent tokenizer special-token template')
        tokenizer._vldocir_special_suffix = suffix
    return list(ids) + suffix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--nodes', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=ROOT / 'EvidenceNet/models/Qwen3-Embedding-0.6B')
    args = parser.parse_args()
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer
    units, mappings, stats = collect_units(args.source, args.nodes)
    queries = list(rows(args.pilot / 'queries.jsonl'))
    evidence = list(rows(args.pilot / 'gold_evidence.jsonl'))
    corpus = {page(r) for r in rows(args.pilot / 'corpus_pages.jsonl')}
    if {u['page'] for u in units['page_mean']} != corpus or stats['pages'] != len(corpus):
        raise ValueError('Prepared corpus differs from the frozen evaluation corpus')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'node_pages.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in mappings))
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, padding_side='left')
    model = AutoModel.from_pretrained(args.model, local_files_only=True,
                                     torch_dtype=torch.bfloat16).cuda().eval()
    # Deduplicate identical token windows across arms, preserving all page text.
    token_cache, window_index, sequences, indices = {}, {}, [], {}
    def tokenize(text):
        if text not in token_cache:
            token_cache[text] = tokenizer.encode(text, add_special_tokens=False)
        return token_cache[text]
    for arm in ARMS:
        indices[arm] = []
        for unit in units[arm]:
            payload = document_model_input(unit)
            context = tokenize(payload['title_context'])[:64]
            current = []
            for chunk in windows(tokenize(payload['content'])):
                ids = tuple(with_special_tokens(tokenizer, context + chunk))
                if ids not in window_index:
                    window_index[ids] = len(sequences)
                    sequences.append(list(ids))
                current.append(window_index[ids])
            indices[arm].append(current)
    print(json.dumps({'unique_document_windows': len(sequences), **stats}), flush=True)
    def encode(seqs):
        result = []
        for start in range(0, len(seqs), 16):
            encoded = tokenizer.pad({'input_ids': seqs[start:start + 16]}, padding=True,
                                    return_tensors='pt').to('cuda')
            with torch.inference_mode():
                vector = model(**encoded).last_hidden_state[:, -1].float()
                vector = torch.nn.functional.normalize(vector, p=2, dim=1)
            result.append(vector.cpu().numpy())
        return np.concatenate(result)
    vectors = encode(sequences)
    query_sequences = []
    for q in queries:
        ids = tokenize(query_model_input(q))
        if len(ids) > 512:
            raise ValueError('Query exceeds encoder budget; do not silently truncate it')
        query_sequences.append(with_special_tokens(tokenizer, ids))
    query_vectors = encode(query_sequences)
    similarities = query_vectors @ vectors.T
    results = {}
    for arm in ARMS:
        page_scores = defaultdict(lambda: np.full(len(queries), -np.inf))
        for unit, selected in zip(units[arm], indices[arm]):
            if arm == 'page_mean':
                pooled = vectors[selected].mean(axis=0)
                pooled /= max(float(np.linalg.norm(pooled)), 1e-12)
                score = query_vectors @ pooled
            else:
                score = similarities[:, selected].max(axis=1)
            page_scores[unit['page']] = np.maximum(page_scores[unit['page']], score)
        scores = [{'question_id': q['question_id'], 'document_id': pid[0],
                   'page_number': int(pid[1]), 'score': float(values[qi])}
                  for pid, values in sorted(page_scores.items()) for qi, q in enumerate(queries)]
        (args.output / f'{arm}_scores.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in scores))
        report = evaluate(queries, evidence, scores, corpus=corpus)
        report.update(scope='pilot', corpus_pages=len(corpus), arm=arm,
                      title_context='same document title and source page headings in all arms; max64tokens',
                      encoder=str(args.model.resolve()), document_window=384, stride=320,
                      pooling='normalized mean of window vectors' if arm == 'page_mean' else 'max window/unit score per page',
                      description_policy='unverified Qwen retrieval hints' if 'visual' in arm else 'source text only')
        results[arm] = report
        (args.output / f'{arm}_metrics.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'arm': arm, 'macro': report['macro_six_types']}), flush=True)
    # Paired, type-stratified bootstrap; 24 queries support only exploratory conclusions.
    rng = np.random.default_rng(20261009)
    comparisons = {}
    for control, treatment in [('page_windows', 'hybrid_visual'),
                               ('parser_atoms_visual', 'hybrid_visual'),
                               ('parser_atoms', 'hybrid_text'),
                               ('hybrid_text', 'hybrid_visual')]:
        metric = 'nDCG@5'
        groups = defaultdict(list)
        for q in queries:
            qid = q['question_id']
            groups[q['question_type']].append(results[treatment]['per_query'][qid][metric]
                                             - results[control]['per_query'][qid][metric])
        samples = np.mean([rng.choice(v, size=(2000, len(v)), replace=True).mean(axis=1)
                           for v in groups.values()], axis=0)
        comparisons[f'{treatment}_vs_{control}'] = {
            'metric': metric, 'macro_delta': float(np.mean([np.mean(v) for v in groups.values()])),
            'bootstrap_95_interval': list(map(float, np.quantile(samples, [.025, .975])))}
    summary = {'scope': 'selected-corpus workflow pilot; not official full-corpus scores',
               'queries': len(queries), 'corpus_pages': len(corpus), **stats,
               'arms': {arm: r['macro_six_types'] for arm, r in results.items()},
               'comparisons': comparisons, 'graph_expansion': False,
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'small_sample_warning': '24 queries; improvements require a larger fixed holdout and corpus'}
    (args.output / 'comparison.json').write_text(json.dumps(summary, indent=2) + '\n')
    lines = ['# VL-DocIR pilot retrieval comparison', '',
             f"{len(queries)} queries; {len(corpus)} pages. Selected corpus; no graph expansion.", '',
             '| Arm | Macro Recall@5 | Macro nDCG@5 | Macro RecallAll@5 |',
             '|---|---:|---:|---:|']
    for arm, report in results.items():
        m = report['macro_six_types']
        lines.append(f"| {arm} | {m['Recall@5']:.4f} | {m['nDCG@5']:.4f} | {m['RecallAll@5']:.4f} |")
    lines += ['', 'All arms use the same encoder, title context and full-text token windows.',
              'parser_atoms_visual and hybrid_visual share identical Qwen descriptions.',
              'Visual descriptions are unverified retrieval hints.',
              '24 queries support an exploratory pilot, not a full-corpus superiority claim.']
    (args.output / 'report.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
