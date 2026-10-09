#!/usr/bin/env python3
"""Shadow gating study. Cached dual masks are evaluation-only, never gate input.

Consumes already identified assets. This experiment measures avoidable *dual
mask jobs*, not savings from parsing/OCR/asset-identity reconstruction.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader
from pypdf.generic import ContentStream

from build_background_dual_mask_report import HEADER, panel


def load(path):
    return json.loads(Path(path).read_text())


def normalized_split_boundaries(split, source_name):
    """Return internal vertical boundaries in source-page normalized units.

    The split manifest is written in its own render coordinate system.  Audit
    previews may use another width, so raw manifest pixels must never be mixed
    with preview pixels.
    """
    rows = [r for r in split.get('pages', []) if r.get('source_page') == source_name]
    if not rows:
        return []
    source_width = max(float(r['bbox'][2]) for r in rows)
    if source_width <= 0:
        return []
    edges = {float(r['bbox'][0]) for r in rows} | {float(r['bbox'][2]) for r in rows}
    return sorted(edge / source_width for edge in edges if 0 < edge < source_width)


def clip_flags(page, reader):
    """Track whether non-rectangular/text clipping is active at each Do.

    Conservative: a polygon drawn with m/l is considered complex even if it
    might be a rectangle. This reads operators, not rendered masks.
    """
    found = {}
    path_end = {b'n',b'f',b'F',b'f*',b'S',b's',b'B',b'B*',b'b',b'b*'}

    def visit(container, resources, prefix, inherited=False, depth=0):
        if depth>20:
            raise ValueError('Form nesting limit')
        stream=container.get_contents() if hasattr(container,'get_contents') else container
        state={'complex':inherited,'text_render':0};stack=[]
        path_complex=False;rectangles=0;pending=False
        for index,(args,op) in enumerate(ContentStream(stream,reader).operations):
            path=prefix+(index,)
            if op==b'q': stack.append(dict(state))
            elif op==b'Q': state=stack.pop() if stack else {'complex':True,'text_render':0}
            elif op in (b'm',b'l',b'c',b'v',b'y'): path_complex=True
            elif op==b're': rectangles+=1
            elif op in (b'W',b'W*'): pending=True
            elif op in path_end:
                if pending: state['complex'] |= path_complex or rectangles!=1
                path_complex=False;rectangles=0;pending=False
            elif op==b'Tr': state['text_render']=int(args[0])
            elif op==b'ET' and state['text_render']>=4: state['complex']=True
            elif op==b'Do':
                obj=resources['/XObject'][args[0]].get_object()
                if obj.get('/Subtype')=='/Form':
                    visit(obj,obj.get('/Resources',resources),path,state['complex'],depth+1)
                elif obj.get('/Subtype')=='/Image':
                    found[path]=state['complex']
    visit(page,page['/Resources'],())
    return found


def rect_mask(box, width, height, sx=1, sy=1):
    x1,y1,x2,y2=box
    a,b=max(0,int(np.floor(x1*sx))),max(0,int(np.floor(y1*sy)))
    c,d=min(width,int(np.ceil(x2*sx))),min(height,int(np.ceil(y2*sy)))
    out=np.zeros((height,width),dtype=np.uint8)
    if c>a and d>b: out[b:d,a:c]=1
    return out


def quick_support(asset, width, height, pdf_page, flags, cfg):
    """Original image alpha projected with its affine transform, on a small grid.

    PDF clip paths are not rasterized here: complex clips explicitly trigger
    the full path. Rectangular clips can overestimate this cheap support.
    """
    projected=np.zeros((height,width),dtype=bool)
    rectangles=np.zeros_like(projected)
    source_soft=False;nonrect=False
    for member in asset['render_layer_members']:
        sw,sh=asset['image_size']
        rectangles |= rect_mask(member['rendered_bbox_pixels'],width,height,width/sw,height/sh).astype(bool)
        nonrect |= flags.get(tuple(member['invocation_path']),True)
        alpha_path=member.get('alpha_mask_path')
        if alpha_path:
            with Image.open(alpha_path) as im:
                alpha=im.convert('L')
                alpha.thumbnail((512,512))
                arr=np.asarray(alpha)
                source_soft |= float((arr<cfg['alpha_support_threshold']).mean())>=cfg['source_soft_mask_min_missing_fraction']
        else:
            arr=np.full((32,32),255,dtype=np.uint8)
        a,b,c,d,e,f=member['transform'];h,w=arr.shape
        sx,sy=width/pdf_page.rect.width,height/pdf_page.rect.height
        matrix=np.array([[a*sx/w,c*sx/h,e*sx],[b*sy/w,d*sy/h,f*sy]],dtype=np.float64)
        placed=cv2.warpAffine(arr,matrix,(width,height),flags=cv2.INTER_LINEAR,borderValue=0)
        projected |= placed>=cfg['alpha_support_threshold']
    return projected,rectangles,source_soft,nonrect


def assess(features,cfg):
    reasons=[]
    if features['nonrect_clip']: reasons.append('nonrectangular_or_text_clip')
    if features['source_soft_mask']: reasons.append('source_transparency')
    if features['support_missing_fraction']>=cfg['irregular_support_min_missing_fraction']:
        reasons.append('irregular_projected_support')
    if features['crosses_known_boundary']: reasons.append('crosses_recorded_page_boundary')
    if features['confirmed_image_overlaps']: reasons.append('image_support_overlap')
    if (features['supported_text_lines']>=cfg['dense_text_min_lines'] or
        features['supported_text_area_fraction']>=cfg['dense_text_min_area_fraction']):
        reasons.append('dense_text_over_image')
    return {'decision':'DUAL_MASK' if reasons else 'FAST_BBOX', 'reasons':reasons or ['simple_image_or_small_text_overlay']}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--baseline',type=Path,required=True)
    ap.add_argument('--config',type=Path,required=True)
    ap.add_argument('--split-manifest',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    cfg=load(args.config);summary=load(args.baseline/'summary.json')
    assets=[json.loads(s) for s in (args.baseline/'visual_assets.jsonl').read_text().splitlines()]
    data=Path(summary['input_pdf']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=summary['input_sha256']:
        raise ValueError('Source PDF changed since baseline: refuse coordinate comparison')
    document=fitz.open(stream=data,filetype='pdf');reader=PdfReader(io.BytesIO(data))
    split=load(args.split_manifest)
    results=[];page_stats=[];reports=[]
    for number in sorted({a['source_page'] for a in assets}):
        page=document[number-1];flags=clip_flags(reader.pages[number-1],reader)
        selected=[a for a in assets if a['source_page']==number]
        width=cfg['support_grid_width'];height=round(width*page.rect.height/page.rect.width)
        support={};boxes={};meta={}
        for asset in selected:
            aid=asset['asset_id']
            support[aid],boxes[aid],soft,nonrect=quick_support(asset,width,height,page,flags,cfg)
            meta[aid]=(soft,nonrect)
        textlines=[l['bbox'] for b in page.get_text('dict')['blocks'] if b.get('type')==0 for l in b.get('lines',[])]
        textmasks=[rect_mask(b,width,height,width/page.rect.width,height/page.rect.height).astype(bool) for b in textlines]
        source_name=f'page_{number:06d}'
        boundaries=normalized_split_boundaries(split,source_name)
        page_rows=[]
        for asset in selected:
            aid=asset['asset_id'];supp=support[aid];box=boxes[aid];pixels=int(supp.sum())
            bbox_pairs=[];support_pairs=[]
            for other in selected:
                bid=other['asset_id']
                if bid==aid:continue
                if np.any(box & boxes[bid]):bbox_pairs.append(bid)
                overlap=int((supp&support[bid]).sum())
                fraction=overlap/max(1,min(pixels,int(support[bid].sum())))
                if overlap and fraction>=cfg['meaningful_image_overlap_fraction']:
                    support_pairs.append({'asset_id':bid,'fraction':fraction})
            raw_lines=0;supported=0;union=np.zeros_like(supp)
            for tm in textmasks:
                raw_lines+=bool(np.any(box&tm))
                coverage=int((tm&supp).sum())/max(1,int(tm.sum()))
                if coverage>=cfg['meaningful_text_line_coverage']:
                    supported+=1;union |= tm&supp
            crossing=[]
            for edge in boundaries:
                cut=round(edge*width)
                fraction=min(int(supp[:,:cut].sum()),int(supp[:,cut:].sum()))/max(1,pixels)
                if fraction>=cfg['boundary_min_side_fraction']:crossing.append(edge)
            f={'nonrect_clip':meta[aid][1],'source_soft_mask':meta[aid][0],
               'support_missing_fraction':max(0,1-pixels/max(1,int(box.sum()))),
               'crosses_known_boundary':crossing,'bbox_image_overlaps':bbox_pairs,
               'confirmed_image_overlaps':support_pairs,'bbox_text_lines':raw_lines,
               'supported_text_lines':supported,'supported_text_area_fraction':int(union.sum())/max(1,pixels)}
            row={'asset_id':aid,'page':number,'xrefs':asset['xrefs'],'features':f,
                 'bbox_only_image_trigger':bool(bbox_pairs),'bbox_only_image_or_text_trigger':bool(bbox_pairs or raw_lines),
                 **assess(f,cfg)}
            # Predictions are complete. Only now open the expensive reference
            # masks to check which complex geometries the fast path would skip.
            if asset.get('layer_mask'):
                with Image.open(args.baseline/asset['layer_mask']) as im:
                    truth=np.asarray(im)>=cfg['alpha_support_threshold']
                ys,xs=np.nonzero(truth)
                envelope=(int(xs.max()-xs.min()+1)*int(ys.max()-ys.min()+1)) if len(xs) else 0
                missing=1-int(truth.sum())/max(1,envelope)
                row['reference_mask_missing_fraction']=missing
                row['reference_irregular']=missing>=cfg['baseline_irregular_min_missing_fraction']
                row['fast_path_reference_irregular']=row['decision']=='FAST_BBOX' and row['reference_irregular']
            else:
                row['reference_irregular']=None;row['fast_path_reference_irregular']=None
            results.append(row);page_rows.append(row)
        stat={'page':number,'assets':len(page_rows),'bbox_image_only_triggered':sum(r['bbox_only_image_trigger'] for r in page_rows),
              'bbox_image_or_text_triggered':sum(r['bbox_only_image_or_text_trigger'] for r in page_rows),
              'dual_mask':sum(r['decision']=='DUAL_MASK' for r in page_rows),
              'fast_path':sum(r['decision']=='FAST_BBOX' for r in page_rows),
              'fast_path_reference_irregular':sum(bool(r['fast_path_reference_irregular']) for r in page_rows)}
        page_stats.append(stat)
        folder=args.baseline/f'page_{number:04d}'
        base=Image.open(folder/f'{selected[0]["asset_id"]}_original_view.png').convert('RGB');preview=base.copy();draw=ImageDraw.Draw(preview)
        for asset,row in zip(selected,page_rows):
            color=(20,160,90) if row['decision']=='FAST_BBOX' else (235,140,0)
            for i,member in enumerate(asset['render_layer_members']):
                bbox=member['rendered_bbox_pixels']
                draw.rectangle(bbox,outline=color,width=3)
                if i==0:draw.text((max(0,bbox[0]+3),max(0,bbox[1]-14)),row['asset_id'].split('_')[-1]+' '+row['decision'],fill=color,stroke_width=1,stroke_fill='white')
        preview.save(args.output/f'page_{number:04d}.png')
        card=panel(f'Page {number}: green = fast path; orange = dual mask',[('Original',base),('Gate',preview)])
        card+='<section><pre>'+__import__('html').escape(json.dumps({'counts':stat,'assets':page_rows},indent=2))+'</pre></section>'
        (args.output/f'page_{number:04d}.html').write_text(HEADER+card)
        reports.append(card)
    totals={key:sum(s[key] for s in page_stats) for key in ['assets','bbox_image_only_triggered','bbox_image_or_text_triggered','dual_mask','fast_path','fast_path_reference_irregular']}
    sweeps=[]
    for min_lines in [4,8,12]:
        for min_area in [.03,.08,.15]:
            c={**cfg,'dense_text_min_lines':min_lines,'dense_text_min_area_fraction':min_area}
            decisions=[assess(r['features'],c)['decision'] for r in results]
            sweeps.append({'min_lines':min_lines,'min_area':min_area,'dual_mask':decisions.count('DUAL_MASK'),
                           'fast_path_reference_irregular':sum(d=='FAST_BBOX' and bool(r['reference_irregular']) for r,d in zip(results,decisions))})
    out={'experiment':cfg['version'],'baseline':str(args.baseline),'source_sha256':summary['input_sha256'],
         'config':cfg,'pages':page_stats,'totals':totals,'text_threshold_sensitivity':sweeps,
         'avoided_mask_job_fraction':totals['fast_path']/max(1,totals['assets']),
         'evaluation_scope':'cached assets; reference masks evaluated only after gate decisions; not human GT or measured end-to-end speedup',
         'production_modified':False}
    (args.output/'summary.json').write_text(json.dumps(out,indent=2))
    (args.output/'gate_decisions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in results))
    intro='<header><h1>Background complexity gate</h1><p>Green: retain asset with bbox/overlay metadata. Orange: request full dual-mask processing. Boxes are original render-layer members.</p></header>'
    (args.output/'report.html').write_text(HEADER+intro+''.join(reports))
    print(json.dumps(out,indent=2))


if __name__=='__main__':main()
