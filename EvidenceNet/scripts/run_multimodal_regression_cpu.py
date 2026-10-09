"""Five-page shadow regression with frozen flows and explicit quality diagnostics."""
import argparse
import json
import shutil
import traceback
from pathlib import Path
import run_multimodal_information_unit_pilot as pilot

OUT = pilot.ROOT / 'EvidenceNet/output/multimodal_regression_v3_cpu'


def prepare(source):
    rep = pilot.read(source / 'input_representation.json')
    flow = pilot.read(source / 'flow.json')
    assembly = pilot.read(source / 'assembly.json')
    components = pilot.make_components(rep, assembly, pilot.read(source / 'visual_presentations.json'))
    units = {'T_' + u['evidence_unit_id']: u for u in assembly['evidence_units']}
    streams = {s['flow_id']: (i['content_item_id'], s) for i in flow['content_items'] for s in i['flows']}
    owners = {v: i['content_item_id'] for i in flow['content_items'] for v in i['visual_panel_ids']}
    for c in components:
        if c['modality'] == 'text':
            u = units[c['component_id']]
            owner, stream = streams[u['flow_id']]
            c.update(content_item_id=owner, flow_id=u['flow_id'], role_hint=stream['flow_kind'],
                     upstream_completeness=u.get('completeness'), role_unresolved=stream.get('role_unresolved', False))
        else:
            c['content_item_id'] = owners[c['source_visual_panel_ids'][0]]
    known = set(pilot.base.fragments(rep))
    used = {f for c in components for f in c.get('source_fragment_ids', [])}
    structural = [r for i in flow['content_items'] for r in i.get('structural_fragments', [])]
    retained = used | {r['fragment_id'] for r in structural}
    assert retained == known, 'source fragment coverage mismatch'
    diagnostics = {
        'short_text_candidates': [c['component_id'] for c in components if c['modality'] == 'text' and len(c['text'].strip()) <= 4],
        'upstream_incomplete': [c['component_id'] for c in components if c.get('upstream_completeness') != 'COMPLETE' and c['modality'] == 'text'],
        'structural_fragments_retained_separately': structural,
        'source_coverage_complete_including_context': retained == known,
        'article_scope': 'frozen page-local content items; not cross-page article reconstruction',
    }
    return rep, flow, components, diagnostics


def run(preflight=False):
    llm = None
    summaries = []
    for source in sorted(pilot.SOURCE.glob('*/*/input_representation.json')):
        source = source.parent
        target = OUT / source.parent.name / source.name
        if preflight:
            target = OUT.with_name(OUT.name + '_preflight') / source.parent.name / source.name
        target.mkdir(parents=True, exist_ok=True)
        try:
            rep, flow, components, audit = prepare(source)
            pilot.write(target / 'input_components.json', components)
            pilot.write(target / 'flow.json', flow)
            pilot.write(target / 'input_audit.json', audit)
            original = pilot.source_image(rep['document_id'], rep['page'])
            assert original.exists()
            paths = pilot.labelled_visual_inputs(components, target)
            assert len(paths) == sum(c['modality'] == 'image' for c in components)
            if preflight:
                print(source, len(components), 'short candidates', len(audit['short_text_candidates']), flush=True)
                continue
            if llm is None:
                llm = pilot.create_llm({'provider': 'transformers', 'model': str(pilot.MODEL), 'dtype': 'bfloat16', 'device_map': 'cpu', 'require_cuda': False, 'enable_thinking': False})
            prompt = pilot.prompt(components) + '\nAdditional constraints: body/main/sidebar prose must not be CAPTION_OF. Preserve simulated/test context when paraphrasing rescue events. Ownership below is a tentative upstream hint; if you propose a cross-owner link, explain it explicitly. Do not repair garbled OCR.\n' + json.dumps([{k: c.get(k) for k in ('component_id', 'content_item_id', 'role_hint', 'role_unresolved')} for c in components])
            pilot.write(target / 'request.json', {'prompt': prompt, 'images': [str(original)] + paths})
            print('START', source, flush=True)
            generation = llm.generate_raw_with_images('Conservative multimodal evidence assembler. JSON only.', prompt, [str(original)] + paths, 3500)
            pilot.write(target / 'raw_generation.json', {'raw': generation.raw})
            response = pilot.extract_json(generation.raw)
            pilot.write(target / 'model_response.json', response)
            groups, errors = pilot.validate_groups(response, components)
            by_id = {c['component_id']: c for c in components}
            accepted = []
            for group in groups:
                reasons = []
                for r in group['internal_relations']:
                    if r['relation'] == 'CAPTION_OF' and by_id[r['source_component']]['role_hint'] in {'main', 'sidebar'}:
                        reasons.append('body_text_as_caption')
                touched = {r[k] for r in group['internal_relations'] for k in ('source_component', 'target_component')}
                if touched != set(group['component_ids']):
                    reasons.append('member_without_relation')
                if reasons:
                    errors.append({'group': group, 'reasons': reasons})
                else:
                    accepted.append(group)
            nodes = pilot.materialize(rep, components, accepted)
            for n in nodes:
                n['model_status'] = n['status']
                n['status'] = 'SEMANTIC_REVIEW_PENDING' if n['unit_type'] == 'COMPOSITE' else 'UNRESOLVED_SOURCE_COMPONENT'
                n['content_item_ids'] = sorted({by_id[c['component_id']]['content_item_id'] for c in n['components']})
                for c in n['components']:
                    c.update({k: by_id[c['component_id']].get(k) for k in ('content_item_id', 'flow_id', 'upstream_completeness', 'role_unresolved')})
            observed = [c['component_id'] for n in nodes for c in n['components']]
            assert sorted(observed) == sorted(by_id)
            pilot.jsonl(target / 'evidence_nodes.jsonl', nodes)
            shutil.copy2(original, target / 'original.png')
            pilot.render(target, nodes, original)
            summary = {'document_id': rep['document_id'], 'page': rep['page'], 'components': len(components), 'composites': len(accepted), 'rejections': errors, 'short_text_candidates': audit['short_text_candidates'], 'cross_owner_groups': [n['node_id'] for n in nodes if len(n['content_item_ids']) > 1], 'component_coverage': True, 'semantic_review': 'pending', 'production_modified': False, 'source_root': str(source), 'model': str(pilot.MODEL), 'parser_view_route': 'frozen bounded v4 representations; native asset or existing figure crop'}
        except Exception:
            summary = {'source': str(source), 'error': traceback.format_exc(), 'production_modified': False}
        pilot.write(target / 'summary.json', summary)
        summaries.append(summary)
        pilot.write(OUT / 'summary.json', summaries)
        print('FINISHED', source, flush=True)
    if not preflight:
        from build_asset_visibility_review import run as visibility_report
        visibility_report(OUT)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    run(parser.parse_args().preflight)
