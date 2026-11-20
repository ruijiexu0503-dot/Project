"""Comparable text/object overlays using saved results; no new inference."""
import base64
import html
import io
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
DEST = OUT / 'poster_text_object_comparison_v1'


def rows(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    current = json.loads((OUT/'qwen_text_first_poster_fullpage_v2/result.json').read_text())
    free = json.loads((OUT/'qwen_text_first_poster_v1/result.json').read_text())
    ocr = rows(OUT/'poster_all_layers_v1/str_text.jsonl')
    catalog = {r['id']:r for r in rows(OUT/'poster_all_layers_v1/sam_visual_candidates.jsonl')}
    baseline = rows(OUT/'poster_str_sam_v1/sam_visual_candidates.jsonl')
    groups = current['prediction']['groups']
    width, height = current['poster_size']
    im = Image.open(current['source']).convert('RGB'); im.thumbnail((2000,2000))
    buf = io.BytesIO(); im.save(buf,format='JPEG',quality=90)
    src = 'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()
    methods = [
      ('A','最初：STR＋SAM，无 Qwen','STR 检测文字，SAM 独立生成视觉候选，按文字重叠等规则过滤。没有文字–object 语义对应；颜色仅区分候选。',None,[(r['id'],r['bbox'],i) for i,r in enumerate(baseline)]),
      ('B','中间实验：Qwen 自由 bbox（仅日冕局部）','Qwen 根据 OCR 和 JPEG 判断对应关系并直接输出 bbox。这里补画全页 OCR 作参照，不代表该实验处理过全部文字。',free['prediction']['groups'], [('G'+str(i+1),g['object_bbox_px'],i) for i,g in enumerate(free['prediction']['groups']) if g.get('object_bbox_px')]),
      ('C','Qwen 选候选：原始语义选择','按 OCR 排序分批输入，Qwen 从 SAM 候选中选 ID。此层只展示模型选择，不含邻近扩展。',groups, [('G'+str(i+1)+' '+cid,catalog[cid]['bbox'],i) for i,g in enumerate(groups) for cid in g.get('visual_candidate_ids',[]) if cid in catalog]),
      ('D','选候选＋启发式邻近扩展','在 C 后根据描述关键词和候选距离扩展 geometry。是代码规则，不是 Qwen 自主识别；可能把邻近物体合入。',groups, [('G'+str(i+1)+' '+cid,catalog[cid]['bbox'],i) for i,g in enumerate(groups) for cid in g.get('geometry_candidate_ids',[]) if cid in catalog]),
      ('E','扩展后合并 bbox','使用已保存的 merged_geometry_bboxes：同组候选重叠或接近时合并外接框。矩形可能包含空白、文字；跨组不自动合并。本页真正画出合并框。',groups, [('G'+str(i+1)+' merged',b,i) for i,g in enumerate(groups) for b in g.get('merged_geometry_bboxes',[])]),
    ]
    panels=[]; stats=[]
    for key,title,desc,gs,objects in methods:
        membership={}
        for i,g in enumerate(gs or []):
            for tid in g.get('text_ids',[]): membership.setdefault(tid,[]).append(i)
        def color(i): return f'hsl({(i*137.508)%360:.2f},90%,65%)'
        def rect(box,cls,col,label):
            x,y,x2,y2=box
            return f'<rect class="{cls}" x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" stroke="{col}"><title>{html.escape(label)}</title></rect>'
        svg=f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{title}"><image width="{width}" height="{height}" href="{src}"/>'
        for r in ocr:
            ids=membership.get(r['id'],[])
            svg+=rect(r['bbox'],'txt',color(ids[0]) if ids else '#cccccc',r['id']+' '+r['text']+' | '+(', '.join('G'+str(i+1) for i in ids) or '未关联/仅 OCR'))
        for label,box,i in objects: svg+=rect(box,'obj',color(i),label)
        svg+='</svg>'
        detail=''
        for i,g in enumerate(gs or []):
            texts=[r['text'] for r in ocr if r['id'] in g.get('text_ids',[])]
            detail+=f'<li style="border-left:6px solid {color(i)}"><b>G{i+1}</b> '+html.escape(' / '.join(texts))+' → '+html.escape(g.get('object_description',''))+' ('+html.escape(g.get('object_status',''))+')</li>'
        panels.append(f'<article data-method="{key}"><h2>{title}</h2><p>{desc}</p><p>文字框 {len(ocr)}；object 框条目 {len(objects)}（含重复引用）；被分组引用的 OCR 区域 {len(membership)}。</p><div class="viewport">{svg}</div><details><summary>文字–object 对应明细</summary><ul>{detail or "原始基线没有语义配对。"}</ul></details></article>')
        stats.append({'method':key,'text_boxes':len(ocr),'object_box_entries':len(objects),'grouped_text_regions':len(membership)})
    page='''<!doctype html><meta charset="utf-8"><title>文字框与 object 框：方案对比</title>
<style>body{font:16px system-ui;margin:20px;background:#eef1f5;color:#182230}h1{font-size:26px}header,article,section{background:white;border-radius:10px;padding:18px;margin-bottom:16px}nav{position:sticky;top:0;background:#fff;padding:14px;z-index:2;border:1px solid #bbb}label{margin-right:14px}main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{min-width:0}article h2{font-size:20px}.viewport{overflow:auto;max-height:85vh;background:#222}svg{display:block;width:100%;height:auto}rect{fill:transparent;vector-effect:non-scaling-stroke}rect.txt{stroke-width:1.5;stroke-dasharray:5 3}rect.obj{stroke-width:3}rect:hover{fill:#fff3;stroke-width:5}body.no-text .txt,body.no-object .obj{display:none}li{margin:10px 0;padding-left:10px}pre{white-space:pre-wrap}@media(max-width:900px){main{grid-template-columns:1fr}}</style>
<header><h1>同一海报：文字框＋object 框对比</h1><p>虚线细框＝文字，实线粗框＝object。关联文字使用对应组颜色，灰色表示未关联（不等于未检测）。鼠标停在框上可查看 OCR 原文、ID 或 object 组号；一段文字属于多组时以第一组着色，悬停显示全部组号。</p><p>所有视图都补画同一套 91 个 OCR 框，以便比较。C／D／E 是同一次推理的不同处理阶段，不是三次独立模型实验。重复框可能重叠，框数不代表独立对象数或准确率。</p></header>
<nav><label><input type="checkbox" id="text" checked>文字框</label><label><input type="checkbox" id="object" checked>object 框</label><label>放大 <input id="zoom" type="range" min="100" max="350" value="100" step="25"></label><span id="choices"></span></nav><main>'''+''.join(panels)+'''</main><section><h2>整图理解实验：另一个层面</h2><p>直接给 Qwen JPEG，分别自由描述与追问曲线、刻度、背景。能解释部分全局语义，但没有生成 object 框，所以不能用其他方法的框冒充定位结果。背景、弥散区域和温标也可能承载信息，并非所有信息都应压成独立 object。</p><a href="../qwen_poster_understanding_v1/report.html">阅读 Qwen 两次完整描述及错误核查</a></section><section><h2>已知问题</h2><p>当前仍有星系团、回力棒星云等误关联；文字漏分组和 OCR 错字尚未解决。合并框只改变几何显示，不修复语义。原来的报告虽保存合并坐标，overlay 实际仍画的是未合并候选；本页 E 才显示合并后的框。</p></section>
<script>for(const kind of ['text','object'])document.getElementById(kind).onchange=e=>document.body.classList.toggle('no-'+kind,!e.target.checked);document.getElementById('zoom').oninput=e=>document.querySelectorAll('svg').forEach(s=>s.style.width=e.target.value+'%');document.querySelectorAll('article').forEach(a=>{const l=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.checked=true;c.onchange=()=>a.style.display=c.checked?'':'none';l.append(c,document.createTextNode(a.dataset.method));document.getElementById('choices').append(l)});</script>'''
    (DEST/'report.html').write_text(page)
    (DEST/'summary.json').write_text(json.dumps(stats,indent=2))
    print(json.dumps(stats));print(DEST/'report.html')


if __name__=='__main__':main()
