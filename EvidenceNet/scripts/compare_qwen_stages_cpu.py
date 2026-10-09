"""Matched-input staged versus joint page reconstruction, CPU shadow only."""
import argparse
from collections import Counter
import html
import json
import time
import traceback
import run_multimodal_information_unit_pilot as p

OUT = p.ROOT / 'EvidenceNet/output/qwen_stages_comparison_v1_cpu'
CASES = [('DLRmagazine_176_EN', 'page_0012'), ('gw150914_detection_dolphin', 'page_0002')]
SCHEMA = {'items': [{'item_id': 'I1', 'kind': 'article|sidebar|other', 'units': [
    {'unit_id': 'U1', 'role': 'evidence|context|unresolved', 'fragment_ids': ['source ID'],
     'visual_ids': [], 'claim': 'short source-grounded claim, or null',
     'links': [{'fragment_id': 'source ID', 'visual_id': 'source ID',
                'relation': 'CAPTION_OF|DIRECT_EXPLANATION', 'anchor': 'verbatim substring'}]}]}]}


def check(data, fragments, visuals, assignment=False):
    errors, fs, vs, unit_ids, item_ids = [], [], [], [], []
    for item in data['items']:
        item_ids.append(item['item_id'])
        if assignment:
            fs.extend(item['fragment_ids']); vs.extend(item['visual_ids'])
            continue
        for unit in item['units']:
            unit_ids.append(unit['unit_id'])
            fids, vids = unit['fragment_ids'], unit['visual_ids']
            fs.extend(fids); vs.extend(vids)
            if not fids and not vids: errors.append('empty_unit')
            if unit['role'] not in {'evidence', 'context', 'unresolved'}: errors.append('unknown_role')
            linked = set()
            for link in unit.get('links', []):
                f, v = link['fragment_id'], link['visual_id']
                anchor = ' '.join(link['anchor'].split())
                if f not in fids or v not in vids or f not in fragments: errors.append('link_membership')
                elif not anchor or anchor not in ' '.join(fragments[f]['text'].split()): errors.append('anchor_not_verbatim')
                if link['relation'] not in {'CAPTION_OF', 'DIRECT_EXPLANATION'}: errors.append('link_type')
                linked.add(v)
            if fids and vids and linked != set(vids): errors.append('ungrounded_visual_member')
    for label, observed, expected in [('text', fs, set(fragments)), ('visual', vs, set(visuals))]:
        counts = Counter(observed)
        if set(observed) != expected or any(n != 1 for n in counts.values()):
            errors.append({'coverage': label, 'missing': sorted(expected-set(observed)), 'unknown': sorted(set(observed)-expected), 'duplicates': [k for k,v in counts.items() if v>1]})
    if len(set(item_ids)) != len(item_ids) or len(set(unit_ids)) != len(unit_ids): errors.append('duplicate_id')
    return {'valid': not errors, 'errors': errors, 'semantic_review': 'pending'}


