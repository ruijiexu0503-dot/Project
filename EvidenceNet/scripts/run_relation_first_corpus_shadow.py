#!/usr/bin/env python3
"""Cross-data shadow: stable components and reading flows before evidence relations."""
from __future__ import annotations

import argparse
import base64
import copy
import html
import hashlib
import json
import shutil
import time
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import run_flow_first_evidence_pilot as base
import run_composite_evidence_pilot as composite
from run_bounded_composite_pilot import text_units as grouped_text_units
from bounded_geometry import candidates_for, source_anchor
import flow_recovery
import source_grounding


ROOT = base.ROOT
OUT = ROOT / 'EvidenceNet/output/relation_first_corpus_shadow_v1'


class InferenceBudgetExhausted(RuntimeError):
    pass


class BudgetedLLM:
    def __init__(self, model, deadline, output):
        self.model, self.deadline, self.output = model, deadline, output
        self.calls = 0

    def generate_raw_with_images(self, *args, **kwargs):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            write(self.output / 'budget_stop.json', {'status': 'budget_exhausted', 'resume_required': True})
            raise InferenceBudgetExhausted('Inference budget reached; completed flow and visual decisions are checkpointed.')
        self.calls += 1
        event = {'status': 'running', 'call_index': self.calls, 'started_at_unix': time.time(),
                 'stage': args[0] if args else kwargs.get('system'),
                 'max_new_tokens': args[3] if len(args) > 3 else kwargs.get('max_new_tokens')}
        write(self.output / 'inference_status.json', event)
        started = time.monotonic()
        try:
            result = self.model.generate_raw_with_images(*args, **kwargs)
        except Exception as exc:
            event.update(status='failed', elapsed_seconds=round(time.monotonic()-started, 3), error=repr(exc))
            write(self.output / 'inference_status.json', event)
            raise
        event.update(status='complete', elapsed_seconds=round(time.monotonic()-started, 3), output_characters=len(result.raw))
        write(self.output / 'inference_status.json', event)
        print(json.dumps(event), flush=True)
        return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def one_fragment(atom_id, text):
    return [{'fragment_id': f'{atom_id}::F001', 'source_atom_id': atom_id,
             'char_start': 0, 'char_end': len(text), 'text': text, 'oversized_unsplit': False}]


def atom_type(label):
    label = str(label or '').lower()
    if label == 'cap': return 'caption'
    if label in {'fig', 'image', 'chart'}: return 'image'
    if label in {'tab', 'table'}: return 'table'
    if label in {'formula', 'equation'}: return 'formula'
    if label.startswith('sec'): return 'heading'
    if label in {'header', 'foot'}: return 'furniture'
    return 'text'


def work_json(work):
    rows = sorted((work / 'output_json').glob('*.json'))
    if len(rows) != 1:
        raise FileNotFoundError(f'expected one Dolphin JSON in {work}, found {len(rows)}')
    return rows[0]


