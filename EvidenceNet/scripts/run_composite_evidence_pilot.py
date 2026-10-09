#!/usr/bin/env python3
"""Isolated caption/composite regression pilot over three DLR pages."""
import argparse
import copy
import html
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops
import run_flow_first_evidence_pilot as base

OUT = Path(os.environ.get(
    'COMPOSITE_EVIDENCE_OUTPUT',
    base.ROOT / 'EvidenceNet/output/composite_evidence_pilot_v1',
)).resolve()
FLOW_PROMPT = base.flow_prompt
VALIDATE_FLOW = base.validate_flow
VALIDATE_EVIDENCE = base.validate_evidence
REPORT = base.report


def flow_prompt(rep):
    return FLOW_PROMPT(rep) + '''
ROLE REVIEW REQUIRED:
Parser roles are proposals. Identify image captions by what the words describe,
including text printed on photographs. Captions are caption flows, never furniture.
Keep each caption in its own flow under the same content item as its image when
ownership is supported. Picture credits and logos are structural; explanatory
image labels must be retained in caption flows. Do not use flow_kind other.
Sidebar and main prose can share an article but need separate reading flows.
The output must preserve all fragments exactly once.
'''


def validate_flow(flow, rep):
    result = VALIDATE_FLOW(flow, rep)
    seen = set()
    for item in flow.get('content_items', []):
        for stream in item.get('flows', []):
            fid = stream.get('flow_id')
            if not fid or fid in seen or stream.get('flow_kind') not in {'main', 'sidebar', 'caption'}:
                result['errors'].append({'type': 'invalid_flow_id_or_kind', 'flow': stream})
            seen.add(fid)
            ids = stream.get('fragment_ids', [])
            for edge in stream.get('continuations', []):
                a, b = edge.get('from_fragment_id'), edge.get('to_fragment_id')
                if a in ids and b in ids and ids.index(b) != ids.index(a) + 1:
                    result['errors'].append({'type': 'reversed_continuation', 'edge': edge})
    result['valid'] = not result['errors']
    return result


def evidence_prompt(rep, flow):
    return '''Return JSON with evidence_units, context_items: [], relations.
Each evidence unit has evidence_unit_id, content_item_id, flow_id,
unit_type (TEXT, VISUAL, COMPOSITE), fragment_ids, visual_panel_ids,
completeness (COMPLETE, POSSIBLE_CONTINUATION, UNRESOLVED), association_basis.

Every non-structural fragment, including captions, must occur exactly once in
evidence_units. Every visual panel must occur exactly once. Structural fragments
stay in the flow ledger and never become evidence text. Do not invent IDs.

Prefer COMPOSITE for a picture with its directly interpreting caption. Include
the caption's exact fragments with the picture in ONE unit. Explain the observed
association in association_basis. Shared topic or proximity alone is insufficient.
When a caption directly names the visual's subject, a standalone VISUAL plus a
separate caption is invalid: return one COMPOSITE. Select the native asset panel,
never the enclosing Dolphin figure rectangle, as the visual component.
Use a standalone TEXT caption when its visual target is uncertain and record why.
Keep background photographs independent of unrelated overlaid article paragraphs.
Main or sidebar prose can form a COMPOSITE only if it directly explains the image.
Do not merge the entire article with a photograph.

Text fragments of each unit must be an ordered contiguous subset of its one flow.
The unit and all its panels must belong to that flow's content item. Visual-only
units must use their panel's content item. Same-sentence continuation endpoints
must stay in one unit. Preserve truncated sentences as POSSIBLE_CONTINUATION.

Relations: HAS_HEADING runs from structural title/section_heading/dek fragment to
an evidence ID. ILLUSTRATES runs from a visual/composite unit to a text/composite
unit. No self-relations. Captions already inside COMPOSITE need no CAPTION_OF edge.

FLOW:
''' + json.dumps(flow, ensure_ascii=False) + '\nTEXT:\n' + json.dumps(
        {key: value['text'] for key, value in base.fragments(rep).items()}, ensure_ascii=False)