def run(preflight=False):
    llm = None
    for index, (doc, page) in enumerate(CASES):
        source = p.SOURCE / doc / page
        target = OUT / doc / page
        rep = p.read(source / 'input_representation.json')
        fragments = p.base.fragments(rep)
        visual_rows = {v['visual_bundle_id']: v for v in rep['visual_bundles']}
        # The same primitive fragments, geometry and labeled images go to both arms.
        # Neither arm receives old flow/assembly decisions.
        presentations = {v['panel_id']:v['image'] for v in p.read(source / 'visual_presentations.json')}
        components = [{'component_id': v, 'modality':'image', 'image':presentations[v]} for v in visual_rows]
        paths = [str(p.source_image(doc, page))] + p.labelled_visual_inputs(components, target)
        source_data = {'text': [{'id': fid, 'text': f['text'], 'geometry': f['atom'].get('geometry_members', [])} for fid,f in fragments.items()],
                       'visuals': [{'id': v, 'geometry': row.get('geometry_members', [])} for v,row in visual_rows.items()]}
        common = ('Inspect the page and labeled visual images. IDs printed on images are authoritative. '
                  'Preserve every input fragment and visual exactly once, including headings, credits and uncertain material. '
                  'Recover reading order from the page, not PDF paint order. Join broken words/sentences by ordered source IDs; never rewrite OCR. '
                  'Each item is a local article or sidebar. Do not merge unrelated items. Preserve simulation/test context. '
                  'Do not use topic similarity alone for visual association.\nSOURCE:\n' + json.dumps(source_data))
        p.write(target / 'inputs.json', {'source': str(source), 'images': paths, 'data': source_data})
        if preflight:
            assert all(p.Path(path).exists() for path in paths)
            print(doc, page, len(fragments), len(visual_rows), flush=True)
            continue
        if llm is None:
            llm = p.create_llm({'provider':'transformers','model':str(p.MODEL),'dtype':'bfloat16','device_map':'cpu','require_cuda':False,'enable_thinking':False})
        # Alternate execution order to reduce systematic warm-up bias.
        for arm in (['staged','joint'] if index % 2 == 0 else ['joint','staged']):
            dest = target / arm
            calls = []
            def invoke(name, prompt):
                p.write(dest / (name + '_request.json'), {'prompt':prompt, 'images':paths})
                started = time.perf_counter()
                gen = llm.generate_raw_with_images('Document reconstruction analyst. JSON only.', prompt, paths, 6000)
                elapsed = time.perf_counter() - started
                record = {'seconds':elapsed, 'output_tokens':len(llm.tokenizer.encode(gen.raw)), 'prompt_characters':len(prompt)}
                calls.append(record)
                p.write(dest / (name + '_raw.json'), {'raw':gen.raw, **record})
                return p.extract_json(gen.raw)
            try:
                constraint = ''
                ownership = None
                if arm == 'staged':
                    ownership = invoke('ownership', common + '\nOnly determine article/side-bar ownership and reading order. Output {"items":[{"item_id":"I1","kind":"article|sidebar|other","fragment_ids":["ordered source IDs"],"visual_ids":["source IDs"]}]}.')
                    audit = check(ownership, fragments, visual_rows, True)
                    p.write(dest / 'ownership_validation.json', audit)
                    if not audit['valid']: raise ValueError('Ownership invalid; no dependent call made')
                    constraint = '\nUse these fixed item memberships and text reading order, only decide unit boundaries and visual associations:\n' + json.dumps(ownership)
                prompt = common + constraint + '\nReturn one nested ledger; unit order is reading order. Every evidence unit is an independently understandable fact or explanation; context and incomplete fragments must remain labeled context/unresolved. Several images may share a caption. Text-only units are allowed. A multimodal unit must ground each visual in a member fragment via a verbatim quote. Body explanation is DIRECT_EXPLANATION, not CAPTION_OF. Use only these fields:\n' + json.dumps(SCHEMA)
                data = invoke('units', prompt)
                audit = check(data, fragments, visual_rows)
                if ownership:
                    fixed = {i['item_id']: i for i in ownership['items']}
                    if {i['item_id'] for i in data['items']} != set(fixed): audit['errors'].append('changed_items')
                    for item in data['items']:
                        orig = fixed.get(item['item_id'], {})
                        fids = [f for u in item['units'] for f in u['fragment_ids']]
                        vids = [v for u in item['units'] for v in u['visual_ids']]
                        if fids != orig.get('fragment_ids') or sorted(vids) != sorted(orig.get('visual_ids', [])):
                            audit['errors'].append('changed_ownership_or_order')
                    audit['valid'] = not audit['errors']
                p.write(dest / 'result.json', data)
                p.write(dest / 'validation.json', audit)
                units = [u for i in data['items'] for u in i['units']]
                metrics = {'valid':audit['valid'], 'units':len(units), 'composites':sum(bool(u['fragment_ids'] and u['visual_ids']) for u in units),
                           'short_evidence_units':[u['unit_id'] for u in units if u['role']=='evidence' and u['fragment_ids'] and sum(len(fragments.get(f,{}).get('text','').strip()) for f in u['fragment_ids'])<=4],
                           'semantic_review':'pending'}
            except Exception:
                metrics = {'valid':False, 'error':traceback.format_exc()}
            metrics.update(calls=calls, call_count=len(calls), inference_seconds=sum(c['seconds'] for c in calls), production_modified=False,
                           edge_stage='not run: matched comparison of reconstruction/node construction only', model=str(p.MODEL))
            p.write(dest / 'metrics.json', metrics)
            print(doc,page,arm,metrics,flush=True)
        # A portable review includes original page and exact source texts, not only paraphrases.
        sections = []
        for arm in ['staged','joint']:
            dest = target / arm
            metrics = p.read(dest / 'metrics.json')
            data = p.read(dest / 'result.json') if (dest / 'result.json').exists() else {}
            sections.append('<section><h2>'+arm+'</h2><pre>'+html.escape(json.dumps(metrics,indent=2))+'</pre>')
            for item in data.get('items',[]):
                sections.append('<h3>'+html.escape(item['item_id'])+'</h3>')
                for u in item['units']:
                    sections.append('<article><pre>'+html.escape(json.dumps(u,ensure_ascii=False,indent=2))+'</pre><p>'+html.escape('\n'.join(fragments[f]['text'] for f in u['fragment_ids'] if f in fragments))+'</p>'+''.join('<img src="'+p.data_uri(presentations[v])+'">' for v in u['visual_ids'] if v in presentations)+'</article>')
            sections.append('</section>')
        (target / 'comparison.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:15px system-ui}main{display:flex;gap:20px}section{width:48%}pre,p{white-space:pre-wrap}article{border:1px solid #aaa;padding:12px}img{max-width:100%;max-height:450px}</style><h1>Matched inputs: staged / joint</h1><p>Structural validation is not semantic validation. Cross-document edge generation is excluded.</p><img src="'+p.data_uri(paths[0])+'"><main>'+''.join(sections)+'</main>')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    run(parser.parse_args().preflight)