def crop(image, box, source_size, output):
    with Image.open(image) as source:
        sx, sy = source.width / source_size[0], source.height / source_size[1]
        x1, y1, x2, y2 = [int(round(v * scale)) for v, scale in zip(box, (sx, sy, sx, sy))]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(source.width, x2), min(source.height, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        output.parent.mkdir(parents=True, exist_ok=True)
        source.crop((x1, y1, x2, y2)).save(output)
    return str(output)


def dolphin_representation(row, output, fresh_root):
    native = ROOT / 'EvidenceNet/output/bounded_composite_v4_geometry' / row['document_id'] / row['page']
    if row['document_id'] == 'DLRmagazine_176_EN' and (native / 'visual_presentations.json').exists():
        rep = base.read(native / 'input_representation.json')
        images = {r['panel_id']: r['image'] for r in base.read(native / 'visual_presentations.json')}
        for visual in rep['visual_bundles']:
            visual['presentation'] = images[visual['visual_bundle_id']]
        source = ROOT / 'EvidenceNet/output/composite_evidence_pilot_v3_recomposed_components' / row['document_id'] / row['page'] / 'original.png'
        return rep['atoms'], rep['visual_bundles'], source
    mode = row['mode']
    if mode == 'fresh':
        case_id = row.get('case_id', f"relation_{row['document_id']}")
        work = fresh_root / 'parsed' / case_id
        source = fresh_root / 'images' / f'{case_id}.png'
    elif mode == 'fresh_image':
        case_id = row.get('case_id', f"relation_{row['document_id']}")
        work = fresh_root / 'parsed' / case_id
        source = ROOT / row['image']
    else:
        work = ROOT / row['work']
        if mode == 'case': source = ROOT / row['image']
        else: source = output / 'source.png'
    if not source.exists():
        raise FileNotFoundError(source)
    elements = json.loads(work_json(work).read_text(encoding='utf-8'))
    write(output / 'source_elements.json', elements)
    summary = json.loads((work / 'run_summary.json').read_text(encoding='utf-8'))
    with Image.open(source) as im:
        sx, sy = im.width / summary['image_size'][0], im.height / summary['image_size'][1]
    atoms, visuals = [], []
    for index, element in enumerate(elements, 1):
        label, text, box = str(element.get('label') or ''), str(element.get('text') or ''), element.get('bbox')
        page_box = [v*s for v, s in zip(box, (sx, sy, sx, sy))] if box else None
        identifier = f"A_{index:03d}"
        typ = atom_type(label)
        if typ == 'image' and box:
            visual_id = f'V_{len(visuals)+1:03d}'
            figure = crop(source, box, summary['image_size'], output / 'visuals' / f'{visual_id}.png')
            if figure is None:
                raise ValueError(f'Invalid visual crop: {identifier}, {box}')
            visuals.append({'visual_bundle_id': visual_id, 'bbox': page_box, 'layout_label': label,
                            'provenance_state': 'dolphin_complete_figure_crop',
                            'geometry_members': [{'member_id': f'{visual_id}::M001', 'bbox': page_box,
                                                  'bbox_source': 'dolphin_v2_element_bbox'}],
                            'presentation': figure})
            continue
        if not text.strip(): continue
        atoms.append({'atom_id': identifier, 'atom_type': typ, 'layout_role': label,
                      'text_preview': text[:500], 'text_length': len(text),
                      'text_fragments': one_fragment(identifier, text),
                      'geometry_members': ([{'member_id': f'{identifier}::G001', 'bbox': page_box}]
                                           if isinstance(box, list) and len(box) == 4 else [])})
    return atoms, visuals, source


def pptx_representation(row, output, audit_root):
    native = [json.loads(line) for line in (audit_root / 'native_objects.jsonl').read_text().splitlines() if line.strip()]
    slide = [item for item in native if item['slide'] == row['slide_number']]
    preview = output / 'source.png'; preview.parent.mkdir(parents=True, exist_ok=True)
    metadata = base.read(audit_root / 'summary.json')
    sw, sh = metadata['slide_size_emu']
    width, height = 1600, round(1600 * sh / sw)
    canvas = Image.new('RGB', (width, height), 'white'); draw = ImageDraw.Draw(canvas)
    font_path = next(iter(Path('/usr/share/fonts').rglob('DroidSans.ttf')), None)
    font = ImageFont.truetype(str(font_path), 22) if font_path else ImageFont.load_default()
    atoms, visuals = [], []
    for item in slide:
        x1, y1, x2, y2 = [int(v * size) for v, size in zip(item['bbox_normalized'], (width, height, width, height))]
        if item['kind'] == 'text' and item['text'].strip():
            aid = f"A_{len(atoms)+1:03d}"; draw.rectangle((x1,y1,x2,y2), outline=(35,140,70), width=2)
            draw.text((x1 + 4, y1 + 4), item['text'], fill='black', font=font)
            atoms.append({'atom_id': aid, 'atom_type': 'text', 'layout_role': 'pptx_text',
                          'text_preview': item['text'][:500], 'text_length': len(item['text']),
                          'text_fragments': one_fragment(aid, item['text']),
                          'geometry_members': [{'member_id': f'{aid}::G001', 'bbox': [x1,y1,x2,y2]}]})
        elif item['kind'] == 'picture' and item.get('asset_path'):
            vid = f'V_{len(visuals)+1:03d}'; source = audit_root / item['asset_path']; target = output / 'visuals' / f'{vid}{source.suffix}'
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
            with Image.open(source) as im:
                im = im.convert('RGBA')
                cuts = item.get('crop', {})
                visible = im.crop((round(im.width*cuts.get('left', 0)), round(im.height*cuts.get('top', 0)),
                                   round(im.width*(1-cuts.get('right', 0))), round(im.height*(1-cuts.get('bottom', 0)))))
                visible = visible.resize((max(1, x2-x1), max(1, y2-y1)))
                canvas.paste(visible, (x1, y1), visible)
            draw.rectangle((x1,y1,x2,y2), outline=(40,90,220), width=3)
            visuals.append({'visual_bundle_id': vid, 'bbox': [x1,y1,x2,y2], 'layout_label': 'pptx_picture',
                            'provenance_state': 'native_pptx_picture_shape', 'presentation': str(target),
                            'geometry_members': [{'member_id': f'{vid}::M001', 'bbox': [x1,y1,x2,y2],
                                                  'bbox_source': 'pptx_native_shape'}]})
    canvas.save(preview)
    write(output / 'pptx_source_ledger.json', {'objects': slide, 'preview': 'approximate_native_object_layout',
          'unsupported_objects': [r for r in slide if r['kind'] not in {'text', 'picture'}],
          'not_a_faithful_render': True})
    return atoms, visuals, preview


def local_flow(rep):
    streams = []
    structural = []
    for atom in rep['atoms']:
        ids = [f['fragment_id'] for f in atom['text_fragments']]
        if atom['atom_type'] in {'heading', 'furniture'}:
            structural.extend({'fragment_id': fid, 'role': 'page_furniture' if atom['atom_type'] == 'furniture' else 'section_heading'} for fid in ids)
        else:
            streams.append({'flow_id': f"CI_1_{atom['atom_id']}", 'flow_kind': 'caption' if atom['atom_type'] == 'caption' else 'main',
                            'fragment_ids': ids, 'continuations': []})
    return {'content_items': [{'content_item_id': 'CI_1', 'kind': 'document_content', 'flows': streams,
             'structural_fragments': structural, 'visual_panel_ids': [v['visual_bundle_id'] for v in rep['visual_bundles']]}]}


def reading_flow_prompt(rep):
    # Internal geometry/member IDs are provenance, not output choices for the model.
    atoms = [{'parser_role': a.get('atom_type'),
              'boxes': [m['bbox'] for m in a.get('geometry_members', []) if m.get('bbox')],
              'fragments': [{'fragment_id': f['fragment_id'], 'text': f['text']}
                            for f in a['text_fragments']]} for a in rep['atoms']]
    visuals = [{'visual_panel_id': v['visual_bundle_id'], 'bbox': v.get('bbox'),
                'boxes': [m['bbox'] for m in v.get('geometry_members', []) if m.get('bbox')]}
               for v in rep['visual_bundles']]
    return '''Infer content ownership and reading order from this page and its source components.
Return JSON with content_items (a list). Each item has a unique content_item_id,
kind, flows, structural_fragments, and visual_panel_ids.
Each flow has a unique flow_id, flow_kind (main/sidebar/caption), fragment_ids in
reading order, and continuations (a list). Each continuation has from_fragment_id,
to_fragment_id (the immediately next fragment), and kind (same_sentence or same_paragraph).
Each structural entry has fragment_id and role (title/section_heading/dek/byline/page_furniture/logo).
Every supplied fragment and visual must occur exactly once. Only use supplied IDs.
Use empty lists when no members exist. Captions belong in caption flows, not furniture.
Preserve separate articles and sidebar flows. Same-sentence continuations must be explicit.
Parser roles are hints, not truth. Never discard uncertain text or visual components.
The ONLY top-level key is content_items. Page furniture belongs in an item's
structural_fragments, NEVER in a top-level page_furniture field. If page-wide
furniture has no article owner, give it a separate page_context content item.
A heading must appear EITHER in structural_fragments OR in a reading flow, never both.
Copy visual_panel_id exactly into visual_panel_ids. Every fragment_id must occur
once as an assignment; continuation endpoints merely reference those assignments.
Use this nesting (empty lists here show structure, not permission to omit sources):
{"content_items":[{"content_item_id":"CI_1","kind":"article","flows":[
{"flow_id":"FLOW_1","flow_kind":"main","fragment_ids":[],"continuations":[]}],
"structural_fragments":[],"visual_panel_ids":[]}]}
Before responding, compare your assignments with the complete source inventory.
SOURCE: ''' + json.dumps({'atoms': atoms, 'visuals': visuals}, ensure_ascii=False)


def repair_flow_patch(flow, rep, source, llm, target):
    audit={'policy':flow_recovery.PATCH_POLICY_VERSION,'status':'failed','needs_review':True,
           'semantic_validated':False,'additional_model_calls':0}
    try:
        fixed,plan=flow_recovery.prepare_patch(flow,rep)
        audit.update(plan)
        check=validate_flow(fixed,rep)
        if not check['valid']:
            if not plan['missing'] and not plan['duplicate_options']:
                raise ValueError('no supported assignment patch for remaining errors')
            prompt=flow_recovery.patch_prompt(fixed,rep,plan)
            write(target/'flow_repair_input.json',{'prompt':prompt,'plan':plan})
            audit['additional_model_calls']=1
            raw=llm.generate_raw_with_images('Document assignment patch. JSON only.',prompt,[str(source)],2200).raw
            write(target/'flow_repair_raw.json',{'raw':raw})
            fixed,details=flow_recovery.apply_patch_choices(fixed,plan,base.extract_json(raw))
            audit.update(details)
            check=validate_flow(fixed,rep)
        audit['validation']=check
        write(target/'flow_repair_candidate.json',fixed)
        if check['valid']:
            audit['status']='repaired'
            write(target/'flow_recovery.json',audit)
            return fixed
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        audit['error']=str(exc)
    write(target/'flow_recovery.json',audit)
    raise ValueError('bounded assignment patch remains invalid or unresolved')


def make_flow(rep, source, llm, target, local_only, max_attempts=1, recovery_policy='none'):
    if local_only: return local_flow(rep)
    recovery = recovery_policy in flow_recovery.POLICIES
    if recovery:
        write(target / 'flow_recovery.json', {'policy': recovery_policy, 'needs_review': False, 'status': 'not_needed'})
    if recovery and not base.fragments(rep):
        flow = {'content_items': [{'content_item_id': 'PAGE_CONTEXT', 'kind': 'page_context',
                'flows': [], 'structural_fragments': [],
                'visual_panel_ids': [v['visual_bundle_id'] for v in rep['visual_bundles']]}]}
        write(target / 'flow_recovery.json', {'policy': recovery_policy, 'needs_review': True,
              'status': 'visual_only', 'text_recovery_required': True, 'semantic_validated': False})
        return flow
    original_prompt = reading_flow_prompt(rep)
    prompt = original_prompt
    last_flow = None
    for attempt in range(max_attempts):
        raw = llm.generate_raw_with_images('Document reading-flow analyst. JSON only.', prompt, [str(source)], 6000).raw
        write(target / f'flow_attempt_{attempt}.json', {'raw': raw})
        check = None
        try:
            flow = base.extract_json(raw); check = validate_flow(flow, rep)
            last_flow = flow
            write(target / f'flow_validation_{attempt}.json', check)
            if check['valid']: return flow
            raise ValueError(check['errors'])
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            write(target / f'flow_validation_{attempt}.json', check or {'valid': False, 'errors': str(exc)})
            prompt = (original_prompt + '\nYour previous response failed validation. Repair that response, '
                      'retain valid assignments, and return the complete corrected JSON. Do not repeat the errors.\n'
                      'PREVIOUS_RESPONSE:\n' + raw + '\nVALIDATION_ERRORS:\n' + str(exc))
    if recovery_policy == flow_recovery.PATCH_POLICY_VERSION and last_flow is not None:
        return repair_flow_patch(last_flow,rep,source,llm,target)
    if recovery and last_flow is not None:
        # One bounded additional call. Missing/unknown source IDs still fail the
        # original validator; no automatic reassignment to page furniture.
        audit = {'policy': recovery_policy, 'needs_review': True, 'semantic_validated': False,
                 'status': 'failed'}
        try:
            options = flow_recovery.duplicate_options(last_flow, rep)
            if not options:
                raise ValueError('no eligible duplicate assignments to repair')
            prompt = flow_recovery.repair_prompt(last_flow, rep, options)
            write(target / 'flow_repair_input.json', {'prompt': prompt, 'options': options})
            raw = llm.generate_raw_with_images('Document assignment repair. JSON only.', prompt, [str(source)], 1200).raw
            write(target / 'flow_repair_raw.json', {'raw': raw})
            corrected, details = flow_recovery.apply_choices(last_flow, options, base.extract_json(raw))
            check = validate_flow(corrected, rep)
            audit.update(details, validation=check)
            write(target / 'flow_repair_candidate.json', corrected)
            if check['valid']:
                audit['status'] = 'repaired'
                write(target / 'flow_recovery.json', audit)
                return corrected
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            audit['error'] = str(exc)
        write(target / 'flow_recovery.json', audit)
    if recovery and last_flow is None:
        write(target / 'flow_recovery.json', {'policy': recovery_policy, 'needs_review': True,
              'semantic_validated': False, 'status': 'failed',
              'error': 'no parsed flow available for bounded repair'})
    raise ValueError(f'reading flow invalid after {max_attempts} attempt(s)')


def text_units(flow, rep):
    fragments = base.fragments(rep); result = grouped_text_units(flow, rep)
    for index, unit in enumerate(result, 1):
        unit.update(text_unit_id=f'T_{index:03d}', evidence_unit_id=f'T_{index:03d}',
                    text='\n'.join(fragments[f]['text'] for f in unit['fragment_ids']))
    return result


def structural_review_units(flow, rep):
    fragments = base.fragments(rep)
    return [{'text_unit_id': 'S_' + entry['fragment_id'],
             'evidence_unit_id': 'S_' + entry['fragment_id'],
             'fragment_ids': [entry['fragment_id']], 'flow_id': None,
             'content_item_id': item['content_item_id'], 'caption_candidate': False,
             'structural_role': entry['role'], 'text': fragments[entry['fragment_id']]['text']}
            for item in flow['content_items'] for entry in item['structural_fragments']
            if entry['role'] == 'page_furniture'
            and len(fragments[entry['fragment_id']]['text'].strip()) >= 40]


def relation_candidates(visual, units, owner, rep, fragments, size):
    _, ranked = candidates_for(visual, units, rep, fragments, size)
    by_id = {u['text_unit_id']: u for u in units}
    for row in ranked:
        unit = by_id[row['unit_id']]
        row.update(content_item_id=unit['content_item_id'],
                   candidate_scope='same_item' if unit['content_item_id'] == owner else 'cross_item',
                   structural_role=unit.get('structural_role'),
                   caption_policy=('layout_review_required' if unit.get('structural_role') else
                                   'allowed' if unit['caption_candidate'] else 'body_only'))
        geometry = row['geometry']
        row['nearby'] = (not geometry.get('unavailable') and geometry['gap'] <= 0.15
                         and geometry['score'] <= 0.35)
    # Ownership is a prior, not a gate. Reserve bounded space for adjacent
    # cross-item text and possible captions misclassified as page furniture.
    eligible = [r for r in ranked if r['nearby'] or
                (r['candidate_scope'] == 'same_item' and not r['structural_role'])]
    selected = []
    pools = [([r for r in eligible if r['structural_role']], 2),
             ([r for r in eligible if r['caption_candidate']], 3),
             ([r for r in eligible if r['candidate_scope'] == 'cross_item' and not r['structural_role']], 2),
             ([r for r in eligible if r['candidate_scope'] == 'same_item' and not r['structural_role']], 2)]
    for pool, count in pools:
        selected.extend([r for r in pool if r not in selected][:count])
    selected.extend([r for r in eligible if r not in selected][:max(0, 9-len(selected))])
    return selected, ranked


def validate_flow(flow, rep):
    errors = []
    if not isinstance(flow, dict) or set(flow) != {'content_items'} or not isinstance(flow.get('content_items'), list):
        return {'valid': False, 'errors': [{'type': 'invalid_root_schema', 'required_keys': ['content_items']}]}
    item_keys = {'content_item_id', 'kind', 'flows', 'structural_fragments', 'visual_panel_ids'}
    for item in flow['content_items']:
        if not isinstance(item, dict) or set(item) != item_keys:
            errors.append({'type': 'invalid_item_schema', 'required_keys': sorted(item_keys)})
            continue
        if any(not isinstance(item[k], list) for k in ('flows', 'structural_fragments', 'visual_panel_ids')):
            errors.append({'type': 'invalid_item_lists'})
            continue
        if not isinstance(item['kind'], str):
            errors.append({'type': 'invalid_content_kind'})
        if any(not isinstance(v, str) for v in item['visual_panel_ids']):
            errors.append({'type': 'invalid_visual_ids'})
        for entry in item['structural_fragments']:
            if (not isinstance(entry, dict) or set(entry) != {'fragment_id', 'role'}
                    or not isinstance(entry.get('fragment_id'), str) or not isinstance(entry.get('role'), str)):
                errors.append({'type': 'invalid_structural_entry'})
        for stream in item['flows']:
            if (not isinstance(stream, dict) or set(stream) != {'flow_id', 'flow_kind', 'fragment_ids', 'continuations'}
                    or not isinstance(stream.get('flow_id'), str) or not isinstance(stream.get('flow_kind'), str)
                    or not isinstance(stream.get('fragment_ids'), list) or not isinstance(stream.get('continuations'), list)):
                errors.append({'type': 'invalid_stream_schema'})
                continue
            if any(not isinstance(fid, str) for fid in stream['fragment_ids']):
                errors.append({'type': 'invalid_fragment_ids'})
            for edge in stream['continuations']:
                if not isinstance(edge, dict) or set(edge) != {'from_fragment_id', 'to_fragment_id', 'kind'} or any(not isinstance(v, str) for v in edge.values()):
                    errors.append({'type': 'invalid_continuation_schema'})
    if errors:
        return {'valid': False, 'errors': errors}
    result = composite.validate_flow(flow, rep)
    ids = [i.get('content_item_id') for i in flow['content_items']]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        result['errors'].append({'type': 'invalid_content_item_ids'})
    for item in flow['content_items']:
        for entry in item['structural_fragments']:
            if entry.get('role') not in {'title', 'section_heading', 'dek', 'byline', 'page_furniture', 'logo'}:
                result['errors'].append({'type': 'invalid_structural_role', 'entry': entry})
        for stream in item['flows']:
            for edge in stream.get('continuations', []):
                if edge.get('kind') not in {'same_sentence', 'same_paragraph'}:
                    result['errors'].append({'type': 'invalid_continuation_kind'})
    result['valid'] = not result['errors']
    return result


def validate_edges(result, visual_label, candidates):
    if not isinstance(result, dict) or result.get('visual_label') != visual_label or not isinstance(result.get('edges'), list):
        raise ValueError('invalid visual label or edges')
    if any(not isinstance(e, dict) for e in result['edges']):
        raise ValueError('each edge must be an object')
    ids = set(candidates); grouped = {}
    captions = [e.get('text_unit_id') for e in result['edges'] if e.get('relation') == 'CAPTION_FOR']
    if any(not isinstance(uid, str) for uid in captions):
        raise ValueError('text_unit_id must be a string')
    if len(set(captions)) > 1:
        raise ValueError('at most one direct caption per visual')
    for edge in result['edges']:
        unit = edge.get('text_unit_id')
        if not isinstance(unit, str) or unit not in ids: raise ValueError('unknown text unit')
        if edge.get('relation') not in {'CAPTION_FOR', 'ILLUSTRATES'}: raise ValueError('invalid relation')
        if edge['relation'] == 'CAPTION_FOR':
            policy = candidates[unit].get('caption_policy')
            if candidates[unit].get('caption_layout_required'):
                if edge.get('caption_attachment') not in {'standalone_target', 'explicit_shared_panel'}:
                    raise ValueError('caption requires target-specific or explicit shared-panel attachment')
                if not isinstance(edge.get('caption_layout_basis'), str) or len(edge['caption_layout_basis'].strip()) < 20:
                    raise ValueError('caption requires explicit target-specific caption_layout_basis')
            if policy == 'body_only':
                raise ValueError('body text cannot be CAPTION_FOR; use ILLUSTRATES only with direct visible support')
            if policy == 'layout_review_required' and (
                    not isinstance(edge.get('caption_layout_basis'), str)
                    or len(edge['caption_layout_basis'].strip()) < 20):
                raise ValueError('structural caption requires explicit caption_layout_basis')
        if not isinstance(edge.get('basis'), str) or not edge['basis'].strip():
            raise ValueError('each edge requires a grounded association basis')
        if edge.get('text_quality') not in {'UNVERIFIED', 'SUSPECT'}:
            raise ValueError('text_quality must be UNVERIFIED or SUSPECT')
        indexed = 'evidence_spans' in candidates[unit]
        if indexed and any(k in edge for k in ('anchor', 'supporting_anchors', 'source_char_start', 'source_char_end')):
            raise ValueError('span protocol accepts source IDs only, not generated quotes or offsets')
        extra = edge.get('supporting_span_ids' if indexed else 'supporting_anchors', [])
        if not isinstance(extra, list):
            raise ValueError('supporting_anchors must be a list')
        text = candidates[unit]['text']
        supports = []
        for quote in [edge.get('anchor_span_id' if indexed else 'anchor')] + extra:
            if indexed:
                resolved = source_grounding.resolve_span(candidates[unit], quote)
            elif 0 < len(text.strip()) < 12 and quote == text.strip():
                start = text.index(text.strip())
                resolved = {'anchor': text.strip(), 'source_char_start': start, 'source_char_end': start + len(text.strip())}
            else:
                resolved = source_anchor(text, quote)
            supports.append({**resolved, 'reported_relation': edge['relation'], 'basis': edge['basis'],
                             'caption_layout_basis': edge.get('caption_layout_basis'),
                             'caption_attachment': edge.get('caption_attachment'),
                             'text_quality': edge['text_quality']})
        if candidates[unit].get('anchor_protocol') == 'span-id-v2':
            source_grounding.validate_primary_semantics(supports[0]['anchor'])
        grouped.setdefault(unit, []).extend(supports)
    merged = []
    for unit, supports in grouped.items():
        supports = list({(s['source_char_start'], s['source_char_end'], s['reported_relation']): s for s in supports}.values())
        # A caption can describe several subpanels. Preserve those claims as
        # support for one caption relation, without creating duplicate nodes.
        primary = next((s for s in supports if s['reported_relation'] == 'CAPTION_FOR'), supports[0])
        merged.append({'text_unit_id': unit, 'relation': primary['reported_relation'],
                       **{k: primary[k] for k in ('anchor', 'source_char_start', 'source_char_end', 'basis')},
                       **({'anchor_span_id': primary['span_id']} if 'span_id' in primary else {}),
                       'text_quality': 'SUSPECT' if any(s['text_quality'] == 'SUSPECT' for s in supports) else 'UNVERIFIED',
                       'supporting_spans': supports})
    result['edges'] = merged


def validate_edges_individually(result, visual_label, candidates, allow_partial_support=False):
    if not isinstance(result, dict) or result.get('visual_label') != visual_label or not isinstance(result.get('edges'), list):
        raise ValueError('invalid visual label or edges')
    accepted = []; rejected = []
    for index, edge in enumerate(result['edges']):
        try:
            candidate = copy.deepcopy(edge)
            support_errors = []
            if allow_partial_support and isinstance(candidate, dict):
                indexed = 'evidence_spans' in candidates.get(candidate.get('text_unit_id'), {})
                support_field = 'supporting_span_ids' if indexed else 'supporting_anchors'
                extra = candidate.get(support_field, [])
                if not isinstance(extra, list):
                    raise ValueError('supporting_anchors must be a list')
                candidate[support_field] = []
                # All primary relation, caption, and source checks remain mandatory.
                validate_edges({'visual_label': visual_label, 'edges': [copy.deepcopy(candidate)]}, visual_label, candidates)
                for support_index, quote in enumerate(extra):
                    trial = {**candidate, support_field: [quote]}
                    try:
                        validate_edges({'visual_label': visual_label, 'edges': [trial]}, visual_label, candidates)
                        candidate[support_field].append(quote)
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        support_errors.append({'edge_index': index, 'support_index': support_index,
                            'rejection_kind': 'supporting_anchor', 'edge_retained': True,
                            'span_id' if indexed else 'anchor': quote, 'error': str(exc)})
            single = {'visual_label': visual_label, 'edges': [copy.deepcopy(candidate)]}
            validate_edges(single, visual_label, candidates)
            accepted.append((index, candidate))
            rejected.extend(support_errors)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            rejected.append({'edge_index': index, 'edge': edge, 'error': str(exc)})
    captions = {e['text_unit_id'] for _, e in accepted if e['relation'] == 'CAPTION_FOR'}
    if len(captions) > 1:
        # Do not choose an arbitrary winner among conflicting direct captions.
        rejected.extend({'edge_index': i, 'edge': e, 'error': 'conflicting direct captions'}
                        for i, e in accepted if e['relation'] == 'CAPTION_FOR')
        accepted = [(i, e) for i, e in accepted if e['relation'] != 'CAPTION_FOR']
    retained_indices = {i for i, _ in accepted}
    for row in rejected:
        if row.get('edge_retained') and row['edge_index'] not in retained_indices:
            row['edge_retained'] = False
    normalized = {'visual_label': visual_label, 'edges': [copy.deepcopy(e) for _, e in accepted]}
    validate_edges(normalized, visual_label, candidates)
    return normalized, rejected


def reusable_flow(root, rep, source, config):
    if root is None:
        return None
    prior = root / rep['document_id'] / rep['page']
    if not (prior / 'flow_checkpoint.json').exists() or not (prior / 'input_representation.json').exists():
        return None
    old_rep = base.read(prior / 'input_representation.json')
    if old_rep.get('inference_config') != config or reading_flow_prompt(old_rep) != reading_flow_prompt(rep):
        return None
    old_source = Path(old_rep['source_image'])
    if hashlib.sha256(old_source.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
        return None
    checkpoint = base.read(prior / 'flow_checkpoint.json')
    if checkpoint.get('recovery', {}).get('needs_review'):
        return None  # Do not reuse repaired ownership without its audit context.
    flow = checkpoint['flow']
    return flow if validate_flow(flow, rep)['valid'] else None


def validate_components(rep, nodes):
    actual = Counter(f for n in nodes for f in n['fragment_ids'])
    visuals = Counter(v for n in nodes for v in n['visual_ids'])
    if actual != Counter(list(base.fragments(rep))):
        raise ValueError('component fragment coverage mismatch')
    if visuals != Counter(v['visual_bundle_id'] for v in rep['visual_bundles']):
        raise ValueError('component visual coverage mismatch')
    if len({n['node_id'] for n in nodes}) != len(nodes):
        raise ValueError('duplicate component IDs')


def anchor_fragments(unit, edge, fragments):
    offset = 0; spans = []
    for fid in unit['fragment_ids']:
        fragment = fragments[fid]
        start = max(0, edge['source_char_start'] - offset)
        end = min(len(fragment['text']), edge['source_char_end'] - offset)
        if end > start:
            spans.append({'fragment_id': fid, 'fragment_char_start': start, 'fragment_char_end': end,
                          'source_atom_id': fragment['atom']['atom_id'],
                          'source_atom_char_start': fragment['char_start'] + start,
                          'source_atom_char_end': fragment['char_start'] + end})
        offset += len(fragment['text']) + 1
    if not spans:
        raise ValueError('anchor has no source fragment')
    return spans


def build_gallery(target, rep, nodes, edges, presentations):
    fragments = base.fragments(rep); images = {p['panel_id']: p['image'] for p in presentations}
    cards = []
    colors = ['#147d72', '#b83c50', '#5268ad', '#986f12', '#8d4fa0', '#357d36']
    for index, node in enumerate(nodes):
        content = ''.join(f"<p><code>{html.escape(fid)}</code> {html.escape(fragments[fid]['text'])}</p>" for fid in node['fragment_ids'])
        for v in node['visual_ids']:
            path = Path(images[v])
            mime = 'image/jpeg' if path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'
            encoded = base64.b64encode(path.read_bytes()).decode('ascii')
            content += f"<img src='data:{mime};base64,{encoded}'><p><code>{html.escape(v)}</code></p>"
        linked = [edge for edge in edges if edge['source_node_id'] == node['node_id'] or edge['target_node_id'] == node['node_id']]
        links = ''.join(f"<li>{html.escape(edge['relation_type'])}: " +
                        '<br>'.join(f"<code>{html.escape(s['anchor'])}</code>" for s in edge.get('supporting_spans', [edge])) +
                        '</li>' for edge in linked)
        cards.append(f"<section style='border-color:{colors[index % len(colors)]}'><h2>{html.escape(node['node_id'])}</h2><p>{html.escape(node.get('node_type', 'linked_evidence_view'))}</p>{content}<ul>{links}</ul></section>")
    (target / 'evidence_gallery.html').write_text("<!doctype html><meta charset='utf-8'><style>body{font:15px system-ui;margin:24px;background:#eef2f5}section{background:white;padding:16px;margin:14px 0;border-left:5px solid #147d72}img{max-width:600px;max-height:480px;display:block}code{overflow-wrap:anywhere}</style><h1>Relation-first Evidence Components</h1><p>Components remain independent. Edges carry the exact supporting span and its reading context.</p>" + ''.join(cards), encoding='utf-8')


def inference_config(args):
    cpu = getattr(args, 'device', 'cuda') == 'cpu'
    return {'provider': 'transformers', 'model': args.model,
            'dtype': getattr(args, 'dtype', None) or ('float32' if cpu else 'bfloat16'),
            'device_map': 'cpu' if cpu else 'auto', 'require_cuda': not cpu,
            'enable_thinking': False}


def run(args):
    started = time.monotonic()
    for key in ('sources', 'output', 'fresh_root', 'staged_sources', 'pptx_audit'):
        setattr(args, key, getattr(args, key).resolve())
    sources = json.loads(args.sources.read_text(encoding='utf-8'))['sources']
    keys = set(getattr(args, 'page_key', None) or [])
    if keys:
        available = {r['document_id'] + '/' + r['page'] for r in sources}
        if keys - available:
            raise ValueError(f'Unknown requested pages: {sorted(keys - available)}')
        sources = [r for r in sources if r['document_id'] + '/' + r['page'] in keys]
    sources = sources[args.shard_index::args.shard_count]
    if getattr(args, 'max_pages', None):
        sources = sources[:args.max_pages]
    if not sources:
        raise ValueError('No source pages selected')
    config = inference_config(args)
    policy = getattr(args, 'recovery_policy', 'none')
    anchor_protocol = getattr(args, 'anchor_protocol', 'quote')
    edge_prompt_policy = getattr(args, 'edge_prompt_policy', 'legacy')
    if edge_prompt_policy == 'grounded-v3' and anchor_protocol != 'span-id-v2':
        raise ValueError('grounded-v3 requires span-id-v2')
    role_path = getattr(args, 'visual_role_map', None)
    role_map = source_grounding.load_role_map(role_path)
    policy_config = {'recovery_policy': policy, 'max_attempts': getattr(args, 'max_attempts', 1),
                     'anchor_protocol': anchor_protocol, 'edge_prompt_policy': edge_prompt_policy,
                     'visual_role_map_sha256': hashlib.sha256(Path(role_path).read_bytes()).hexdigest() if role_path else None}
    signature = hashlib.sha256(Path(__file__).read_bytes() + Path(flow_recovery.__file__).read_bytes()
        + Path(source_grounding.__file__).read_bytes()
        + args.sources.read_bytes() + json.dumps([config, policy_config], sort_keys=True).encode()).hexdigest()
    if not args.local_check and getattr(args, 'cpu_threads', None):
        import torch
        torch.set_num_threads(args.cpu_threads)
    llm = None if args.local_check else base.create_llm(config)
    if llm is not None:
        seconds = getattr(args, 'inference_budget_seconds', None)
        llm = BudgetedLLM(llm, started + seconds if seconds else None, args.output)
    summaries = []
    for row in sources:
        target = args.output / row['document_id'] / row['page']; target.mkdir(parents=True, exist_ok=True)
        if row['mode'] == 'pptx':
            atoms, visuals, source = pptx_representation(row, target, args.pptx_audit)
        else:
            if row['mode'] == 'corpus':
                # Source render was staged by the caller, preserving the exact PDF page selected.
                staged = args.staged_sources / row['document_id'] / f"{row['page']}.png"; staged.parent.mkdir(parents=True, exist_ok=True)
                if not staged.exists(): raise FileNotFoundError(staged)
                row = {**row, 'image': str(staged.relative_to(ROOT)), 'mode': 'case'}
            atoms, visuals, source = dolphin_representation(row, target, args.fresh_root)
        rep = {'document_id': row['document_id'], 'page': row['page'], 'atoms': atoms, 'visual_bundles': visuals,
               'source_parser': 'native_pptx' if row['mode'] == 'pptx' else 'Dolphin-v2 with DLR native visual override where available',
               'source_image': str(source), 'source_manifest_row': row, 'model': args.model, 'inference_config': config,
               'retrieval_eligible': False, 'production_modified': False, 'recovery_policy': policy}
        digest = hashlib.sha256(signature.encode() + json.dumps(rep, sort_keys=True).encode())
        for path in [source] + [Path(v['presentation']) for v in visuals]:
            digest.update(path.read_bytes())
        page_signature = digest.hexdigest()
        if args.resume and (target / 'summary.json').exists():
            previous = base.read(target / 'summary.json')
            required = ('components.json', 'relations.json', 'evidence_gallery.html', 'flow.json', 'text_units.json',
                        'review_status.json', 'review_units.json', 'candidate_ledger.json', 'composite_views.json',
                        'visual_presentations.json', 'visual_roles.json')
            resumable = {'complete'} if getattr(args, 'retry_failed', False) else {'complete', 'partial', 'flow_failed'}
            if previous.get('status') == 'flow_failed':
                required = ('failure.json', 'input_representation.json')
            if (previous.get('status') in resumable and previous.get('signature') == page_signature
                    and previous.get('local_check') == args.local_check and all((target / name).exists() for name in required)):
                summaries.append(previous)
                continue
        write(target / 'input_representation.json', rep)
        roles = source_grounding.visual_roles(rep, source, role_map)
        write(target / 'visual_roles.json', roles)
        recovery_audit = {}
        try:
            cache = base.read(target / 'flow_checkpoint.json') if args.resume and not args.local_check and (target / 'flow_checkpoint.json').exists() else {}
            if cache.get('signature') == page_signature and validate_flow(cache.get('flow'), rep)['valid']:
                flow = cache['flow']
                recovery_audit = cache.get('recovery', {})
            else:
                reuse_root = getattr(args, 'reuse_flow_root', None)
                can_reuse = not args.local_check and not (policy != 'none' and not base.fragments(rep))
                flow = reusable_flow(reuse_root, rep, source, config) if can_reuse else None
                if flow is not None:
                    write(target / 'flow_reuse.json', {'source_root': str(reuse_root), 'input_and_validation_matched': True})
                else:
                    flow = make_flow(rep, source, llm, target, args.local_check, getattr(args, 'max_attempts', 1), policy)
                    if policy != 'none' and not args.local_check:
                        recovery_audit = base.read(target / 'flow_recovery.json')
            if not args.local_check:
                write(target / 'flow_checkpoint.json', {'signature': page_signature, 'flow': flow, 'recovery': recovery_audit})
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            failure = {'document_id': row['document_id'], 'page': row['page'], 'status': 'flow_failed', 'error': str(exc),
                       'structural_valid': False, 'signature': page_signature, 'local_check': args.local_check}
            write(target / 'failure.json', failure)
            write(target / 'summary.json', failure)
            summaries.append(failure)
            write(args.output / 'progress.json', {'pages': summaries})
            if getattr(args, 'fail_fast', False):
                write(args.output / 'summary.json', {'pages': summaries, 'status': 'stopped_after_failure', 'production_modified': False})
                return False
            continue
        check = validate_flow(flow, rep)
        if not check['valid']: raise ValueError(check)
        units = text_units(flow, rep); fragments = base.fragments(rep)
        review_units = units + structural_review_units(flow, rep)
        with Image.open(source) as page_image: size = page_image.size
        owner = {v: item['content_item_id'] for item in flow['content_items'] for v in item['visual_panel_ids']}
        presentations = [{'panel_id': v['visual_bundle_id'], 'image': v['presentation'], 'mode': v['provenance_state']} for v in visuals]
        edges = []; candidate_ledger = {}; calls = 0; reviews = {}
        for index, visual in enumerate(visuals, 1):
            vid, label = visual['visual_bundle_id'], f'VISUAL_{index:02d}'
            if roles[vid]['exclude_from_semantic_candidates']:
                candidate_ledger[vid] = {'selected': [], 'ranked': [], 'exclusion': roles[vid]}
                reviews[vid] = {'status': 'reviewed_noncontent_visual', 'candidate_count': 0, 'visual_role': roles[vid]}
                continue
            selected, ranked = relation_candidates(visual, review_units, owner[vid], rep, fragments, size)
            for candidate in selected:
                candidate['caption_layout_required'] = True
                if anchor_protocol in {'span-id-v1', 'span-id-v2'}:
                    candidate['anchor_protocol'] = anchor_protocol
                    candidate['evidence_spans'] = source_grounding.evidence_spans(candidate['unit_id'], candidate['text'], protocol=anchor_protocol)
            candidates = {r['unit_id']: r for r in selected}; candidate_ledger[vid] = {'selected': selected, 'ranked': ranked}
            reviews[vid] = {'status': 'local_not_reviewed' if args.local_check else 'no_candidates',
                            'candidate_count': len(candidates)}
            if args.local_check or not candidates: continue
            reviews[vid]['status'] = 'failed'
            prompt = ('Review one visual against candidate text components. First image is the page, second is ' + label + '. '
                      'Geometry is only a candidate hint. Return edges only when source text directly captions or explains visible content. '
                      'A visual can have one CAPTION_FOR edge and several ILLUSTRATES edges. Do not use topic similarity. '
                      'Content-item ownership is uncertain: cross_item candidates are permitted but require direct visual support, not proximity. '
                      'CAPTION_FOR means a standalone figure caption, not narrative prose describing a similar scene. '
                      'A caption beneath a DIFFERENT photo does not caption this target merely because it mentions the same vehicle or event. '
                      'For every CAPTION_FOR, verify placement against the target image on the full page. '
                      'Use caption_attachment=standalone_target only for a caption attached to this target; '
                      'use explicit_shared_panel only when wording or panel labels explicitly cover this target among multiple images. '
                      'For shared captions, quote the part referring to this target. Explain placement and any panel wording in caption_layout_basis. '
                      'Respect caption_policy: body_only can only be ILLUSTRATES, and only for specific visible content. '
                      'For layout_review_required, the earlier page-furniture label may be wrong: CAPTION_FOR requires '
                      'an additional caption_layout_basis describing its standalone caption placement and typography on the page. '
                      'Do not link running headers, page numbers or unrelated text. Mark visibly corrupted OCR SUSPECT. '
                      'Return at most one edge per text_unit_id. If that text captions the figure, use CAPTION_FOR; '
                      'descriptions of its subpanels belong in optional supporting_anchors on that same edge. '
                      'Each edge needs a unique exact quote from the supplied source text; whitespace may differ but words may not. '
                      'Return JSON with visual_label="' + label + '" and edges (a list; empty if no grounded association). '
                      'Each edge has text_unit_id (from candidates), relation (CAPTION_FOR or ILLUSTRATES), '
                      'anchor (unique exact source quote at least 12 characters, or the full text for a shorter component), basis (specific visible support), '
                      'text_quality (UNVERIFIED or SUSPECT). Do not repair OCR words, punctuation or LaTeX. '
                      'Required output shape: {"visual_label":"' + label + '","edges":['
                      '{"text_unit_id":"<candidate ID>","relation":"CAPTION_FOR or ILLUSTRATES",'
                      '"anchor":"<exact source substring>","basis":"<specific visible evidence>",'
                      '"text_quality":"UNVERIFIED or SUSPECT","supporting_anchors":[], '
                      '"caption_attachment":"standalone_target or explicit_shared_panel for CAPTION_FOR; null for ILLUSTRATES",'
                      '"caption_layout_basis":"<target-specific placement and panel-label evidence for CAPTION_FOR; null for ILLUSTRATES>"}]}. '
                      'Return edges:[] if unsupported. All caption edges MUST include both caption fields. Candidates: '
                      + json.dumps(candidates, ensure_ascii=False))
            if anchor_protocol in {'span-id-v1', 'span-id-v2'}:
                prompt = source_grounding.span_prompt(prompt, label, candidates)
            if edge_prompt_policy == 'grounded-v3':
                prompt = source_grounding.grounded_prompt(label, candidates)
            write(target / f'{vid}_edge_prompt.json', {'anchor_protocol': anchor_protocol, 'edge_prompt_policy': edge_prompt_policy, 'prompt': prompt})
            for attempt in range(getattr(args, 'max_attempts', 1)):
                cache_path = target / f'{vid}_edge_checkpoint.json'
                cache = base.read(cache_path) if attempt == 0 and args.resume and cache_path.exists() else {}
                cached = cache.get('signature') == page_signature
                if cached:
                    raw = json.dumps(cache['result'])
                else:
                    calls += 1
                    raw = llm.generate_raw_with_images('Relation-first evidence reviewer. JSON only.', prompt, [str(source), visual['presentation']], 1200).raw
                    write(target / f'{vid}_edge_attempt_{attempt}.json', {'raw': raw})
                try:
                    original_result = base.extract_json(raw)
                    result, rejected = validate_edges_individually(original_result, label, candidates,
                        allow_partial_support=policy in flow_recovery.POLICIES)
                    write(cache_path, {'signature': page_signature, 'result': original_result})
                    for edge in result['edges']:
                        unit = next(u for u in review_units if u['text_unit_id'] == edge['text_unit_id'])
                        context = next((s for item in flow['content_items'] if item['content_item_id'] == unit['content_item_id']
                                        for s in item['flows'] if s['flow_id'] == unit['flow_id']),
                                       {'fragment_ids': unit['fragment_ids']})
                        for support in edge['supporting_spans']:
                            support['source_spans'] = anchor_fragments(unit, support, fragments)
                        edge.update({'visual_id': vid, 'context_fragment_ids': context['fragment_ids'],
                                     'anchor_text_unit_id': unit['text_unit_id'],
                                     'source_spans': anchor_fragments(unit, edge, fragments),
                                     'candidate_scope': candidates[edge['text_unit_id']]['candidate_scope'],
                                     'original_structural_role': unit.get('structural_role'),
                                     'geometry': candidates[edge['text_unit_id']]['geometry']})
                        edges.append(edge)
                    reviews[vid]['status'] = ('partial' if result['edges'] else 'failed') if rejected else (
                        'matched' if result['edges'] else 'reviewed_no_match')
                    reviews[vid].update(accepted_relations=len(result['edges']),
                                        rejected_relations=sum(r.get('rejection_kind') != 'supporting_anchor' for r in rejected),
                                        rejected_supporting_anchors=sum(r.get('rejection_kind') == 'supporting_anchor' for r in rejected),
                                        rejected_edges=rejected)
                    write(target / f'{vid}_edge_validation_{attempt}.json',
                          {'valid': not rejected, 'relations': len(result['edges']), 'rejected_edges': rejected})
                    break
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    reviews[vid]['error'] = str(exc)
                    write(target / f'{vid}_edge_validation_{attempt}.json', {'valid': False, 'error': str(exc)})
                    prompt += '\nCorrect schema only: ' + str(exc)
            write(target / 'review_status.json', reviews)
        nodes = [{'node_id': f"{rep['document_id']}_{rep['page']}_{unit['text_unit_id']}", 'node_type': 'text_component',
                  'fragment_ids': unit['fragment_ids'], 'visual_ids': [], 'flow_id': unit['flow_id']} for unit in units]
        nodes += [{'node_id': f"{rep['document_id']}_{rep['page']}_{visual['visual_bundle_id']}", 'node_type': 'visual_component',
                   'fragment_ids': [], 'visual_ids': [visual['visual_bundle_id']], 'flow_id': None,
                   'visual_role': roles[visual['visual_bundle_id']]} for visual in visuals]
        nodes += [{'node_id': f"{rep['document_id']}_{rep['page']}_S_{entry['fragment_id']}",
                   'node_type': 'structural_component', 'role': entry['role'], 'fragment_ids': [entry['fragment_id']],
                   'visual_ids': [], 'flow_id': None} for item in flow['content_items'] for entry in item['structural_fragments']]
        validate_components(rep, nodes)
        for node in nodes:
            node.update(status='SHADOW_UNVERIFIED', retrieval_eligible=False)
        node_for_text = {u['text_unit_id']: f"{rep['document_id']}_{rep['page']}_{u['text_unit_id']}" for u in review_units}
        node_for_visual = {v['visual_bundle_id']: f"{rep['document_id']}_{rep['page']}_{v['visual_bundle_id']}" for v in visuals}
        for edge in edges:
            edge['source_node_id'] = node_for_visual[edge['visual_id']]; edge['target_node_id'] = node_for_text[edge['text_unit_id']]
            edge['relation_type'] = edge.pop('relation')
            if edge['relation_type'] == 'CAPTION_FOR':
                edge['source_node_id'], edge['target_node_id'] = edge['target_node_id'], edge['source_node_id']
        composite_views = []
        for uid in dict.fromkeys(e['text_unit_id'] for e in edges):
            matches = [e for e in edges if e['text_unit_id'] == uid]
            composite_views.append({'view_id': f'CV_{len(composite_views)+1:03d}',
                'component_node_ids': [node_for_text[uid]] + [node_for_visual[e['visual_id']] for e in matches],
                'kind': 'linked_evidence_view', 'destructive_merge': False})
        write(target / 'input_representation.json', rep); write(target / 'flow.json', flow); write(target / 'text_units.json', units)
        write(target / 'review_units.json', review_units)
        write(target / 'candidate_ledger.json', candidate_ledger); write(target / 'relations.json', edges); write(target / 'components.json', nodes)
        write(target / 'composite_views.json', composite_views); write(target / 'visual_presentations.json', presentations)
        write(target / 'review_status.json', reviews)
        build_gallery(target, rep, nodes, edges, presentations)
        by_id = {n['node_id']: n for n in nodes}
        view_nodes = [{'node_id': v['view_id'], 'fragment_ids': [f for nid in v['component_node_ids'] for f in by_id[nid]['fragment_ids']],
                       'visual_ids': [i for nid in v['component_node_ids'] for i in by_id[nid]['visual_ids']]} for v in composite_views]
        if view_nodes:
            shutil.copy2(target / 'evidence_gallery.html', target / 'components_gallery.html')
            build_gallery(target, rep, view_nodes + nodes, edges, presentations)
        summary = {'document_id': row['document_id'], 'page': row['page'], 'components': len(nodes), 'relations': len(edges),
                   'linked_views': len(composite_views), 'visuals': len(visuals), 'model_calls': calls,
                   'structural_valid': check['valid'], 'local_check': args.local_check, 'production_modified': False,
                   'status': 'local_check' if args.local_check else ('partial' if recovery_audit.get('needs_review') or any(r['status'] in {'failed', 'partial'} for r in reviews.values()) else 'complete'),
                   'flow_review_required': bool(recovery_audit.get('needs_review')),
                   'flow_recovery': recovery_audit, 'recovery_policy': policy,
                   'anchor_protocol': anchor_protocol, 'edge_prompt_policy': edge_prompt_policy,
                   'visual_role_map_sha256': policy_config['visual_role_map_sha256'],
                   'visual_role_counts': dict(Counter(r['role'] for r in roles.values())),
                   'review_counts': dict(Counter(r['status'] for r in reviews.values())), 'signature': page_signature,
                   'limitations': ['no_parsed_text'] if not atoms else []}
        write(target / 'summary.json', summary); summaries.append(summary)
        write(args.output / 'progress.json', {'pages': summaries})
        if getattr(args, 'fail_fast', False) and summary['status'] == 'partial':
            write(args.output / 'summary.json', {'pages': summaries, 'status': 'stopped_after_failure', 'production_modified': False})
            return False
    failures = sum(s.get('status') not in {'complete', 'local_check'} for s in summaries)
    write(args.output / 'summary.json', {'pages': summaries, 'production_modified': False,
          'status': 'completed_with_failures' if failures else ('local_check' if args.local_check else 'complete'),
          'validation_failed_pages': failures, 'processed_pages': len(summaries),
          'selected_pages': len(sources)})
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', type=Path, required=True); parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--fresh-root', type=Path, required=True); parser.add_argument('--staged-sources', type=Path, required=True)
    parser.add_argument('--pptx-audit', type=Path, required=True); parser.add_argument('--model', default=str(ROOT / 'external/models/Qwen3.5-35B-A3B'))
    parser.add_argument('--local-check', action='store_true')
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--dtype', choices=('float32', 'bfloat16'), help='Default: float32 for CPU, bfloat16 for CUDA.')
    parser.add_argument('--cpu-threads', type=int)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true', help='With --resume, explicitly retry pages previously marked failed/partial.')
    parser.add_argument('--reuse-flow-root', type=Path, help='Reuse validated flows only when source image, prompt inputs and model configuration match.')
    parser.add_argument('--max-attempts', type=int, default=1, help='Model attempts per flow/visual; failed validation is recorded and processing continues.')
    parser.add_argument('--recovery-policy', choices=('none', 'bounded-v1', 'bounded-v2'), default='none',
                        help='Shadow only: visual-only fallback; v1 duplicate choice or v2 bounded assignment patch; per-support anchor rejection.')
    parser.add_argument('--anchor-protocol', choices=('quote', 'span-id-v1', 'span-id-v2'), default='quote',
                        help='Select exact source spans by ID instead of generating quotations.')
    parser.add_argument('--edge-prompt-policy', choices=('legacy', 'grounded-v3'), default='legacy')
    parser.add_argument('--visual-role-map', type=Path,
                        help='Source-reviewed visual roles bound to page/crop hashes and geometry; unlisted visuals remain UNKNOWN.')
    parser.add_argument('--shard-index', type=int, default=0)
    parser.add_argument('--shard-count', type=int, default=1)
    parser.add_argument('--page-key', action='append', help='Select document_id/page; repeat for multiple pages.')
    parser.add_argument('--max-pages', type=int, help='Limit pages in this invocation after shard selection.')
    parser.add_argument('--fail-fast', action='store_true')
    parser.add_argument('--inference-budget-seconds', type=int, help='Stop starting new model calls after this duration, including model load.')
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        parser.error('shard-index must be in [0, shard-count)')
    if args.max_pages is not None and args.max_pages <= 0:
        parser.error('max-pages must be positive')
    if args.inference_budget_seconds is not None and args.inference_budget_seconds <= 0:
        parser.error('inference-budget-seconds must be positive')
    if args.cpu_threads is not None and args.cpu_threads <= 0:
        parser.error('cpu-threads must be positive')
    if args.max_attempts <= 0:
        parser.error('max-attempts must be positive')
    try:
        if not run(args):
            raise SystemExit(2)
    except InferenceBudgetExhausted as exc:
        print(str(exc), flush=True)
        raise SystemExit(75)
