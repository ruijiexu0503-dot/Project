#!/usr/bin/env python3
"""Build portable per-page reports from existing dual-mask audit artifacts."""
import argparse
import base64
import html
import io
import json
from pathlib import Path

from PIL import Image
from audit_background_dual_masks import overlay


def embedded(image):
    # Compact presentation previews only. Canonical masks remain lossless PNG.
    buffer=io.BytesIO()
    image.convert('RGB').save(buffer,format='JPEG',quality=88,subsampling=0)
    return 'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()


HEADER='''<!doctype html><meta charset="utf-8"><title>Background mask audit</title>
<style>body{font:16px system-ui;background:#eef1f5;margin:20px}section,header{background:white;padding:18px;margin:16px auto;max-width:1400px}img{width:100%}button{padding:10px;margin:5px;cursor:pointer}pre{white-space:pre-wrap}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}</style>
<script>function show(b,n){b.parentNode.querySelectorAll(':scope > img').forEach((x,i)=>x.style.display=i===n?'block':'none')}</script>
<header><h1>Background image audit · 图层与可见范围</h1>
<p>Original 原页；Visible 被其他内容遮挡后的可见范围；Layer 保留裁剪与透明度的图层范围；Image layer 单独显示图片内容。</p>
<p>同一颜色代表同一个 asset；背景文字和独立插图可以与其重叠。轮廓是渲染估计，没有填洞或生成隐藏像素。</p></header>'''


def panel(title,views):
    buttons=''.join(f'<button onclick="show(this,{i})">{html.escape(name)}</button>' for i,(name,_) in enumerate(views))
    images=''.join(f'<img alt="{html.escape(name)}" style="display:{"block" if i==1 else "none"}" src="{embedded(im)}">' for i,(name,im) in enumerate(views))
    return f'<section><h2>{html.escape(title)}</h2>{buttons}{images}</section>'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);args=ap.parse_args()
    rows=[json.loads(s) for s in (args.output/'visual_assets.jsonl').read_text().splitlines()]
    palette=[(0,175,200),(245,155,0),(230,60,120),(80,100,230)]
    pages=sorted({r['source_page'] for r in rows});all_cards=[]
    for page in pages:
        selected=[r for r in rows if r['source_page']==page]
        folder=args.output/f'page_{page:04d}'
        base=Image.open(folder/f'{selected[0]["asset_id"]}_original_view.png').convert('RGB')
        combined_visible,combined_layer=base.copy(),base.copy()
        legend=[]
        for i,row in enumerate(selected):
            color=palette[i%len(palette)]
            with Image.open(args.output/row['visible_mask']) as mask:
                combined_visible=overlay(combined_visible,mask.convert('L'),color)
            if row['layer_mask']:
                with Image.open(args.output/row['layer_mask']) as mask:
                    combined_layer=overlay(combined_layer,mask.convert('L'),color)
            legend.append(f'<tr><td style="color:rgb{color}">{row["asset_id"]}</td><td>{row["xrefs"]}</td>'
                          f'<td>{row["layer_pixels_ge24"]}</td><td>{row["visible_pixels_ge24"]}</td></tr>')
        card=panel(f'PDF page {page} · all assets', [('Original',base),('Visible',combined_visible),('Layer',combined_layer)])
        card+='<section><table><tr><th>Asset / colour</th><th>PDF xrefs</th><th>Layer pixels</th><th>Visible pixels</th></tr>'+''.join(legend)+'</table></section>'
        combined_visible.save(folder/'overview_visible.png');combined_layer.save(folder/'overview_layer.png')
        for row in selected:
            views=[]
            for label in ['Original','Visible','Layer','Image layer']:
                path=folder/f'{row["asset_id"]}_{label.lower().replace(" ","_")}_view.png'
                if path.exists():
                    with Image.open(path) as im: views.append((label,im.convert('RGB')))
            card+=panel(row['asset_id'],views)
        (args.output/f'page_{page:04d}.html').write_text(HEADER+card)
        all_cards.append(card)
    links='<section>'+ ' · '.join(f'<a href="page_{p:04d}.html">Page {p}</a>' for p in pages)+'</section>'
    (args.output/'report.html').write_text(HEADER+links+''.join(all_cards))
    print(json.dumps({'pages':pages,'portable_html':True}))


if __name__=='__main__': main()
