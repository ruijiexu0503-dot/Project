"""Prepare matched raster views and report existing Dolphin outputs; shadow only."""
import argparse
import base64
import html
import io
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'parsing/src'))
from PIL import Image
from audit_background_dual_masks import altered_pdf, render, response_mask

OUT = ROOT / 'parsing/audits/dolphin_layer_parsing_ablation_v1'
PILOT = ROOT / 'parsing/experiments/dolphin_v2_pilot'

def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False))

def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    cases, groups = [], []
    sources = [
        ('dlr', 'data/incoming/DLRmagazine_176_EN.pdf',
         'parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2', [9, 17]),
        ('nvidia', 'data/incoming/financial_reports/NVIDIA_2026_Annual_Report.pdf',
         'parsing/audits/gated_background_assets_shadow_v1/NVIDIA_2026_Annual_Report_full_v1', [5]),
    ]
    for name, pdf, audit, pages in sources:
        data = (ROOT / pdf).read_bytes()
        assets = [json.loads(s) for s in (ROOT / audit / 'visual_assets.jsonl').read_text().splitlines()]
        for page in pages:
            base = render(data, page - 1, 1600)
            selected = [a for a in assets if a['source_page'] == page]
            def area(a):
                return sum(max(0, b[2]-b[0])*max(0, b[3]-b[1]) for b in
                           [m['rendered_bbox_pixels'] for m in a['render_layer_members']])
            for asset in sorted(selected, key=area, reverse=True)[:2]:
                gid = name + '_' + asset['asset_id']
                members = asset['render_layer_members']
                sx, sy = base.width/asset['image_size'][0], base.height/asset['image_size'][1]
                boxes = [m['rendered_bbox_pixels'] for m in members]
                crop = [max(0, math.floor(min(b[0] for b in boxes)*sx)),
                        max(0, math.floor(min(b[1] for b in boxes)*sy)),
                        min(base.width, math.ceil(max(b[2] for b in boxes)*sx)),
                        min(base.height, math.ceil(max(b[3] for b in boxes)*sy))]
                targets = asset['invocation_paths']
                layer = render(altered_pdf(data, page-1, targets, True), 0, 1600)
                mask = response_mask(data, page-1, targets, False, 1600)
                # Binary support avoids applying alpha twice; holes may remove overlaid text.
                visible = Image.composite(base, Image.new('RGB', base.size, 'white'),
                                          mask.point(lambda v: 255 if v >= 24 else 0))
                group = {'id': gid, 'pdf': pdf, 'page': page, 'asset_id': asset['asset_id'],
                         'crop_window_pixels': crop, 'page_render_size': list(base.size),
                         'source_member_bboxes': boxes, 'source_image_size': asset['image_size'],
                         'invocation_paths': targets, 'cases': [],
                         'note': 'Crop envelope is an input window, not a new evidence bbox. Asset grouping is inherited, not semantic gold.'}
                for variant, image in [('original_crop', base), ('visible_support', visible), ('isolated_layer', layer)]:
                    cid = gid + '_' + variant
                    path = OUT / (cid + '.png')
                    image.crop(crop).save(path)
                    cases.append({'case_id': cid, 'input_image': str(path.relative_to(ROOT))})
                    group['cases'].append(cid)
                groups.append(group)
    for name, pdf, page in [
        ('nist_table', 'data/incoming/government_reports/NIST_AI_100-1_AI_RMF_1.0.pdf', 28),
        ('nvidia_table', 'data/incoming/financial_reports/NVIDIA_2026_Annual_Report.pdf', 128)]:
        cid = name + '_original_control'
        path = OUT / (cid + '.png')
        render((ROOT/pdf).read_bytes(), page-1, 1600).save(path)
        cases.append({'case_id': cid, 'input_image': str(path.relative_to(ROOT))})
        groups.append({'id': name, 'pdf': pdf, 'page': page, 'cases': [cid],
                       'note': 'Vector/text table control: no raster layer substitution.'})
    dump(OUT/'cases.json', {'experiment': 'dolphin-layer-parsing-ablation-v1', 'cases': cases})
    dump(OUT/'provenance.json', {'groups': groups, 'production_modified': False,
         'evaluation': 'No gold accuracy. Compare omissions, duplicate text, numeric fidelity, table topology and visible vs hidden content. Isolated-layer text must never be auto-inserted as visible evidence.'})
    report()
    print(f'Prepared {len(cases)} cases / {len(groups)} groups', flush=True)

def report():
    manifest = json.loads((OUT/'cases.json').read_text())
    cards, rows = [], []
    for case in manifest['cases']:
        cid = case['case_id']
        md = OUT/'work'/cid/'markdown'/(cid+'.md')
        status = 'complete' if md.exists() else 'pending'
        text = md.read_text() if md.exists() else 'Waiting for Dolphin inference.'
        row = {'case_id': cid, 'status': status, 'markdown_chars': len(text) if md.exists() else None,
               'table_count': text.count('<table') if md.exists() else None}
        rows.append(row)
        encoded = base64.b64encode((ROOT/case['input_image']).read_bytes()).decode()
        cards.append(f'<section><h2>{html.escape(cid)}</h2><p>{status}</p><img src="data:image/png;base64,{encoded}"><pre>{html.escape(text)}</pre></section>')
    dump(OUT/'summary.json', {'cases': rows, 'complete': sum(r['status']=='complete' for r in rows),
         'total': len(rows), 'production_modified': False, 'accuracy_evaluated': False})
    (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Dolphin layer ablation</title><style>body{font:15px system-ui;margin:24px}section{border:1px solid #aaa;padding:15px;margin:20px 0}img{max-width:100%;max-height:850px}pre{white-space:pre-wrap}</style><h1>Dolphin layer parsing: matched input comparison</h1><p>Original crop / visible support / isolated native layer. Masks are renderer responses, not semantic segmentation. Isolated layers can reveal content hidden on the source page. No automatic evidence merge.</p>'+''.join(cards))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()
    report() if args.report else prepare()
