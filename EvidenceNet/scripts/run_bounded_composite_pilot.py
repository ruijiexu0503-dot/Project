#!/usr/bin/env python3
"""Frozen-flow regression: bounded caption decisions, deterministic assembly."""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from PIL import Image
from bounded_geometry import candidates_for, source_anchor

import run_flow_first_evidence_pilot as base
import run_composite_evidence_pilot as composite

SOURCE = base.ROOT / 'EvidenceNet/output/composite_evidence_pilot_v3_recomposed_components'
OUT = base.ROOT / 'EvidenceNet/output/bounded_composite_v3_geometry'


def restore_uncertain(flow):
    flow = copy.deepcopy(flow)
    restored = []
    for item in flow['content_items']:
        keep = []
        for row in item.get('structural_fragments', []):
            if row.get('role') not in {'title', 'section_heading', 'dek', 'byline', 'page_furniture', 'logo'}:
                fid = row['fragment_id']
                restored.append(fid)
                item['flows'].append({'flow_id': item['content_item_id'] + '_REVIEW_' + fid,
                                      'flow_kind': 'main', 'fragment_ids': [fid],
                                      'role_unresolved': True})
            else:
                keep.append(row)
        item['structural_fragments'] = keep
    return flow, restored


def text_units(flow, rep):
    fragments = base.fragments(rep)
    units = []
    for item in flow['content_items']:
        for stream in item['flows']:
            groups = []
            continuations = {(e['from_fragment_id'], e['to_fragment_id'])
                             for e in stream.get('continuations', []) if e['kind'] == 'same_sentence'}
            for fid in stream['fragment_ids']:
                same_block = groups and fragments[groups[-1][-1]]['atom']['atom_id'] == fragments[fid]['atom']['atom_id']
                same_sentence = groups and (groups[-1][-1], fid) in continuations
                if groups and (same_block or same_sentence or stream['flow_kind'] == 'caption'):
                    groups[-1].append(fid)
                else:
                    groups.append([fid])
            for ids in groups:
                units.append({'evidence_unit_id': f'EU_{len(units)+1:03d}',
                              'content_item_id': item['content_item_id'], 'flow_id': stream['flow_id'],
                              'unit_type': 'TEXT', 'fragment_ids': ids, 'visual_panel_ids': [],
                              'completeness': 'UNRESOLVED' if stream.get('role_unresolved') else 'POSSIBLE_CONTINUATION',
                              'caption_candidate': stream['flow_kind'] == 'caption' or stream.get('role_unresolved', False)})
    return units


def validate_decision(row, visual, candidates):
    if row.get('visual_id') != visual or row.get('decision') not in {'MATCH', 'NONE', 'UNCERTAIN'}:
        raise ValueError('invalid visual_id or decision')
    if not isinstance(row.get('basis'), str) or not row['basis'].strip():
        raise ValueError('missing association basis')
    caption = row.get('caption_unit_id')
    if row['decision'] == 'MATCH' and caption not in candidates:
        raise ValueError('unknown caption unit')
    if row['decision'] != 'MATCH' and caption is not None:
        raise ValueError('non-match must use null caption_unit_id')


def validate_review(row, visual_ids, text):
    if row.get('text_quality') not in {'UNVERIFIED', 'SUSPECT'}:
        raise ValueError('missing text_quality')
    if not isinstance(row.get('basis'), str) or not row['basis'].strip():
        raise ValueError('missing review basis')
    if not isinstance(row.get('accepted'), list):
        raise ValueError('accepted must be a list')
    seen = set()
    anchors = []
    for match in row['accepted']:
        vid, anchor = match.get('visual_id'), match.get('anchor')
        if vid not in visual_ids or vid in seen:
            raise ValueError('unknown or duplicate visual')
        resolved = source_anchor(text, anchor)
        if match.get('relation') not in {'CAPTION', 'DIRECT_EXPLANATION'}:
            raise ValueError('invalid relation')
        seen.add(vid)
        match.update(resolved)
        anchors.append(' '.join(resolved['anchor'].split()))
    if len(anchors) > 1 and any(a in b or b in a for i, a in enumerate(anchors) for b in anchors[i+1:]):
        raise ValueError('shared caption needs distinct non-containing image-specific anchors')


def opaque_review_ids(visual_ids):
    """Keep parser/path words out of semantic evidence presented to the reviewer."""
    forward = {visual_id: f'VISUAL_{index:02d}' for index, visual_id in enumerate(visual_ids, 1)}
    return forward, {label: visual_id for visual_id, label in forward.items()}


def restore_review_ids(row, reverse):
    row = copy.deepcopy(row)
    for match in row.get('accepted', []):
        match['visual_id'] = reverse.get(match.get('visual_id'), match.get('visual_id'))
    return row


