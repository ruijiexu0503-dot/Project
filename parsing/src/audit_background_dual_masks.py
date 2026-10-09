#!/usr/bin/env python3
"""Isolated PDF background-layer audit. Never edit the source PDF.

Keep PDF transforms, clip paths and soft masks; suppress unrelated painting
only for the layer view. Differential renders measure response, not semantic
segmentation. No contour filling or image inpainting is performed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageFilter
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, DictionaryObject, NameObject, NumberObject, DecodedStreamObject

from audit_pdf_object_layers import extract_object, smask_xref
from audit_pdf_rectangular_visual_bundles_document import union_find_groups


def image_occurrences(page, pdf):
    images, warnings = [], []

    def visit(container, resources, prefix, depth=0):
        if depth > 20:
            raise ValueError('Form nesting exceeds audit limit')
        stream = container.get_contents() if hasattr(container, 'get_contents') else container
        if stream is None:
            return
        for i, (args, op) in enumerate(ContentStream(stream, pdf).operations):
            path = prefix + (i,)
            if op == b'INLINE IMAGE':
                warnings.append({'path': path, 'reason': 'inline image retained as page context, not a recoverable target'})
            if op == b'Tr' and int(args[0]) >= 4:
                warnings.append({'path': path, 'reason': 'text clipping: isolated layer unsupported'})
            if op != b'Do':
                continue
            ref = resources.get('/XObject', {}).get(args[0])
            if ref is None:
                raise ValueError(f'Missing XObject at {path}')
            obj = ref.get_object()
            if obj.get('/Subtype') == '/Form':
                visit(obj, obj.get('/Resources', resources), path, depth + 1)
            elif obj.get('/Subtype') == '/Image':
                images.append({'invocation_path': list(path), 'xref': ref.idnum,
                               'unsupported': bool(obj.get('/ImageMask')) or '/Mask' in obj,
                               'soft_mask': '/SMask' in obj})
    visit(page, page['/Resources'], ())
    return images, warnings


def altered_pdf(pdf_bytes, page_index, targets, layer, tone=None):
    """Rewrite per-invocation streams, retaining graphics-state and clip ops.

    Each Form invocation gets its own rewritten copy, so a repeated xref can
    be targeted without also changing its other placements.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    page = writer.pages[0]
    targets = {tuple(path) for path in targets}

    def rewrite(container, resources, prefix):
        source = container.get_contents() if hasattr(container, 'get_contents') else container
        resources = DictionaryObject(dict(resources))
        xobjects = DictionaryObject(dict(resources.get('/XObject', {})))
        resources[NameObject('/XObject')] = xobjects
        out = []
        for i, (args, op) in enumerate(ContentStream(source, writer).operations):
            path = prefix + (i,)
            if op == b'Do':
                obj = xobjects[args[0]].get_object()
                subtype = obj.get('/Subtype')
                if subtype == '/Form':
                    # Form state is scoped; unrelated forms cannot change the
                    # enclosing clip and can be omitted in the isolated view.
                    contains = any(t[:len(path)] == path for t in targets)
                    if not contains:
                        if not layer:
                            out.append((args, op))
                        continue
                    child, child_resources = rewrite(obj, obj.get('/Resources', resources), path)
                    form = DecodedStreamObject()
                    for key, value in obj.items():
                        if key not in ('/Length', '/Filter', '/DecodeParms', '/Resources'):
                            form[key] = value
                    form.set_data(child.get_data())
                    form[NameObject('/Resources')] = child_resources
                    name = NameObject(f'/AuditForm{i}')
                    xobjects[name] = writer._add_object(form)
                    out.append(([name], b'Do'))
                elif subtype == '/Image':
                    if path not in targets:
                        if not layer:
                            out.append((args, op))
                        continue
                    if tone is None:
                        out.append((args, op))
                        continue
                    replacement = DecodedStreamObject()
                    width, height = int(obj['/Width']), int(obj['/Height'])
                    replacement.update({NameObject('/Type'): NameObject('/XObject'),
                                        NameObject('/Subtype'): NameObject('/Image'),
                                        NameObject('/Width'): NumberObject(width),
                                        NameObject('/Height'): NumberObject(height),
                                        NameObject('/BitsPerComponent'): NumberObject(8),
                                        NameObject('/ColorSpace'): NameObject('/DeviceRGB')})
                    # Renderer applies the original SMask, transform and clip.
                    if '/SMask' in obj:
                        replacement[NameObject('/SMask')] = obj.raw_get('/SMask')
                    replacement.set_data(bytes([tone]) * (width * height * 3))
                    name = NameObject(f'/AuditImage{i}')
                    xobjects[name] = writer._add_object(replacement)
                    out.append(([name], b'Do'))
                else:
                    raise ValueError(f'Unsupported XObject subtype {subtype}')
            elif layer and op in (b'f', b'F', b'f*', b'S', b's', b'B', b'B*', b'b', b'b*'):
                # End the path so W/W* still takes effect, without painting.
                out.append(([], b'n'))
            elif layer and op in (b'Tj', b'TJ', b"'", b'"', b'sh', b'INLINE IMAGE'):
                continue
            else:
                out.append((args, op))
        result = ContentStream(None, writer)
        result.operations = out
        return result, resources

    stream, resources = rewrite(page, page['/Resources'], ())
    page[NameObject('/Contents')] = writer._add_object(stream)
    page[NameObject('/Resources')] = resources
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def render(pdf_bytes, page_index, width):
    with fitz.open(stream=pdf_bytes, filetype='pdf') as doc:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(width / page.rect.width, width / page.rect.width), alpha=False)
        return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


