#!/usr/bin/env python3
"""Build a cross-format/content-type report from isolated adapter audits."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

import fitz


def load(path):
    return json.loads(Path(path).read_text())


def pdf_vector_metrics(path, pages=None):
    document = fitz.open(path)
    numbers = pages or list(range(1, len(document) + 1))
    rows = []
    for number in numbers:
        page = document[number - 1]
        rows.append({'page': number, 'vector_drawing_paths': len(page.get_drawings()),
                     'image_references': len(page.get_images(full=True))})
    return {'audited_pages': len(rows), 'pages_with_vector_drawings': sum(r['vector_drawing_paths'] > 0 for r in rows),
            'vector_drawing_paths': sum(r['vector_drawing_paths'] for r in rows),
            'pages_with_image_references': sum(r['image_references'] > 0 for r in rows),
            'image_references': sum(r['image_references'] for r in rows),
            'max_vector_page': max(rows, key=lambda r: r['vector_drawing_paths']), 'pages': rows}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    cases = [
        {'id': 'dlr_pdf', 'format': 'PDF', 'content_type': 'magazine', 'scope': 'full 32 source spreads',
         'source': root / 'data/incoming/DLRmagazine_176_EN.pdf',
         'audit': root / 'parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/summary.json',
         'report': root / 'parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/report.html',
         'example': root / 'parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/page_0009/gate_overlay.jpg'},
        {'id': 'gw_pdf', 'format': 'PDF', 'content_type': 'scientific paper', 'scope': 'full 16 pages',
         'source': root / 'data/processed/gw150914_detection.pdf',
         'audit': root / 'parsing/audits/multi_type_visual_adapter_v1/gw150914_detection_full/summary.json',
         'report': root / 'parsing/audits/multi_type_visual_adapter_v1/gw150914_detection_full/report.html',
         'example': root / 'parsing/audits/multi_type_visual_adapter_v1/gw150914_detection_full/page_0002/gate_overlay.jpg'},
        {'id': 'nist_pdf', 'format': 'PDF', 'content_type': 'government report', 'scope': 'full 48 pages',
         'source': root / 'data/incoming/government_reports/NIST_AI_100-1_AI_RMF_1.0.pdf',
         'audit': root / 'parsing/audits/multi_type_visual_adapter_v1/NIST_AI_RMF_full/summary.json',
         'report': root / 'parsing/audits/multi_type_visual_adapter_v1/NIST_AI_RMF_full/report.html',
         'example': root / 'parsing/audits/multi_type_visual_adapter_v1/NIST_AI_RMF_full/page_0001/gate_overlay.jpg'},
        {'id': 'nvidia_pdf', 'format': 'PDF', 'content_type': 'financial report', 'scope': '7 representative pages',
         'source': root / 'data/incoming/financial_reports/NVIDIA_2026_Annual_Report.pdf', 'pages': [1,5,12,33,84,149,175],
         'audit': root / 'parsing/audits/multi_type_visual_adapter_v1/NVIDIA_2026_Annual_Report_sample/summary.json',
         'report': root / 'parsing/audits/multi_type_visual_adapter_v1/NVIDIA_2026_Annual_Report_sample/report.html',
         'example': root / 'parsing/audits/multi_type_visual_adapter_v1/NVIDIA_2026_Annual_Report_sample/page_0084/gate_overlay.jpg'},
    ]
    outputs = []
    for case in cases:
        audit = load(case['audit']); vector = pdf_vector_metrics(case['source'], case.get('pages'))
        totals = audit['totals']; zero_asset_pages = sum(p['assets'] == 0 for p in audit['pages'])
        max_assets = max(audit['pages'], key=lambda p: p['assets'])
        row = {k: str(v) if isinstance(v, Path) else v for k, v in case.items() if k not in ('audit','report','example','source')}
        row.update({'source': str(case['source']), 'audit_summary': str(case['audit']), 'report': str(case['report']),
                    'assets': totals['assets'], 'dual_mask': totals['dual_mask'], 'fast_bbox': totals['fast_bbox'],
                    'unresolved': totals['unresolved'], 'zero_raster_asset_pages': zero_asset_pages,
                    'max_raster_assets_on_page': {'page': max_assets['page'], 'assets': max_assets['assets']},
                    'vector_metrics': vector})
        if case['id'] == 'dlr_pdf':
            row['finding'] = 'Raster-rich magazine works, but page 26 also has 8,907 vector drawing paths; raster assets are not full visual coverage.'
        elif case['id'] == 'gw_pdf':
            row['finding'] = 'Page 2 Figure 1 is encoded as 65 raster tiles. Figure-level bundling must precede asset gating.'
        elif case['id'] == 'nist_pdf':
            row['finding'] = 'Only 10 raster assets across 48 pages; most content is text/vector and should remain addressable outside this adapter.'
        else:
            row['finding'] = 'Three sampled pages have zero raster assets despite visible text, rules/tables or vector layout. A vector branch is required.'
        outputs.append(row)
    pptx = load(root / 'parsing/audits/pptx_native_adapter_pilot/ESS203_day_01/summary.json')
    raster = load(root / 'parsing/audits/multi_type_visual_adapter_v1/dlr_raster_sequence.json')
    overall = {'experiment': 'multi-type-visual-adapter-audit-v1', 'pdf_cases': outputs,
               'pptx': {'slides': pptx['slides'], 'objects': sum(pptx['totals'].values()), 'pictures': pptx['pictures'],
                        'picture_overlap_pairs': pptx['picture_overlap_pairs'],
                        'finding': 'Native object geometry and z-order are available; faithful pixel rendering remains unavailable.'},
               'raster_sequence': {'pages': len(raster['page_inputs']), 'route': raster['visual_route'],
                                   'layer_mask_status': raster['mask_contract']['layer_mask_status'],
                                   'finding': 'OCR/layout may continue, but hidden extent and native layers cannot be recovered.'},
               'conclusion': ['Route by source capability before visual extraction.',
                              'PDF raster XObjects, PDF vector drawings, PPTX native objects and flattened raster regions are separate evidence sources.',
                              'Do not interpret zero raster assets as zero visual evidence.',
                              'Do not run per-tile masks before figure/asset bundling.'],
               'production_modified': False}
    (args.output / 'summary.json').write_text(json.dumps(overall, indent=2))
    style = '''<!doctype html><meta charset="utf-8"><title>Multi-type visual adapter audit</title><style>body{font:15px system-ui;background:#eef1f5;margin:20px}header,section{background:white;padding:18px;margin:16px auto;max-width:1400px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}.examples{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.examples img{width:100%}pre{white-space:pre-wrap}</style>'''
    table = '<table><tr><th>Case</th><th>Scope</th><th>Raster assets</th><th>Dual / Fast</th><th>Zero-asset pages</th><th>Vector paths</th><th>Finding</th><th>Audit</th></tr>'
    for row, case in zip(outputs, cases):
        report_link = Path(os.path.relpath(case['report'], args.output)).as_posix()
        table += f'<tr><td>{html.escape(row["format"]+" · "+row["content_type"])}</td><td>{html.escape(row["scope"])}</td><td>{row["assets"]}</td><td>{row["dual_mask"]} / {row["fast_bbox"]}</td><td>{row["zero_raster_asset_pages"]}</td><td>{row["vector_metrics"]["vector_drawing_paths"]}</td><td>{html.escape(row["finding"])}</td><td><a href="{report_link}">open</a></td></tr>'
    pptx_report = Path(os.path.relpath(root / 'parsing/audits/pptx_native_adapter_pilot/ESS203_day_01/report.html', args.output)).as_posix()
    table += f'<tr><td>PPTX · slides</td><td>full {pptx["slides"]} slides</td><td>{pptx["pictures"]} native pictures</td><td colspan="3">{sum(pptx["totals"].values())} native objects; {pptx["picture_overlap_pairs"]} picture overlaps</td><td>{html.escape(overall["pptx"]["finding"])}</td><td><a href="{pptx_report}">open</a></td></tr>'
    table += f'<tr><td>Raster page sequence</td><td>{len(raster["page_inputs"])} pages</td><td colspan="4">{raster["visual_route"]}; layer={raster["mask_contract"]["layer_mask_status"]}</td><td>{html.escape(overall["raster_sequence"]["finding"])}</td><td>routing only</td></tr></table>'
    pictures = ''.join(f'<figure><figcaption>{html.escape(c["content_type"])}</figcaption><img src="{Path(os.path.relpath(c["example"], args.output)).as_posix()}"></figure>' for c in cases)
    page = style + '<header><h1>Multi-type visual adapter audit</h1><p>This compares source capabilities; counts are not semantic visual-node accuracy.</p><pre>' + html.escape(json.dumps(overall['conclusion'], indent=2)) + '</pre></header><section>' + table + '</section><section><h2>Examples</h2><div class="examples">' + pictures + '</div></section>'
    (args.output / 'report.html').write_text(page)
    print(json.dumps({'output': str(args.output), 'pdf_cases': len(outputs), 'pptx_slides': pptx['slides'], 'raster_pages': len(raster['page_inputs'])}, indent=2))


if __name__ == '__main__':
    main()