def assemble(units, flow, decisions, reviews):
    units = copy.deepcopy(units)
    by_id = {u['evidence_unit_id']: u for u in units}
    owners = {v: item['content_item_id'] for item in flow['content_items'] for v in item['visual_panel_ids']}
    accepted = {m['visual_id']: (cid, m) for cid, r in reviews.items() for m in r['accepted']}
    for decision in decisions:
        vid = decision['visual_id']
        if vid in accepted:
            cid, match = accepted[vid]
            unit = by_id[cid]
            unit['visual_panel_ids'].append(vid)
            unit['unit_type'] = 'COMPOSITE'
            unit.setdefault('visual_text_links', []).append(match)
            unit['association_basis'] = reviews[cid]['basis']
            unit['text_quality'] = reviews[cid]['text_quality']
            if unit['text_quality'] == 'SUSPECT':
                unit['completeness'] = 'UNRESOLVED'
        else:
            units.append({'evidence_unit_id': f'EU_{len(units)+1:03d}', 'content_item_id': owners[vid],
                          'flow_id': None, 'unit_type': 'VISUAL', 'fragment_ids': [], 'visual_panel_ids': [vid],
                          'completeness': 'UNRESOLVED', 'association_basis': 'No verified direct text association'})
    return {'evidence_units': units, 'context_items': [], 'relations': []}


def paper_inputs(source, target, llm, local_only):
    """Reuse Dolphin figures; infer paper flows separately from association."""
    rep = base.read(source / 'input_representation.json')
    original = base.ROOT / 'EvidenceNet/output/dolphin_paper_node_pipeline_v1/prepared/raw' / rep['document_id'] / rep['page'] / 'page.png'
    presentations = []
    for i, visual in enumerate(rep['visual_bundles'], 1):
        vid = visual['visual_bundle_id']
        path = source / 'visual_crops' / f'crop_{i:02d}_{vid}.png'
        if not path.exists():
            raise FileNotFoundError(path)
        presentations.append({'panel_id': vid, 'image': str(path), 'mode': 'dolphin_complete_figure_crop'})
    if local_only:
        streams = [{'flow_id': 'LOCAL_' + a['atom_id'], 'flow_kind': 'caption' if a['atom_type'] == 'caption' else 'main',
                    'fragment_ids': [f['fragment_id'] for f in a.get('text_fragments', [])], 'continuations': []}
                   for a in rep['atoms'] if a.get('text_fragments')]
        flow = {'content_items': [{'content_item_id': 'CI_1', 'flows': streams, 'structural_fragments': [],
                                  'visual_panel_ids': [v['visual_bundle_id'] for v in rep['visual_bundles']]}]}
    else:
        prompt = composite.flow_prompt(rep)
        for attempt in range(3):
            raw = llm.generate_raw_with_images('Document reading-flow analyst. JSON only.', prompt, [str(original)], 6000).raw
            base.write(target / f'paper_flow_attempt{attempt}.json', {'raw': raw})
            try:
                flow = base.extract_json(raw)
                check = composite.validate_flow(flow, rep)
                if not check['valid']:
                    raise ValueError(check['errors'])
                break
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                prompt += '\nCorrect the coverage/schema errors: ' + str(exc)
        else:
            raise ValueError('Paper reading flow invalid after three attempts: ' + str(source))
    base.write(target / 'paper_input_provenance.json', {'source': str(source), 'source_parser': 'Dolphin-v2',
               'original': str(original), 'flow': 'local coverage stub' if local_only else 'new Qwen reading flow',
               'visual_policy': 'existing complete figure crop; no new native extraction'})
    return rep, flow, presentations, original