def response_mask(pdf_bytes, page_index, targets, layer, width):
    images = [np.asarray(render(altered_pdf(pdf_bytes, page_index, targets, layer, tone), 0, width), dtype=np.int16)
              for tone in (0, 255)]
    return Image.fromarray(np.max(np.abs(images[1] - images[0]), axis=2).astype(np.uint8))


def overlay(base, mask, color):
    result = base.convert('RGBA')
    tint = Image.new('RGBA', base.size, color + (0,))
    tint.putalpha(mask.point(lambda v: round(v * .3)))
    result = Image.alpha_composite(result, tint).convert('RGB')
    # Display a contour without filling holes. The grayscale PNG is canonical.
    edge = mask.point(lambda v: 255 if v >= 24 else 0).filter(ImageFilter.FIND_EDGES)
    result.paste(Image.new('RGB', base.size, color), (0, 0), edge)
    return result


def embedded(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', type=Path, required=True)
    ap.add_argument('--pages', type=int, nargs='+', required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--width', type=int, default=1400)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = args.pdf.read_bytes()
    reader = PdfReader(io.BytesIO(data))
    document = fitz.open(stream=data, filetype='pdf')
    all_rows, cards, page_summaries = [], [], []
    palette = [(0, 175, 200), (245, 155, 0), (230, 60, 120), (80, 100, 230)]
    for number in args.pages:
        base = render(data, number-1, args.width)
        folder = args.output / f'page_{number:04d}'
        folder.mkdir(exist_ok=True)
        occurrences, warnings = image_occurrences(reader.pages[number-1], reader)
        infos = document[number-1].get_image_info(xrefs=True)
        records = []
        for i, occurrence in enumerate(occurrences):
            infos_for_xref = [v for v in infos if v['xref'] == occurrence['xref']]
            if occurrence['unsupported'] or len(infos_for_xref) != 1:
                warnings.append({**occurrence, 'reason': 'unsupported image mask or non-unique placement for identity grouping'})
                continue
            info = infos_for_xref[0]
            sx = base.width / document[number-1].rect.width
            sy = base.height / document[number-1].rect.height
            bbox = list(info['bbox'])
            record = {**occurrence, 'rendered_bbox_pixels': [bbox[0]*sx,bbox[1]*sy,bbox[2]*sx,bbox[3]*sy],
                      'smask_xref': smask_xref(document, occurrence['xref']), 'transform': list(info['transform'])}
            record.update(extract_object(document, occurrence['xref'], folder / 'objects' / f'{i}.png'))
            records.append(record)
        # Existing grouping is reused only for axis-aligned placements. Other
        # transforms still get renderer-derived masks, but remain separate.
        axis = [r for r in records if abs(r['transform'][1]) < 1e-5 and abs(r['transform'][2]) < 1e-5
                and r['transform'][0] > 0 and r['transform'][3] > 0]
        groups, comparisons = union_find_groups(axis)
        groups += [[r] for r in records if r not in axis]
        for index, group in enumerate(groups):
            asset_id = f'page_{number:04d}_asset_{index+1:02d}'
            targets = [r['invocation_path'] for r in group]
            visible = response_mask(data, number-1, targets, False, args.width)
            unsupported_clip = any('text clipping' in w['reason'] for w in warnings)
            layer = None if unsupported_clip else response_mask(data, number-1, targets, True, args.width)
            visible.save(folder / f'{asset_id}_visible.png')
            if layer is not None:
                layer.save(folder / f'{asset_id}_layer.png')
            xrefs = [r['xref'] for r in group]
            row = {'asset_id':asset_id, 'source_page': number, 'xrefs':xrefs,
                   'invocation_paths':targets, 'render_layer_members':group,
                   'mask_coordinates':'source PDF page rendered pixels', 'image_size':base.size,
                   'mask_semantics':'grayscale black/white render response; threshold 24 for display only',
                   'layer_mask_status':'unresolved_text_clipping' if layer is None else 'renderer_derived_response',
                   'visible_mask': f'page_{number:04d}/{asset_id}_visible.png',
                   'layer_mask':None if layer is None else f'page_{number:04d}/{asset_id}_layer.png',
                   'visible_pixels_ge24':int((np.asarray(visible)>=24).sum()),
                   'layer_pixels_ge24':None if layer is None else int((np.asarray(layer)>=24).sum()),
                   'merge_evidence':[r for r in comparisons if r['merge'] and set(r['xrefs']) <= set(xrefs)],
                   'limitations':['Non-normal blending and group opacity can affect response; this is not an exact opacity estimate.',
                                  'Unproven image identity remains separate; no hidden pixels are generated.']}
            if layer is not None:
                row['layer_minus_visible_pixels_ge24'] = int(((np.asarray(layer)>=24)&(np.asarray(visible)<24)).sum())
                row['visible_outside_layer_pixels_ge24'] = int(((np.asarray(visible)>=24)&(np.asarray(layer)<24)).sum())
            all_rows.append(row)
            color = palette[index % len(palette)]
            views = [('Original',base),('Visible',overlay(base,visible,color))]
            if layer is not None:
                views += [('Layer',overlay(base,layer,color))]
                isolated = render(altered_pdf(data,number-1,targets,True,None),0,args.width)
                views += [('Image layer',isolated)]
            for label, im in views:
                im.save(folder / f'{asset_id}_{label.lower().replace(" ", "_")}_view.png')
            tabs = ''.join(f'<button onclick="show(this, {j})">{label}</button>' for j,(label,_) in enumerate(views))
            pictures = ''.join(f'<img class="view" style="display:{"block" if j==1 else "none"}" src="{embedded(im)}">'
                               for j,(_,im) in enumerate(views))
            cards.append(f'<section><h2>{asset_id} · xrefs {xrefs}</h2>{tabs}{pictures}'
                         f'<p>Visible pixels: {row["visible_pixels_ge24"]}; layer pixels: {row["layer_pixels_ge24"]}.</p>'
                         f'<details><summary>Provenance</summary><pre>{html.escape(json.dumps(row,indent=2))}</pre></details></section>')
            print(f'{asset_id}: xrefs={xrefs} visible={row["visible_pixels_ge24"]} layer={row["layer_pixels_ge24"]}',flush=True)
        page_summaries.append({'page':number,'image_occurrences':len(occurrences),'assets':len(groups),'warnings':warnings})
    summary={'experiment':'background_dual_masks_v1','input_pdf':str(args.pdf.resolve()),
             'input_sha256':hashlib.sha256(data).hexdigest(),'pages':page_summaries,'assets':len(all_rows),
             'production_modified':False,'hole_filling':False,'gpu_used':False}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    (args.output/'visual_assets.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in all_rows))
    report='''<!doctype html><meta charset="utf-8"><title>Background dual mask audit</title>
<style>body{font:16px system-ui;background:#eef1f5;margin:24px}section{background:white;padding:20px;margin:24px auto;max-width:1400px}img{width:100%}button{padding:10px;margin:4px}pre{white-space:pre-wrap} </style>
<h1>Background image layers and visible regions</h1>
<p>Original: source page. Visible: contribution after occlusion. Layer: isolated paint response with original clips and soft masks. Image layer: source colours with unrelated paint suppressed. Masks are estimates from render response; no hole filling.</p>
<script>function show(b,n){b.parentNode.querySelectorAll('.view').forEach((x,i)=>x.style.display=i===n?'block':'none')}</script>'''
    (args.output/'report.html').write_text(report+''.join(cards))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
