#!/usr/bin/env python3
"""Freeze candidates and prompts before running a matched, prompt-only comparison."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import run_relation_first_corpus_shadow as r


CASES = [
    ('CyberPhysicalModelingChapter4', 'page_0006', 'V_001', 'known_failure'),
    ('CyberPhysicalModelingChapter4', 'page_0006', 'V_002', 'positive_control'),
    ('nvidia_2026_annual_report', 'page_0006', 'V_001', 'known_failure'),
    ('CLADmag_2025_H2', 'page_0006', 'V_001', 'known_failure'),
    ('CLADmag_2025_H2', 'page_0006', 'V_002', 'known_failure'),
    ('DLRmagazine_176_EN', 'page_0012', 'P_0012_A03', 'known_failure'),
    ('gw150914_detection', 'page_0002', 'V_001', 'positive_control'),
    ('entropy', 'page_0010', 'V_001', 'positive_control'),
    ('CyberPhysicalModelingChapter4', 'page_0016', 'V_001', 'transfer_control'),
    ('climate_change_with_ml', 'page_0006', 'V_001', 'transfer_control'),
    ('ML1_11_Reinforcement_Learning_1', 'page_0003', 'V_003', 'transfer_control'),
    ('ESS203_day_01', 'slide_0004', 'V_001', 'transfer_control'),
]
STRESS_PREPARED = Path('EvidenceNet/output/hybrid_49page_stress_prepared_20261007')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(baseline, output, all_eligible=False):
    if output.exists():
        raise ValueError('refuse to overwrite a frozen experiment manifest')
    selected_cases = CASES
    source_pages = []
    if all_eligible:
        folders = sorted(baseline.glob('shard_*/*/*/input_representation.json'))
        if len(folders) != 49:
            raise ValueError(f'expected the complete 49-page regression, found {len(folders)}')
        prepared_by_key = {(p.parent.parent.name, p.parent.name): p
                           for p in STRESS_PREPARED.glob('shard_*/*/*/input_representation.json')}
        selected_cases = []
        for rep_path in folders:
            folder = rep_path.parent
            rep = r.base.read(rep_path)
            key = (rep['document_id'], rep['page'])
            comparison = prepared_by_key.get(key)
            if comparison is None or digest(rep['source_image']) != digest(comparison.parent/'original.png'):
                raise ValueError(f'49-page source image drift: {key}')
            source_pages.append({'document_id': key[0], 'page': key[1],
                                 'image_sha256': digest(rep['source_image']),
                                 'flow_status': r.base.read(folder/'summary.json')['status']})
            ledger_path = folder/'candidate_ledger.json'
            if not ledger_path.exists():
                continue
            ledger = r.base.read(ledger_path)
            for visual in rep['visual_bundles']:
                vid = visual['visual_bundle_id']
                if ledger.get(vid, {}).get('selected'):
                    selected_cases.append((key[0], key[1], vid, 'all_eligible_49page'))
        if len(selected_cases) != 35:
            raise ValueError(f'expected 35 eligible visual cases, found {len(selected_cases)}')
    cases = []
    for n, (doc, page, vid, group) in enumerate(selected_cases):
        matches = list(baseline.glob(f'shard_*/{doc}/{page}'))
        if len(matches) != 1:
            raise ValueError(f'expected one baseline page: {doc}/{page}')
        folder = matches[0]
        rep = r.base.read(folder/'input_representation.json')
        visual = next(v for v in rep['visual_bundles'] if v['visual_bundle_id'] == vid)
        label = 'VISUAL_' + str(rep['visual_bundles'].index(visual)+1).zfill(2)
        candidates = {}
        for c in copy.deepcopy(r.base.read(folder/'candidate_ledger.json')[vid]['selected']):
            c['anchor_protocol'] = 'span-id-v2'
            c['evidence_spans'] = r.source_grounding.evidence_spans(c['unit_id'], c['text'], protocol='span-id-v2')
            candidates[c['unit_id']] = c
        if not candidates:
            raise ValueError('empty comparison case')
        legacy = r.base.read(folder/f'{vid}_edge_prompt.json')['prompt']
        prompts = {'legacy-v2': r.source_grounding.span_prompt(legacy, label, candidates),
                   'grounded-v3': r.source_grounding.grounded_prompt(label, candidates)}
        images = [rep['source_image'], visual['presentation']]
        cases.append({'case_id': f'case_{n:02d}', 'document_id': doc, 'page': page,
                      'visual_id': vid, 'visual_label': label, 'group': group,
                      'baseline': str(folder.resolve()), 'candidates': candidates,
                      'images': images, 'image_hashes': [digest(p) for p in images],
                      'baseline_flow_sha256': digest(folder/'flow.json'),
                      'candidate_ledger_sha256': digest(folder/'candidate_ledger.json'),
                      'prompts': prompts})
    r.write(output, {'experiment': 'frozen_49page_prompt_only_comparison' if all_eligible else 'frozen_prompt_only_comparison',
        'arms': ['legacy-v2', 'grounded-v3'], 'max_new_tokens': 1200,
        'production_modified': False, 'cases': cases,
        'source_pages': source_pages, 'source_page_count': len(source_pages) if all_eligible else None,
        'invariants': 'same source images, frozen flow/candidates, v2 spans, validator and decoding; only prompt differs',
        'limitations': 'purposive diagnostic/transfer controls; not independent human GT or an accuracy estimate'})


def run(args):
    manifest = r.base.read(args.manifest)
    signature = digest(args.manifest)
    for case in manifest['cases']:
        if [digest(p) for p in case['images']] != case['image_hashes']:
            raise ValueError('source image drift')
    config = r.inference_config(args)
    llm = r.base.create_llm(config)
    rows = []
    selected_cases = manifest['cases'][args.shard_index::args.shard_count]
    for case in selected_cases:
        target = args.output / args.arm / case['case_id']
        if (target/'result.json').exists():
            cached = r.base.read(target/'result.json')
            if cached['manifest_sha256'] != signature or cached['inference_config'] != config:
                raise ValueError('resume provenance mismatch')
            rows.append(cached)
            continue
        prompt = case['prompts'][args.arm]
        raw = llm.generate_raw_with_images('Relation-first evidence reviewer. JSON only.', prompt,
                                           case['images'], manifest['max_new_tokens']).raw
        r.write(target/'raw.json', {'raw': raw, 'prompt': prompt})
        row = {k: case[k] for k in ('case_id','document_id','page','visual_id','group')}
        row.update(arm=args.arm, manifest_sha256=signature, inference_config=config,
                   production_modified=False, validator_sha256=digest(r.__file__),
                   grounding_code_sha256=digest(r.source_grounding.__file__))
        try:
            parsed = r.base.extract_json(raw)
            row['proposed'] = copy.deepcopy(parsed)
            normalized, rejected = r.validate_edges_individually(parsed, case['visual_label'], case['candidates'], True)
            row.update(status='complete', accepted=normalized['edges'], rejected=rejected)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            row.update(status='invalid_response', error=str(exc), accepted=[], rejected=[])
        r.write(target/'result.json', row)
        rows.append(row)
        r.write(args.output/args.arm/'summary.json', {'arm': args.arm, 'manifest_sha256': signature,
                    'processed':len(rows),'selected':len(selected_cases),
                    'total_manifest_cases':len(manifest['cases']), 'cases':rows})
        print(json.dumps({k:row[k] for k in ('case_id','arm','status')}, ensure_ascii=False),flush=True)


def aggregate(manifest_path, output, shard_count):
    manifest = r.base.read(manifest_path)
    signature = digest(manifest_path)
    expected = [c['case_id'] for c in manifest['cases']]
    for arm in manifest['arms']:
        results = {}
        for shard in range(shard_count):
            path = output/f'batch_{shard}'/arm/'summary.json'
            summary = r.base.read(path)
            if summary['arm'] != arm or summary['manifest_sha256'] != signature:
                raise ValueError(f'shard provenance mismatch: {path}')
            selected = manifest['cases'][shard::shard_count]
            if [c['case_id'] for c in summary['cases']] != [c['case_id'] for c in selected]:
                raise ValueError(f'shard coverage mismatch: {path}')
            for row in summary['cases']:
                if row['case_id'] in results:
                    raise ValueError(f'duplicate case: {row["case_id"]}')
                results[row['case_id']] = row
        if set(results) != set(expected):
            raise ValueError(f'incomplete {arm}: {sorted(set(expected)-set(results))}')
        rows = [results[case_id] for case_id in expected]
        r.write(output/arm/'summary.json', {'arm': arm, 'manifest_sha256': signature,
                'processed': len(rows), 'selected': len(expected), 'cases': rows,
                'shard_count': shard_count, 'production_modified': False})
        print(json.dumps({'arm': arm, 'cases': len(rows),
                          'invalid': sum(row['status'] != 'complete' for row in rows)},
                         ensure_ascii=False))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--all-eligible',action='store_true',
                   help='prepare every eligible visual case from the matched 49-page regression')
    p.add_argument('--aggregate',action='store_true',
                   help='combine completed batch outputs in manifest order')
    p.add_argument('--shard-count',type=int,default=1)
    p.add_argument('--shard-index',type=int,default=0)
    p.add_argument('--baseline',type=Path,default=Path('EvidenceNet/output/latest_regression_46209'))
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path)
    p.add_argument('--arm',choices=['legacy-v2','grounded-v3'])
    p.add_argument('--model',default=str(r.ROOT/'external/models/Qwen3.5-35B-A3B'))
    p.add_argument('--device',default='cuda',choices=['cuda','cpu'])
    args=p.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        p.error('invalid shard index/count')
    if args.prepare: prepare(args.baseline,args.manifest,args.all_eligible)
    elif args.aggregate:
        if args.output is None: p.error('--output required for aggregation')
        aggregate(args.manifest,args.output,args.shard_count)
    else:
        if args.output is None or args.arm is None:p.error('--output and --arm required for inference')
        run(args)