def run(local_only=False, include_papers=False):
    llm = None
    summaries = []
    sources = [SOURCE / 'DLRmagazine_176_EN' / f'page_{page:04d}' for page in (9, 12, 17)]
    if include_papers:
        sources += [base.ROOT / 'EvidenceNet/output/dolphin_paper_node_pipeline_v1/evidence_units/gw150914_detection_dolphin' / f'page_{page:04d}' for page in (2, 4)]
    if not local_only:
        llm = base.create_llm({'provider': 'transformers', 'model': base.read(SOURCE / 'manifest.json')['model'],
                              'dtype': 'bfloat16', 'device_map': 'auto', 'require_cuda': True, 'enable_thinking': False})
    for source in sources:
        target = OUT / source.parent.name / source.name
        is_paper = source.parent.name == 'gw150914_detection_dolphin'
        if is_paper:
            rep, source_flow, presentations, original = paper_inputs(source, target, llm, local_only)
        else:
            rep = base.read(source / 'input_representation.json')
            source_flow = base.read(source / 'flow.json')
            presentations = base.read(source / 'visual_presentations.json')
            original = source / 'original.png'
        with Image.open(original) as im:
            page_size = im.size
        flow, restored = restore_uncertain(source_flow)
        check = composite.validate_flow(flow, rep)
        if not check['valid']:
            raise ValueError(check)
        units = text_units(flow, rep)
        fragments = base.fragments(rep)
        images = {row['panel_id']: row['image'] for row in presentations}
        owners = {v: item['content_item_id'] for item in flow['content_items'] for v in item['visual_panel_ids']}
        decisions = []
        geometry_ledger = {}
        model_calls = 0
        for visual in rep['visual_bundles']:
            vid = visual['visual_bundle_id']
            owned = [u for u in units if u['content_item_id'] == owners[vid]]
            selected, ranked = candidates_for(visual, owned, rep, fragments, page_size)
            geometry_ledger[vid] = {'selected': selected, 'ranked': ranked, 'page_size': page_size,
                                    'policy': 'member geometry hints only; overlap is not ownership'}
            candidates = {r['unit_id']: r for r in selected}
            decision = {'visual_id': vid, 'decision': 'UNCERTAIN', 'caption_unit_id': None,
                        'basis': 'No model judgment in local coverage check' if local_only else 'No eligible text candidates'}
            if candidates and not local_only:
                prompt = ('Judge ONE visual against candidate text units. First image is the source page; second is the visual. '
                          'Candidates include page-normalized edge gap, alignment, intervening geometry members and original boxes. '
                          'Use these as layout hints: favor direct aligned captions without intervening content, check columns on the page. '
                          'Geometry is NOT proof: overlapping background pictures do not own overlaid prose. '
                          'Choose MATCH only for a direct caption or a paragraph explicitly explaining what this picture shows. '
                          'General article context, methods, results and topic similarity are insufficient. '
                          'A shared caption can describe different images in separate clauses. '
                          'Do not reinterpret transcription errors to force a match. Use NONE if none applies, UNCERTAIN for ambiguity. '
                          'Return exactly {"visual_id": "' + vid + '", "decision": "MATCH|NONE|UNCERTAIN", '
                          '"caption_unit_id": "candidate ID or null", "basis": "observable reason"}. '
                          'Do not copy or correct source text. Candidates: ' + json.dumps(candidates, ensure_ascii=False))
                for attempt in range(3):
                    model_calls += 1
                    raw = llm.generate_raw_with_images('Caption association reviewer. JSON only.', prompt,
                                                       [str(original), images[vid]], 800).raw
                    base.write(target / f'{vid}_attempt{attempt}.json', {'raw': raw})
                    try:
                        candidate = base.extract_json(raw)
                        validate_decision(candidate, vid, candidates)
                        decision = candidate
                        break
                    except (ValueError, TypeError, KeyError) as exc:
                        prompt += '\nFix schema: ' + str(exc)
                else:
                    decision['basis'] = 'Model output invalid after three attempts'
            decisions.append(decision)
        reviews = {}
        for cid in dict.fromkeys(d['caption_unit_id'] for d in decisions if d['decision'] == 'MATCH'):
            unit = next(u for u in units if u['evidence_unit_id'] == cid)
            text = '\n'.join(fragments[f]['text'] for f in unit['fragment_ids'])
            vids = [d['visual_id'] for d in decisions if d['decision'] == 'MATCH' and d['caption_unit_id'] == cid]
            opaque_ids, raw_ids = opaque_review_ids(vids)
            review = {'accepted': [], 'text_quality': 'UNVERIFIED', 'basis': 'Review failed; keep visual separate'}
            prompt = ('Audit proposed image-text ownership using the original page (first image), followed by '
                      'the proposed visuals in this exact order: ' + json.dumps([opaque_ids[v] for v in vids]) + '. '
                      'These labels are opaque identifiers only; do not infer anything from their spelling. '
                      'Reject merely topical links. Accept each visual only if this text directly describes it, '
                      'considering page placement and visible details. For a shared caption, each accepted image '
                      'must have a distinct image-specific source quote; whitespace differences are allowed, words are not. '
                      'A vehicle name alone is not a description of a second image. If one link is unsupported reject ONLY that link. '
                      'For body prose accept only explicit explanation of the pictured scene, not general methods or results. '
                      'Never repair or rationalize garbled text (for example substituting a different entity). '
                      'Mark text_quality SUSPECT for transcription anomalies or visual contradictions; otherwise UNVERIFIED. '
                      'Return JSON {"accepted":[{"visual_id":"VISUAL_01","anchor":"exact source substring",'
                      '"relation":"CAPTION or DIRECT_EXPLANATION"}],"text_quality":"UNVERIFIED or SUSPECT",'
                      '"basis":"observable justification, including rejections"}. Empty accepted is allowed. Geometry hints: ' +
                      json.dumps({v: next(r for r in geometry_ledger[v]['selected'] if r['unit_id'] == cid) for v in vids}, ensure_ascii=False) +
                      '\nSource text:\n' + text)
            for attempt in range(3):
                model_calls += 1
                raw = llm.generate_raw_with_images('Evidence association auditor. JSON only.', prompt,
                         [str(original)] + [images[v] for v in vids], 1400).raw
                base.write(target / f'{cid}_review_attempt{attempt}.json', {'raw': raw})
                try:
                    candidate = restore_review_ids(base.extract_json(raw), raw_ids)
                    validate_review(candidate, vids, text)
                    review = candidate
                    break
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    prompt += '\nFix schema: ' + str(exc)
            reviews[cid] = review
        assembly = assemble(units, flow, decisions, reviews)
        # Preserve plausible nearby links for audit, without merging questionable text.
        accepted_visuals = {v for u in assembly['evidence_units'] if u['unit_type'] == 'COMPOSITE' for v in u['visual_panel_ids']}
        pending = [{'visual_id': vid, 'text_unit_id': r['unit_id'], 'geometry': r['geometry'],
                    'status': 'GEOMETRY_ONLY_UNVERIFIED', 'text_quality': 'UNVERIFIED'}
                   for vid, ledger in geometry_ledger.items() if vid not in accepted_visuals
                   for r in ledger['selected'] if r['caption_candidate'] and r['geometry']['score'] <= 0.12]
        for unit in assembly['evidence_units']:
            links = [r for r in pending if r['visual_id'] in unit['visual_panel_ids'] or r['text_unit_id'] == unit['evidence_unit_id']]
            if links:
                unit['pending_associations'] = links
        validation = composite.validate_evidence(assembly, flow, rep)
        nodes, contexts = base.materialize(rep, flow, assembly, validation['valid'])
        for node in nodes:
            node['status'] = 'STRUCTURALLY_VALID_UNREVIEWED' if validation['valid'] else 'UNVALIDATED_CANDIDATE'
            unit = next(u for u in assembly['evidence_units'] if node['node_id'].endswith('_' + u['evidence_unit_id']))
            for key in ('text_quality', 'visual_text_links', 'association_basis', 'pending_associations'):
                if key in unit:
                    node[key] = unit[key]
            node['retrieval_eligible'] = False
            if unit['completeness'] == 'UNRESOLVED':
                node['status'] = 'NEEDS_REVIEW'
        base.write(target / 'input_representation.json', rep)
        base.write(target / 'flow.json', flow)
        base.write(target / 'assembly.json', assembly)
        base.write(target / 'decisions.json', decisions)
        base.write(target / 'association_reviews.json', reviews)
        base.write(target / 'geometry_candidates.json', geometry_ledger)
        base.write(target / 'pending_associations.json', pending)
        base.write(target / 'visual_presentations.json', presentations)
        base.write(target / 'validation.json', validation)
        base.write_jsonl(target / 'evidence_nodes.jsonl', nodes)
        summary = {'document_id': rep['document_id'], 'page': source.name, 'structural_valid': validation['valid'], 'restored_uncertain': restored,
                   'nodes': len(nodes), 'composites': sum(n['unit_type'] == 'COMPOSITE' for n in nodes),
                   'needs_review': sum(n['status'] == 'NEEDS_REVIEW' for n in nodes),
                   'model_calls': model_calls,
                   'source_root': str(source), 'local_only': local_only, 'semantic_review': 'pending',
                   'model': None if local_only else base.read(SOURCE / 'manifest.json')['model'],
                   'parser_view_route': 'Dolphin paper + complete figure crops' if is_paper else 'frozen Dolphin source spreads plus native PDF assets and recovered text',
                   'reading_flows': ('local coverage stub' if local_only else 'new Qwen reading flow') if is_paper else 'frozen v3; uncertain structural roles restored',
                   'geometry_pending_links': len(pending),
                   'shared_caption_proposals': [cid for cid, count in Counter(
                       d['caption_unit_id'] for d in decisions if d['decision'] == 'MATCH').items() if count > 1],
                   'production_modified': False}
        base.write(target / 'run_summary.json', summary)
        summaries.append(summary)
        import subprocess
        import sys
        subprocess.run([sys.executable, str(base.ROOT / 'EvidenceNet/scripts/build_evidence_gallery.py'),
                        '--page-dir', str(target), '--output', str(target / 'evidence_gallery.html')], check=True)
    base.write(OUT / 'summary.json', summaries)
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-check', action='store_true')
    parser.add_argument('--output-root', type=Path, default=OUT)
    parser.add_argument('--include-papers', action='store_true')
    args = parser.parse_args()
    OUT = args.output_root
    if args.local_check:
        OUT = OUT.with_name(OUT.name + '_local_check')
    run(args.local_check, args.include_papers)
