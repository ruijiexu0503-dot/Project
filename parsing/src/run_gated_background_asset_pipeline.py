#!/usr/bin/env python3
"""End-to-end shadow runner for gated PDF visual-asset masks.

The source PDF is read-only.  Every resolved asset remains in the inventory;
the gate controls only whether expensive renderer-derived dual masks are made.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
from collections import Counter, defaultdict, deque
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader

from audit_background_complexity_gate import (
    assess,
    clip_flags,
    load,
    normalized_split_boundaries,
    quick_support,
    rect_mask,
)
from audit_background_dual_masks import image_occurrences, render, response_mask
from audit_pdf_object_layers import extract_object, smask_xref
from audit_pdf_rectangular_visual_bundles_document import union_find_groups
from visual_source_capabilities import classify_source


STYLE = """<!doctype html><meta charset="utf-8"><title>Gated background assets</title>
<style>body{font:15px system-ui;background:#eef1f5;margin:20px}header,section{background:white;padding:18px;margin:16px auto;max-width:1400px}img{max-width:100%;height:auto}table{border-collapse:collapse}td,th{padding:7px;border-bottom:1px solid #ddd;text-align:left}.fast{color:#087f4f}.dual{color:#bd6700}.bad{color:#b00020}pre{white-space:pre-wrap}</style>"""


def match_occurrences(document_page, occurrences):
    """Match pypdf paint occurrences to PyMuPDF placements in paint order."""
    by_xref = defaultdict(deque)
    for info in document_page.get_image_info(xrefs=True):
        if info.get('xref'):
            by_xref[int(info['xref'])].append(info)
    matched, unresolved = [], []
    occurrence_counts = defaultdict(int)
    for occurrence in occurrences:
        occurrence_counts[occurrence['xref']] += 1
    info_counts = {xref: len(rows) for xref, rows in by_xref.items()}
    for occurrence in occurrences:
        xref = occurrence['xref']
        if occurrence['unsupported']:
            unresolved.append({**occurrence, 'reason': 'unsupported image stencil or colour-key mask'})
        elif not by_xref[xref]:
            unresolved.append({**occurrence, 'reason': 'no matching rendered placement'})
        else:
            matched.append((occurrence, by_xref[xref].popleft()))
    for xref, rows in by_xref.items():
        while rows:
            info = rows.popleft()
            unresolved.append({'xref': xref, 'bbox': list(info['bbox']),
                               'reason': 'rendered placement has no content-stream occurrence'})
    return matched, unresolved, {'occurrence_counts': dict(occurrence_counts), 'rendered_counts': info_counts}


def inventory_page(data, reader, document, number, base, folder):
    occurrences, warnings = image_occurrences(reader.pages[number - 1], reader)
    matched, unresolved, counts = match_occurrences(document[number - 1], occurrences)
    warnings.extend(unresolved)
    records = []
    for index, (occurrence, info) in enumerate(matched):
        sx = base.width / document[number - 1].rect.width
        sy = base.height / document[number - 1].rect.height
        bbox = list(info['bbox'])
        record = {
            **occurrence,
            'rendered_bbox_pixels': [bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy],
            'smask_xref': smask_xref(document, occurrence['xref']),
            'transform': list(info['transform']),
        }
        record.update(extract_object(document, occurrence['xref'], folder / 'objects' / f'{index}.png'))
        records.append(record)
    axis = [r for r in records if abs(r['transform'][1]) < 1e-5 and abs(r['transform'][2]) < 1e-5
            and r['transform'][0] > 0 and r['transform'][3] > 0]
    groups, comparisons = union_find_groups(axis)
    groups += [[r] for r in records if r not in axis]
    return groups, comparisons, warnings, counts


def decide_page(groups, base, pdf_page, reader_page, reader, split, number, cfg):
    width = cfg['support_grid_width']
    height = round(width * pdf_page.rect.height / pdf_page.rect.width)
    flags = clip_flags(reader_page, reader)
    assets, support, boxes, meta = [], {}, {}, {}
    for index, group in enumerate(groups):
        aid = f'page_{number:04d}_asset_{index + 1:02d}'
        asset = {'asset_id': aid, 'source_page': number,
                 'xrefs': [r['xref'] for r in group], 'invocation_paths': [r['invocation_path'] for r in group],
                 'render_layer_members': group, 'image_size': list(base.size)}
        support[aid], boxes[aid], soft, nonrect = quick_support(asset, width, height, pdf_page, flags, cfg)
        meta[aid] = (soft, nonrect)
        assets.append(asset)
    lines = [line['bbox'] for block in pdf_page.get_text('dict')['blocks'] if block.get('type') == 0
             for line in block.get('lines', [])]
    text_masks = [rect_mask(box, width, height, width / pdf_page.rect.width,
                            height / pdf_page.rect.height).astype(bool) for box in lines]
    boundaries = normalized_split_boundaries(split, f'page_{number:06d}')
    for asset in assets:
        aid = asset['asset_id']; supp = support[aid]; box = boxes[aid]; pixels = int(supp.sum())
        bbox_pairs, support_pairs = [], []
        for other in assets:
            bid = other['asset_id']
            if bid == aid:
                continue
            if np.any(box & boxes[bid]):
                bbox_pairs.append(bid)
            overlap = int((supp & support[bid]).sum())
            fraction = overlap / max(1, min(pixels, int(support[bid].sum())))
            if overlap and fraction >= cfg['meaningful_image_overlap_fraction']:
                support_pairs.append({'asset_id': bid, 'fraction': fraction})
        raw_lines = supported = 0
        text_union = np.zeros_like(supp)
        for text_mask in text_masks:
            raw_lines += bool(np.any(box & text_mask))
            coverage = int((text_mask & supp).sum()) / max(1, int(text_mask.sum()))
            if coverage >= cfg['meaningful_text_line_coverage']:
                supported += 1
                text_union |= text_mask & supp
        crossing = []
        for edge in boundaries:
            cut = round(edge * width)
            fraction = min(int(supp[:, :cut].sum()), int(supp[:, cut:].sum())) / max(1, pixels)
            if fraction >= cfg['boundary_min_side_fraction']:
                crossing.append(edge)
        features = {
            'nonrect_clip': meta[aid][1], 'source_soft_mask': meta[aid][0],
            'support_missing_fraction': max(0, 1 - pixels / max(1, int(box.sum()))),
            'crosses_known_boundary': crossing, 'bbox_image_overlaps': bbox_pairs,
            'confirmed_image_overlaps': support_pairs, 'bbox_text_lines': raw_lines,
            'supported_text_lines': supported,
            'supported_text_area_fraction': int(text_union.sum()) / max(1, pixels),
        }
        asset['features'] = features
        asset.update(assess(features, cfg))
    return assets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', type=Path, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--split-manifest', type=Path,
                    help='Optional physical-page split manifest. Omit when no verified split boundary exists.')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--pages', type=int, nargs='*')
    ap.add_argument('--width', type=int, default=1000)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source_capabilities = classify_source(args.pdf)
    if source_capabilities['visual_route'] != 'PDF_NATIVE_LAYERS':
        raise ValueError(
            f"This runner requires PDF_NATIVE_LAYERS, got {source_capabilities['visual_route']}. "
            "Route flat images through raster segmentation and leave layer_mask unavailable."
        )
    cfg = load(args.config)
    split = load(args.split_manifest) if args.split_manifest else {'pages': []}
    data = args.pdf.read_bytes()
    source_hash = hashlib.sha256(data).hexdigest()
    reader = PdfReader(io.BytesIO(data)); document = fitz.open(stream=data, filetype='pdf')
    fitz.TOOLS.mupdf_display_errors(False)
    pages = args.pages or list(range(1, len(document) + 1))
    all_assets, page_rows, page_links = [], [], []
    for number in pages:
        fitz.TOOLS.mupdf_warnings(reset=True)
        base = render(data, number - 1, args.width)
        folder = args.output / f'page_{number:04d}'; folder.mkdir(exist_ok=True)
        groups, comparisons, warnings, placement_counts = inventory_page(
            data, reader, document, number, base, folder)
        assets = decide_page(groups, base, document[number - 1], reader.pages[number - 1],
                             reader, split, number, cfg)
        overlay_image = base.copy(); draw = ImageDraw.Draw(overlay_image)
        for asset in assets:
            if asset['decision'] == 'DUAL_MASK':
                targets = asset['invocation_paths']
                visible = response_mask(data, number - 1, targets, False, args.width)
                layer = response_mask(data, number - 1, targets, True, args.width)
                visible_name = f"{asset['asset_id']}_visible.png"; layer_name = f"{asset['asset_id']}_layer.png"
                visible.save(folder / visible_name); layer.save(folder / layer_name)
                asset['visible_mask'] = f'page_{number:04d}/{visible_name}'
                asset['layer_mask'] = f'page_{number:04d}/{layer_name}'
                asset['visible_pixels_ge24'] = int((np.asarray(visible) >= 24).sum())
                asset['layer_pixels_ge24'] = int((np.asarray(layer) >= 24).sum())
                support = np.asarray(layer) >= cfg['alpha_support_threshold']
                ys, xs = np.nonzero(support)
                member_boxes = [m['rendered_bbox_pixels'] for m in asset['render_layer_members']]
                envelope = [min(b[0] for b in member_boxes) - 2, min(b[1] for b in member_boxes) - 2,
                            max(b[2] for b in member_boxes) + 2, max(b[3] for b in member_boxes) + 2]
                outside = ((xs < envelope[0]) | (xs >= envelope[2]) |
                           (ys < envelope[1]) | (ys >= envelope[3])) if len(xs) else np.ones(1, dtype=bool)
                asset['mask_support_outside_assigned_bbox_fraction_2px'] = float(outside.mean())
                asset['mask_placement_consistent'] = bool(len(xs) and outside.mean() <= .01)
                if not asset['mask_placement_consistent']:
                    warnings.append({'asset_id': asset['asset_id'],
                                     'reason': 'renderer mask does not match assigned placement envelope'})
            else:
                asset['visible_mask'] = asset['layer_mask'] = None
            color = (225, 125, 0) if asset['decision'] == 'DUAL_MASK' else (0, 155, 85)
            for member_index, member in enumerate(asset['render_layer_members']):
                box = member['rendered_bbox_pixels']; draw.rectangle(box, outline=color, width=3)
                if member_index == 0:
                    draw.text((max(0, box[0] + 2), max(0, box[1] - 13)),
                              asset['asset_id'].split('_')[-1] + ' ' + asset['decision'],
                              fill=color, stroke_width=1, stroke_fill='white')
        base.save(folder / 'original.jpg', quality=88)
        overlay_image.save(folder / 'gate_overlay.jpg', quality=90)
        raw_renderer_warnings = [line for line in fitz.TOOLS.mupdf_warnings(reset=True).splitlines() if line.strip()]
        warning_counts = Counter(raw_renderer_warnings)
        renderer_warnings = [{'message': message, 'count': count}
                             for message, count in sorted(warning_counts.items())]
        stat = {'page': number, 'image_occurrences': sum(len(g) for g in groups), 'assets': len(assets),
                'dual_mask': sum(a['decision'] == 'DUAL_MASK' for a in assets),
                'fast_bbox': sum(a['decision'] == 'FAST_BBOX' for a in assets),
                'unresolved': len(warnings), 'warnings': warnings,
                'renderer_warnings': renderer_warnings, 'placement_counts': placement_counts}
        page_rows.append(stat); all_assets.extend(assets)
        detail = STYLE + f'<header><h1>Page {number}</h1><p><span class="fast">Green FAST_BBOX</span>; <span class="dual">orange DUAL_MASK</span>. No asset is deleted.</p></header>'
        detail += f'<section><img src="gate_overlay.jpg"><pre>{html.escape(json.dumps({"summary": stat, "assets": assets}, indent=2))}</pre></section>'
        (folder / 'report.html').write_text(detail)
        page_links.append(f'<tr><td>{number}</td><td>{len(assets)}</td><td>{stat["dual_mask"]}</td><td>{stat["fast_bbox"]}</td><td class="bad">{stat["unresolved"]}</td><td><a href="page_{number:04d}/report.html">open</a></td></tr>')
        print(json.dumps({k: stat[k] for k in ('page','assets','dual_mask','fast_bbox','unresolved')}), flush=True)
    totals = {'pages': len(pages), 'assets': len(all_assets),
              'dual_mask': sum(a['decision'] == 'DUAL_MASK' for a in all_assets),
              'fast_bbox': sum(a['decision'] == 'FAST_BBOX' for a in all_assets),
              'unresolved': sum(row['unresolved'] for row in page_rows),
              'renderer_warning_pages': sum(bool(row['renderer_warnings']) for row in page_rows),
              'renderer_warning_unique_messages': sum(len(row['renderer_warnings']) for row in page_rows),
              'renderer_warning_events': sum(sum(w['count'] for w in row['renderer_warnings'])
                                             for row in page_rows)}
    summary = {'experiment': 'gated-background-assets-shadow-v1', 'input_pdf': str(args.pdf.resolve()),
               'input_sha256': source_hash, 'config': cfg, 'totals': totals, 'pages': page_rows,
               'source_capabilities': source_capabilities,
               'split_manifest': str(args.split_manifest.resolve()) if args.split_manifest else None,
               'mask_jobs_avoided_fraction': totals['fast_bbox'] / max(1, totals['assets']),
               'production_modified': False,
               'scope': 'asset inventory plus gated dual masks; no OCR, EvidenceNode, or source-PDF mutation'}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    (args.output / 'visual_assets.jsonl').write_text(''.join(json.dumps(a) + '\n' for a in all_assets))
    table = '<table><tr><th>Page</th><th>Assets</th><th>Dual</th><th>Fast</th><th>Unresolved</th><th>Audit</th></tr>' + ''.join(page_links) + '</table>'
    (args.output / 'report.html').write_text(STYLE + '<header><h1>Gated background-asset shadow run</h1><p>Every resolved asset is retained. The gate controls only dual-mask computation.</p><pre>' + html.escape(json.dumps(totals, indent=2)) + '</pre></header><section>' + table + '</section>')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
