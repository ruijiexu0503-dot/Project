#!/usr/bin/env python3
"""CPU adapter preflight; missing planned Dolphin outputs are explicitly pending."""
import argparse
import json
from pathlib import Path
from PIL import Image
import run_relation_first_corpus_shadow as runner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-parsed', action='store_true')
    args = parser.parse_args()
    root = runner.ROOT
    fresh = root / 'parsing/experiments/dolphin_v2_pilot/work/relation_first_fresh'
    old = root / 'EvidenceNet/output/relation_first_corpus_shadow_v1'
    out = root / 'EvidenceNet/output/relation_first_v3_preflight'
    sources = runner.base.read(root / 'EvidenceNet/config/sources/relation_first_multisample_sources.json')['sources']
    results = []
    for row in sources:
        target = out / row['document_id'] / row['page']; target.mkdir(parents=True, exist_ok=True)
        if row['mode'] in {'fresh', 'fresh_image'}:
            case = row.get('case_id', 'relation_' + row['document_id'])
            image = root / row['image'] if row['mode'] == 'fresh_image' else fresh / 'images' / (case + '.png')
            with Image.open(image) as im: im.verify()
            if not (fresh / 'parsed' / case / 'run_summary.json').exists():
                results.append({'document': row['document_id'], 'page': row['page'], 'status': 'pending_dolphin'})
                continue
        if row['mode'] == 'corpus':
            row = {**row, 'mode': 'case', 'image': str(old / 'staged_sources' / row['document_id'] / (row['page'] + '.png'))}
        if row.get('native_override_required'):
            assert (root / 'EvidenceNet/output/bounded_composite_v4_geometry' / row['document_id'] / row['page'] / 'visual_presentations.json').exists()
        atoms, visuals, image = (runner.pptx_representation(row, target, old / 'pptx_native') if row['mode'] == 'pptx'
                                  else runner.dolphin_representation(row, target, fresh))
        rep = {'document_id': row['document_id'], 'page': row['page'], 'atoms': atoms, 'visual_bundles': visuals}
        flow = runner.local_flow(rep)
        assert runner.validate_flow(flow, rep)['valid']
        units = runner.text_units(flow, rep)
        nodes = [{'node_id': str(i), 'fragment_ids': [f], 'visual_ids': []} for i, f in enumerate(runner.base.fragments(rep))]
        nodes += [{'node_id': 'visual_' + v['visual_bundle_id'], 'fragment_ids': [], 'visual_ids': [v['visual_bundle_id']]} for v in visuals]
        runner.validate_components(rep, nodes)
        with Image.open(image) as im: size = im.size
        for visual in visuals:
            with Image.open(visual['presentation']) as im: im.verify()
            runner.candidates_for(visual, units, rep, runner.base.fragments(rep), size)
        results.append({'document': row['document_id'], 'page': row['page'], 'status': 'adapter_passed',
                        'atoms': len(atoms), 'visuals': len(visuals)})
    runner.write(out / 'summary.json', {'pages': results, 'semantic_validation': False})
    ready = {(r['document'], r['page']) for r in results if r['status'] == 'adapter_passed'}
    runner.write(out / 'ready_sources.json', {'sources': [r for r in sources if (r['document_id'], r['page']) in ready]})
    counts = dict(runner.Counter(r['status'] for r in results))
    print(json.dumps(counts))
    if args.require_parsed and counts.get('pending_dolphin'):
        raise SystemExit('Missing Dolphin outputs; refusing to start relation inference')


if __name__ == '__main__':
    main()