def validate_evidence(assembly, flow, rep):
    # Reuse exact coverage checks, treating caption text as evidence in this variant.
    projected = copy.deepcopy(flow)
    for item in projected.get('content_items', []):
        for stream in item.get('flows', []):
            if stream.get('flow_kind') == 'caption':
                stream['flow_kind'] = 'main'
    result = VALIDATE_EVIDENCE(assembly, projected, rep)
    owners = {s['flow_id']: item['content_item_id'] for item in flow['content_items'] for s in item.get('flows', [])}
    panels = {p: item['content_item_id'] for item in flow['content_items'] for p in item.get('visual_panel_ids', [])}
    units = assembly.get('evidence_units', [])
    ids = [u.get('evidence_unit_id') for u in units]
    if len(ids) != len(set(ids)) or None in ids:
        result['errors'].append({'type': 'duplicate_or_missing_evidence_id'})
    membership = {f: u.get('evidence_unit_id') for u in units for f in u.get('fragment_ids', [])}
    for u in units:
        text, visual = bool(u.get('fragment_ids')), bool(u.get('visual_panel_ids'))
        expected = 'COMPOSITE' if text and visual else 'TEXT' if text else 'VISUAL' if visual else None
        if expected is None or u.get('unit_type') != expected:
            result['errors'].append({'type': 'unit_type_mismatch', 'unit': u.get('evidence_unit_id')})
        if text and owners.get(u.get('flow_id')) != u.get('content_item_id'):
            result['errors'].append({'type': 'text_ownership_mismatch', 'unit': u.get('evidence_unit_id')})
        for p in u.get('visual_panel_ids', []):
            if panels.get(p) != u.get('content_item_id'):
                result['errors'].append({'type': 'visual_ownership_mismatch', 'panel': p})
        if expected == 'COMPOSITE' and not u.get('association_basis'):
            result['errors'].append({'type': 'missing_association_basis', 'unit': u.get('evidence_unit_id')})
    for item in flow['content_items']:
        for stream in item.get('flows', []):
            for edge in stream.get('continuations', []):
                if edge.get('kind') == 'same_sentence' and membership.get(edge.get('from_fragment_id')) != membership.get(edge.get('to_fragment_id')):
                    result['errors'].append({'type': 'split_sentence', 'edge': edge})
    result['valid'] = not result['errors']
    return result


def render_assets(target, rep):
    ledger = []
    for visual in rep['visual_bundles']:
        components = visual.get('native_components', [])
        output = target / (visual['visual_bundle_id'] + '_page_visible.png')
        row = {'panel_id': visual['visual_bundle_id'], 'member_ids': [c['member_id'] for c in components],
               'mode': 'page_visible_response_support', 'image': None}
        # The native object is the evidence component. A page-support mask may
        # overlap nearby text and other artwork, so it is not a safe crop source.
        available = [c for c in components if c.get('source_object_path') and Path(c['source_object_path']).exists()]
        if available:
            x1 = min(component['bbox'][0] for component in available)
            y1 = min(component['bbox'][1] for component in available)
            x2 = max(component['bbox'][2] for component in available)
            y2 = max(component['bbox'][3] for component in available)
            canvas = Image.new('RGBA', (round(x2 - x1), round(y2 - y1)))
            for component in available:
                with Image.open(component['source_object_path']) as source:
                    image = source.convert('RGBA')
                alpha_path = component.get('source_alpha_mask_path')
                if alpha_path and Path(alpha_path).exists():
                    with Image.open(alpha_path) as alpha:
                        image.putalpha(alpha.convert('L'))
                box = component['bbox']
                size = (max(1, round(box[2] - box[0])), max(1, round(box[3] - box[1])))
                image = image.resize(size, Image.Resampling.LANCZOS)
                canvas.alpha_composite(image, (round(box[0] - x1), round(box[1] - y1)))
            bounds = canvas.getchannel('A').getbbox()
            if bounds:
                canvas = canvas.crop(bounds)
            canvas.save(output)
            row['image'] = str(output)
            row['mode'] = 'pdf_native_recomposed_component'
            row['selected_member_ids'] = [component['member_id'] for component in available]
        row['status'] = 'rendered' if row['image'] else 'needs_render_review'
        ledger.append(row)
    base.write(target / 'visual_presentations.json', ledger)


def report():
    links = []
    for case in base.CASES:
        target = OUT / case['document'] / f"page_{case['page']:04d}"
        if (target / 'evidence_nodes.jsonl').exists():
            subprocess.run([sys.executable, str(base.ROOT / 'EvidenceNet/scripts/build_evidence_gallery.py'),
                            '--page-dir', str(target), '--output', str(target / 'evidence_gallery.html')], check=True)
            links.append(f"<li><a href='{target.relative_to(OUT)}/evidence_gallery.html'>Page {case['page']}</a></li>")
    (OUT / 'review.html').write_text('<!doctype html><meta charset="utf-8"><h1>Composite evidence regression</h1><ul>' + ''.join(links) + '</ul>', encoding='utf-8')


def configure():
    base.OUT = OUT
    base.CASES = [c for c in base.panels.CASES if c['page'] in {9, 12, 17}]
    base.flow_prompt = flow_prompt
    base.evidence_prompt = evidence_prompt
    base.validate_flow = validate_flow
    base.validate_evidence = validate_evidence
    base.EVIDENCE_RETRY_POLICY = 'context_items must be empty. Caption fragments belong in evidence, preferably with their directly associated image in COMPOSITE. Preserve exact coverage and ownership.'
    base.report = report


def prepare():
    base.prepare()
    for case in base.CASES:
        target = OUT / case['document'] / f"page_{case['page']:04d}"
        render_assets(target, base.read(target / 'input_representation.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run', 'report'])
    args = parser.parse_args()
    configure()
    {'prepare': prepare, 'run': base.run, 'report': report}[args.action]()
