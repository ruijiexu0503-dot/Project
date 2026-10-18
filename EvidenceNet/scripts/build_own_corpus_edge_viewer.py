#!/usr/bin/env python3
"""Render the own-corpus pilot, including incomplete and rejected decisions."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def build(out):
    from run_own_corpus_edges import graph, rows, write, jsonl, digest
    pages,nodes,reading,issues=graph(out)
    decisions=[];semantic=[];aggregates=defaultdict(list)
    for path in sorted((out/'decisions').glob('*.json')):
        d=json.loads(path.read_text());decisions.append(d)
        pair=d['pair']
        if d.get('input_sha256') != digest([nodes[pair['source']],nodes[pair['target']]]):
            raise ValueError(f'Stale edge decision: {path}')
        if not d['valid'] or d['value'].get('status')!='ACCEPT':continue
        for i,r in enumerate(d['value']['relations']):
            a,b=pair['source'],pair['target']
            if r['direction']=='B_TO_A':a,b=b,a
            edge={'id':pair['pair_id']+f'::{i}','source':a,'target':b,'type':r['type'],
                  'family':'semantic','scope':pair['scope'],'status':'MODEL_ACCEPTED_SOURCE_ANCHORED',
                  'decision':r,'pair':pair,'decision_file':str(path),'human_review':'PENDING'}
            for name,nid in [('anchor_a',pair['source']),('anchor_b',pair['target'])]:
                anchor=r[name];endpoint=nodes[nid]
                if anchor['kind']=='TEXT':
                    member=next(m for m in endpoint['members'] if m['kind']=='atom' and anchor['quote'] in m['text'])
                    edge[name+'_provenance']={'node_id':nid,'source_atom_id':member['id'],
                          'char_start':member['text'].index(anchor['quote']),
                          'char_end':member['text'].index(anchor['quote'])+len(anchor['quote'])}
                else:
                    edge[name+'_provenance']={'node_id':nid,'crops':[{'visual_id':m['id'],'crop':m['crop'],
                         'sha256':hashlib.sha256((out/m['crop']).read_bytes()).hexdigest()}
                         for m in endpoint['members'] if m.get('crop')]}
            semantic.append(edge)
            aa,bb=nodes[a]['article_id'],nodes[b]['article_id']
            if aa and bb and aa!=bb and pair['scope'] in {'cross_article','cross_document'}:
                aggregates[(aa,bb,r['type'])].append(edge['id'])
    article_edges=[{'source_article':a,'target_article':b,'type':t,'supporting_edge_ids':ids,
                    'status':'AGGREGATE_OF_MODEL_JUDGMENTS','human_review':'PENDING'}
                   for (a,b,t),ids in sorted(aggregates.items())]
    pairs=rows(out/'candidate_pairs.jsonl') if (out/'candidate_pairs.jsonl').exists() else []
    summary={'pages':len(pages),'nodes':len(nodes),'ownership_valid_pages':sum(
        (out/f"ownership/page_{p['index']:03d}.json").exists() and
        json.loads((out/f"ownership/page_{p['index']:03d}.json").read_text())['valid'] for p in pages),
        'reading_edges':len(reading),'cross_page_reading_edges':sum(e['cross_page'] for e in reading),
        'candidates':len(pairs),'decisions':len(decisions),'decision_statuses':dict(Counter(
             d['value'].get('status') if d['valid'] else 'INVALID' for d in decisions)),
        'semantic_edges':len(semantic),'semantic_scopes':dict(Counter(e['scope'] for e in semantic)),
        'article_edges':len(article_edges),'issues':len(issues),
        'complete':bool(pairs) and len(decisions)==len(pairs),
        'semantic_validation':'model judgments; independent source review pending',
        'production_modified':False}
    jsonl(out/'reading_edges.jsonl',reading);jsonl(out/'semantic_edges.jsonl',semantic)
    jsonl(out/'article_edges.jsonl',article_edges);jsonl(out/'issues.jsonl',issues)
    write(out/'summary.json',summary)
    payload={'pages':pages,'nodes':list(nodes.values()),'reading':reading,'semantic':semantic,
             'article_edges':article_edges,'decisions':decisions,'summary':summary,'issues':issues}
    write(out/'graph_data.json',payload)
    render(out, payload)
    print(json.dumps(summary),flush=True)


def render(out, payload):
    """Render a graph payload with original node members and page assets."""
    html='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>49页 Evidence edges</title>
<style>body{margin:0;background:#101827;color:#eef2ff;font:14px system-ui}header{padding:12px 18px;background:#1e293b}select,button{background:#334155;color:white;padding:6px;border:1px solid #64748b;margin:4px}main{display:grid;grid-template-columns:58% 42%;height:calc(100vh - 130px)}#stage{overflow:auto}aside{overflow:auto;padding:15px;background:#172033}.node{cursor:pointer}.edge{cursor:pointer}.edge:hover{stroke:white!important;stroke-width:5!important}pre{white-space:pre-wrap;word-break:break-word;font:13px system-ui}.card{border:1px solid #475569;margin:10px 0;padding:10px}img{max-width:100%}.page{position:relative}.page img{width:100%;display:block}.box{position:absolute;border:2px solid #f97316;box-sizing:border-box;pointer-events:none}svg{min-width:950px}.muted{color:#94a3b8}</style>
<header><b>自己的49页材料：节点构成与实际 edge</b><div id="summary"></div>
<select id="doc"><option value="">全部文档</option></select><select id="layer"><option value="all">全部边</option><option value="reading_order">阅读顺序 NEXT</option><option value="semantic">语义边</option><option value="cross">跨文章／文档语义</option></select><button id="articles">文章间关系</button><button id="issues">待检查问题</button><button id="decisions">判断记录（包括拒绝／不确定）</button></header>
<main><div id="stage"><svg id="graph"></svg></div><aside id="detail">点击节点查看原文、成员、原图和描述；点击连线查看关系和两端证据。语义边为模型判断，尚待源文复核。</aside></main>
<script>const D=__DATA__;const ns='http://www.w3.org/2000/svg';const byId=Object.fromEntries(D.nodes.map(n=>[n.id,n]));const pageByTask=Object.fromEntries(D.pages.map(p=>[p.task,p]));const $=s=>document.querySelector(s);const detail=$('#detail');function tag(t,text,parent){let e=document.createElement(t);if(text!==undefined)e.textContent=text;if(parent)parent.append(e);return e}function clear(){detail.replaceChildren()}
function nodeCard(n){let c=tag('div',undefined,detail);c.className='card';tag('b',n.id,c);tag('pre',JSON.stringify({article:n.article_id,article_title:n.article_title,assignment:n.assignment_status,flow:n.flow_id,type:n.unit_type},null,2),c);for(let m of n.members){tag('b',m.kind+' '+m.id,c);tag('pre',m.text,c);if(m.crop){let im=tag('img',undefined,c);im.src=m.crop;tag('div','原始 crop；生成描述是未验证的检索提示',c)}}let page=pageByTask[n.task];let wrap=tag('div',undefined,c);wrap.className='page';let im=tag('img',undefined,wrap);im.onload=()=>{for(let m of n.members)for(let b of m.boxes||[]){let box=tag('div',undefined,wrap);box.className='box';Object.assign(box.style,{left:100*b[0]/im.naturalWidth+'%',top:100*b[1]/im.naturalHeight+'%',width:100*(b[2]-b[0])/im.naturalWidth+'%',height:100*(b[3]-b[1])/im.naturalHeight+'%'})}};im.src=page.image}
function edgeCard(e){clear();tag('h3',e.type+' · '+(e.scope||'reading flow'),detail);tag('pre',JSON.stringify(e,null,2),detail);nodeCard(byId[e.source]);nodeCard(byId[e.target])}
function draw(){let doc=$('#doc').value,layer=$('#layer').value;let edges=[...D.reading,...D.semantic].filter(e=>layer==='all'||e.family===layer||layer==='cross'&&['cross_document','cross_article'].includes(e.scope));let ids=new Set(D.nodes.filter(n=>!doc||n.document===doc).map(n=>n.id));edges=edges.filter(e=>ids.has(e.source)||ids.has(e.target));for(let e of edges){ids.add(e.source);ids.add(e.target)}let nodes=D.nodes.filter(n=>ids.has(n.id));let svg=$('#graph');svg.replaceChildren();svg.setAttribute('width','100%');svg.setAttribute('height',Math.max(600,Math.ceil(nodes.length/4)*125));let positions=Object.fromEntries(nodes.map((n,i)=>[n.id,{x:20+i%4*250,y:25+Math.floor(i/4)*125}]));let defs=document.createElementNS(ns,'defs');defs.innerHTML='<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#cbd5e1"/></marker>';svg.append(defs);for(let e of edges){let a=positions[e.source],b=positions[e.target];let line=document.createElementNS(ns,'path');line.setAttribute('d',`M${a.x+110},${a.y+90} Q${a.x+110},${b.y-15} ${b.x+110},${b.y}`);line.setAttribute('fill','none');line.setAttribute('stroke',e.family==='reading_order'?'#60a5fa':e.scope==='cross_document'?'#f472b6':'#34d399');line.setAttribute('stroke-width','2');if(e.direction!=='SYMMETRIC'&&e.decision?.direction!=='SYMMETRIC')line.setAttribute('marker-end','url(#arrow)');line.classList.add('edge');line.onclick=()=>edgeCard(e);let title=document.createElementNS(ns,'title');title.textContent=e.type+' '+(e.scope||'');line.append(title);svg.append(line)}for(let n of nodes){let p=positions[n.id];let g=document.createElementNS(ns,'g');g.classList.add('node');let r=document.createElementNS(ns,'rect');for(let[k,v]of Object.entries({x:p.x,y:p.y,width:220,height:90,rx:8,fill:'#243249',stroke:n.article_id?'#94a3b8':'#f97316'}))r.setAttribute(k,v);g.append(r);for(let[t,dy]of [[n.document.slice(0,27)+' '+n.page,20],[n.label+' · '+n.unit_type,40],[(n.text||'视觉节点').replace(/\s+/g,' ').slice(0,28),65]]){let e=document.createElementNS(ns,'text');e.setAttribute('x',p.x+8);e.setAttribute('y',p.y+dy);e.setAttribute('fill','#eef2ff');e.textContent=t;g.append(e)}g.onclick=()=>{clear();nodeCard(n);let connected=edges.filter(e=>e.source===n.id||e.target===n.id);tag('h3','连接 '+connected.length+' 条',detail);for(let e of connected){let b=tag('button',e.type+' → '+byId[e.source===n.id?e.target:e.source].label,detail);b.onclick=()=>edgeCard(e)}};svg.append(g)}}
for(let doc of [...new Set(D.nodes.map(n=>n.document))].sort()){let o=tag('option',doc,$('#doc'));o.value=doc}$('#summary').textContent=`${D.summary.pages}页 / ${D.summary.nodes}节点 / ${D.summary.reading_edges}阅读边 / ${D.summary.semantic_edges}语义边；判断 ${D.summary.decisions}/${D.summary.candidates}；独立源文复核待完成`;$('#doc').onchange=draw;$('#layer').onchange=draw;$('#articles').onclick=()=>{clear();tag('h3','文章间关系（由节点证据边汇总）',detail);if(!D.article_edges.length)tag('div','尚无已生成的文章间语义关系',detail);for(let e of D.article_edges){tag('pre',JSON.stringify(e,null,2),detail);for(let id of e.supporting_edge_ids){let edge=D.semantic.find(x=>x.id===id);if(edge){let b=tag('button',id,detail);b.onclick=()=>edgeCard(edge)}}}};$('#issues').onclick=()=>{clear();tag('pre',JSON.stringify(D.issues,null,2),detail)};$('#decisions').onclick=()=>{clear();for(let d of D.decisions){let b=tag('button',d.pair.pair_id+' '+(d.valid?d.value.status:'INVALID'),detail);b.onclick=()=>{clear();tag('pre',JSON.stringify(d,null,2),detail);nodeCard(byId[d.pair.source]);nodeCard(byId[d.pair.target])}}};draw();</script></html>'''
    html=html.replace('__DATA__',json.dumps(payload,ensure_ascii=False).replace('</','<\\/'))
    (out/'index.html').write_text(html)
