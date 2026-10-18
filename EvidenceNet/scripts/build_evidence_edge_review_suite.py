#!/usr/bin/env python3
"""Package source-reviewed reusable edge cases and audit live accepted snapshots."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

from run_node_context_edges import ROOT, read, rows, write, jsonl, sha

DEFAULT=ROOT/'data/benchmarks/evidence_edges_v1_20261014'
TRAFFIC=ROOT/'EvidenceNet/output/paper_relevance_urban_traffic_20261013/graph'
EXPANDED=ROOT/'EvidenceNet/output/article_bridge_expanded_v5_20261012'
DIAGNOSTIC=ROOT/'EvidenceNet/output/subject_gate_diagnostic_v1_20261014'
HIERARCHICAL=ROOT/'EvidenceNet/output/hierarchical_edge_retrieval_v1_20261014'
SOURCES={'traffic':TRAFFIC,'expanded':EXPANDED}
PAGE_OVERRIDES={('CERNCourier2025JanFeb-digitaledition','page_0017'):9}


def load_cases(folder):
    spec=runpy.run_path(str(folder/'curation_specs.py'))
    source_nodes={key:{n['id']:n for n in rows(path/'units.jsonl')} for key,path in SOURCES.items()}
    result=[]
    for c in spec['CASES']:
        c=dict(c);c['suite_case_id']=c.pop('case_id')
        ids=[]
        for side in ['A','B']:
            source,nid,mid=c[side];node=source_nodes[source][nid]
            member=next(m for m in node['members'] if m['id']==mid and m['kind']=='atom')
            c[side]={'source_collection':source,'node_id':nid,'document':node['document'],'page':node['page'],
                'original_pdf_page':PAGE_OVERRIDES.get((node['document'],node['page']),int(str(node['page']).replace('page_',''))),
                'article_id':node.get('article_id'),'primary_anchor':{'member_id':mid,'char_start':0,
                    'char_end':len(member['text']),'quote':member['text'],'member_sha256':hashlib.sha256(member['text'].encode()).hexdigest()}}
            ids.append(nid)
        if ids[0]==ids[1]:raise ValueError('same_node_case:'+c['suite_case_id'])
        c['case_id']='EDGE_'+hashlib.sha256(json.dumps([c['relation'],*ids]).encode()).hexdigest()[:16]
        c['scope']='cross_document' if c['A']['document']!=c['B']['document'] else 'same_document'
        c['reviewer']='assistant_original_source_review_not_independent_expert'
        c['negative_scope']='Only the requested relation is judged; other relations are not excluded.'
        c['calibration_only']=c['relation']=='SHARED_PROJECT_NAVIGATION'
        result.append(c)
    if len({c['case_id'] for c in result})!=len(result):raise ValueError('duplicate_case_id')
    return result,source_nodes,spec['AUDITS']


def structural_node_review(node,policy,base):
    flags=[]
    allowed={(m['kind'],m['member_id']) for m in policy['members'] if m['eligible']}
    atom=[m for m in node['members'] if m['kind']=='atom' and ('atom',m['id']) in allowed]
    visual=[m for m in node['members'] if m['kind']=='visual' and ('visual',m['id']) in allowed]
    if not allowed:flags.append('NO_ELIGIBLE_EVIDENCE')
    if node.get('assignment_status') in {'PAGE_LOCAL_ONLY','UNRESOLVED'} or not node.get('article_id'):
        flags.append('ARTICLE_ASSIGNMENT_NOT_CONFIRMED')
    if (node['document'],node['page']) in PAGE_OVERRIDES:flags.append('LEGACY_PAGE_LABEL_DIFFERS_FROM_PDF_PAGE')
    for m in node['members']:
        if m.get('role') in {'foot','footer','header','watermark','reference','catalogue'} and (m['kind'],m['id']) in allowed:
            flags.append('METADATA_ELIGIBLE_CONFLICT')
        if m['kind']=='visual' and (not m.get('crop') or not (base/m['crop']).is_file()):flags.append('MISSING_ORIGINAL_VISUAL')
    if atom and not visual:
        text=' '.join(m['text'] for m in atom)
        words=re.findall(r'\b\w+\b',re.sub(r'<[^>]+>',' ',text))
        if len(words)<8 and not any(m.get('role')=='equ' for m in atom):flags.append('SHORT_CONTEXT_FRAGMENT')
        if re.search(r'^\s*(?:\$.*?\$\s*)?(?:Download link|https?://)',text,re.I):flags.append('LINK_ONLY_NOT_SUBSTANTIVE_EVIDENCE')
        if text[:1].islower() and not any(m.get('role')=='equ' for m in atom):flags.append('POSSIBLE_SENTENCE_CONTINUATION')
    if any('<table' in m['text'].lower() for m in atom):flags.append('TABLE_HEADERS_ROWS_UNITS_REQUIRE_REVIEW')
    return {'node_id':node['id'],'document':node['document'],'page':node['page'],'flags':sorted(set(flags)),
        'eligible':policy['eligible'],'status':'STRUCTURAL_CHECK_ONLY_SEMANTIC_MEANING_NOT_AUTOMATICALLY_VERIFIED'}


def render_original_pages(folder,pdfmap,pages):
    jobs=[]
    for doc,page in sorted(pages):
        number=PAGE_OVERRIDES.get((doc,page),int(str(page).replace('page_','')))
        target=folder/'assets/pages'/f'{doc}_page_{number:04d}.jpg'
        source=TRAFFIC/'assets/pages'/f'{doc}_page_{number:04d}.jpg'
        if source.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        else:jobs.append({'pdf':str(pdfmap[doc]),'page':number,'target':str(target)})
    if jobs:
        code='''import fitz,json,sys
from pathlib import Path
for job in json.load(sys.stdin):
 p=Path(job['target']);p.parent.mkdir(parents=True,exist_ok=True)
 with fitz.open(job['pdf']) as doc:
  page=doc[job['page']-1]; scale=1600/max(page.rect.width,page.rect.height)
  page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).save(str(p))
'''
        subprocess.run([str(ROOT/'parsing/.venv/bin/python'),'-c',code],input=json.dumps(jobs),text=True,check=True)


def build(folder):
    if (folder/'manifest.json').exists():raise ValueError('suite_already_frozen_use_a_new_version')
    cases,collections,annotations=load_cases(folder)
    policies={key:read(path/'eligibility.json') for key,path in SOURCES.items()}
    captured=[]
    for path in sorted((TRAFFIC/'decisions').glob('*.json')):
        try:r=read(path)
        except json.JSONDecodeError:continue
        if r['response']['valid'] and r['response']['bound']['status']=='ACCEPT':
            captured.append({'source_path':str(path),'record':r,'record_sha256':sha(path),'origin':'traffic_cpu'})
    for r in rows(DIAGNOSTIC/'C_decisions.jsonl'):
        if r['status']=='ACCEPT':
            pair=next(p for p in rows(DIAGNOSTIC/'pairs.jsonl') if p['pair_id']==r['pair_id'])
            captured.append({'source_path':str(DIAGNOSTIC/'C_decisions.jsonl'),'record_sha256':sha(DIAGNOSTIC/'C_decisions.jsonl'),
                'origin':'subject_gate_diagnostic','record':{'pair':pair,'response':{'valid':True,'bound':r['decision']}}})
    missing=[r['record']['pair']['pair_id'] for r in captured if r['record']['pair']['pair_id'] not in annotations]
    if missing:raise ValueError('new_accepts_need_source_review:'+','.join(missing))
    audits=[]
    for item in captured:
        rec=item['record'];pid=rec['pair']['pair_id'];verdict,issue,reason=annotations[pid]
        audits.append({'pair_id':pid,'source':rec['pair']['source'],'target':rec['pair']['target'],'origin':item['origin'],
            'review_verdict':verdict,'issue_type':issue,'reason':reason,'model_relation':rec['response']['bound']['relation'],
            'source_record_sha256':item['record_sha256'],'reviewer':'assistant_source_review_not_independent_expert',
            'publish_as_model_written':verdict=='VALID_RELATION'})
    jsonl(folder/'audits/accepted_decisions_snapshot.jsonl',captured)
    jsonl(folder/'audits/accepted_edge_reviews.jsonl',audits)
    # Candidate proposals are not accepted semantic edges. Audit every endpoint,
    # retain a complete pair inventory, and do not silently approve unreviewed pairs.
    inventory={};needed=set()
    for collection,path in [('baseline',TRAFFIC/'semantic_candidates.jsonl'),('hierarchical',HIERARCHICAL/'node_candidates.jsonl')]:
        for p in rows(path):
            key=tuple(sorted((p['source'],p['target'])));needed.update(('traffic',n) for n in key)
            r=inventory.setdefault(key,{'source':key[0],'target':key[1],'candidate_origins':[],'semantic_review':'UNREVIEWED_CANDIDATE_NOT_AN_EDGE'})
            r['candidate_origins'].append(collection)
    needed.update((c[s]['source_collection'],c[s]['node_id']) for c in cases for s in ['A','B'])
    for item in captured:
        needed.update(('traffic',item['record']['pair'][s]) for s in ['source','target'])
    jsonl(folder/'audits/candidate_inventory.jsonl',inventory.values())
    node_reviews=[];packaged=[]
    for collection,nid in sorted(needed):
        # All diagnostic accepted methods use the traffic collection.
        n=collections[collection][nid];node_reviews.append(structural_node_review(n,policies[collection][nid],SOURCES[collection]))
        n=json.loads(json.dumps(n));n['source_collection']=collection;n['eligible_members']=policies[collection][nid]['members']
        n['original_pdf_page']=PAGE_OVERRIDES.get((n['document'],n['page']),int(str(n['page']).replace('page_','')))
        for m in n['members']:
            if m['kind']=='visual' and m.get('crop'):
                dest=folder/'assets'/collection/Path(m['crop']).relative_to('assets')
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(SOURCES[collection]/m['crop'],dest)
                m['source_crop']=m['crop'];m['crop']=str(dest.relative_to(folder))
        packaged.append(n)
    jsonl(folder/'nodes.jsonl',packaged);jsonl(folder/'audits/node_integrity_reviews.jsonl',node_reviews)
    jsonl(folder/'cases.jsonl',cases)
    jsonl(folder/'inputs/pairs.jsonl',[{'case_id':c['case_id'],'source':c['A']['node_id'],'target':c['B']['node_id'],
        'requested_relation':c['relation']} for c in cases])
    jsonl(folder/'evaluation/reference_labels.jsonl',[{k:c[k] for k in ['case_id','suite_case_id','label','relation','group_id',
        'rationale','conditions','direction','reviewer','negative_scope','calibration_only','split']} for c in cases])
    pdfmap={d['document_id']:ROOT/d['input_pdf'] for d in read(ROOT/'data/incoming/paper_relevance_urban_traffic_20261013/corpus_manifest.json')['documents']}
    for n in packaged:
        doc=n['document']
        if doc in pdfmap:continue
        candidates=[ROOT/'data/processed'/f'{doc}.pdf',ROOT/'data/incoming'/f'{doc}.pdf']
        if doc=='nist_ai_rmf_1_0':candidates.insert(0,ROOT/'data/incoming/government_reports/NIST_AI_100-1_AI_RMF_1.0.pdf')
        if doc=='nvidia_2026_annual_report':candidates.insert(0,ROOT/'data/incoming/financial_reports/NVIDIA_2026_Annual_Report.pdf')
        pdfmap[doc]=next((p for p in candidates if p.exists()),None)
        if pdfmap[doc] is None:raise ValueError('missing_original_pdf:'+doc)
    page_keys={(c[s]['document'],c[s]['page']) for c in cases for s in ['A','B']}
    render_original_pages(folder,pdfmap,page_keys)
    core=[c for c in cases if not c['calibration_only']]
    summary={'cases':len(cases),'core_labels':dict(Counter(c['label'] for c in core)),
        'navigation_labels':dict(Counter(c['label'] for c in cases if c['calibration_only'])),
        'relations':dict(Counter(c['relation'] for c in core)),
        'documents':sorted({c[s]['document'] for c in cases for s in ['A','B']}),'group_count':len({c['group_id'] for c in cases}),
        'accepted_edges_reviewed':len(audits),'accepted_review_verdicts':dict(Counter(a['review_verdict'] for a in audits)),
        'candidate_pairs_inventory':len(inventory),'node_endpoints_checked':len(node_reviews),
        'node_flags':dict(Counter(f for r in node_reviews for f in r['flags'])),
        'review_level':'assistant-source-reviewed development regression, not independent expert or blind test',
        'live_job':'75115 remains running; only the frozen accepted snapshot is reviewed',
        'unreviewed_candidate_semantics':'All candidate pairs remain unreviewed unless separately listed in accepted/case reviews.'}
    write(folder/'summary.json',summary)
    files=[p for p in folder.rglob('*') if p.is_file() and p.name not in {'manifest.json','viewer.html'}]
    manifest={'created_at_utc':datetime.now(timezone.utc).isoformat(),'builder_sha256':sha(__file__),
        'page_provenance_corrections':[{'document':doc,'legacy_page_label':page,'original_pdf_page':number,
            'basis':'UMBRELLA literal original PDF text found on physical page 9; PDF printed pages 16-17.'} for (doc,page),number in PAGE_OVERRIDES.items()],
        'source_files_sha256':{str(path/'units.jsonl'):sha(path/'units.jsonl') for path in SOURCES.values()},
        'original_pdf_sha256':{str(p):sha(p) for p in pdfmap.values()},
        'snapshot_sha256':{str(p.relative_to(folder)):sha(p) for p in files},'scope':summary['live_job']}
    write(folder/'manifest.json',manifest)
    viewer(folder)
    validate(folder)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


def viewer(folder):
    ns={n['id']:n for n in rows(folder/'nodes.jsonl')};cards=[]
    for c in rows(folder/'cases.jsonl'):
        parts=[f'<details data-label="{c["label"]}"><summary>{escape(c["suite_case_id"])} · {c["label"]} · {escape(c["relation"])}</summary>',
            f'<p>{escape(c["rationale"])}</p><p>条件：{escape(c["conditions"])}</p>']
        for side in ['A','B']:
            end=c[side];n=ns[end['node_id']]
            parts.append(f'<h3>{side}: {escape(n["id"])}</h3><p>{escape(str(n.get("article_id")))} · 原始文章归属状态 {escape(n.get("assignment_status","UNSET"))}</p>')
            for m in n['members']:
                body=m['kind']+' '+m['id']+'\n'+m['text']
                parts.append(f'<pre>{escape(body)}</pre>')
                if m.get('crop'):parts.append(f'<img loading="lazy" src="{escape(m["crop"])}">')
            page=n['original_pdf_page'];image=f'assets/pages/{n["document"]}_page_{page:04d}.jpg'
            if (folder/image).exists():parts.append(f'<details><summary>原始 PDF 第 {page} 页；旧节点页标签 {escape(str(n["page"]))}</summary><img loading="lazy" src="{escape(image)}"></details>')
        parts.append('</details>');cards.append(''.join(parts))
    html='''<!doctype html><meta charset="utf-8"><title>Reusable evidence edge cases</title>
<style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem}details{border:1px solid #ccc;padding:12px;margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:12px}img{max-width:100%;max-height:850px}summary{cursor:pointer}select{font:inherit}</style>
<h1>Evidence edge 回归样本</h1><p>标签针对指定关系。参考标签为助手原文复核，尚未由独立专家确认。视觉描述用于召回，原图为核查来源。重复机制按 group_id 分组，禁止随机拆分后称独立盲测。</p>
<select onchange="document.querySelectorAll('[data-label]').forEach(e=>e.hidden=this.value!=='ALL'&&e.dataset.label!==this.value)"><option>ALL</option><option>POSITIVE</option><option>NEGATIVE</option><option>UNCERTAIN</option><option>NAVIGATION_POSITIVE</option></select>'''+''.join(cards)
    (folder/'viewer.html').write_text(html)


def validate(folder):
    m=read(folder/'manifest.json')
    for name,h in m['snapshot_sha256'].items():
        if sha(folder/name)!=h:raise ValueError('changed_snapshot:'+name)
    ns={n['id']:n for n in rows(folder/'nodes.jsonl')};seen=set()
    for c in rows(folder/'cases.jsonl'):
        key=(c['relation'],c['A']['node_id'],c['B']['node_id'])
        if key in seen:raise ValueError('duplicate_case')
        seen.add(key)
        for side in ['A','B']:
            e=c[side];a=e['primary_anchor'];member=next(x for x in ns[e['node_id']]['members'] if x['id']==a['member_id'] and x['kind']=='atom')
            if member['text'][a['char_start']:a['char_end']]!=a['quote']:raise ValueError('changed_case_anchor')
            if hashlib.sha256(member['text'].encode()).hexdigest()!=a['member_sha256']:raise ValueError('changed_member')
    for n in ns.values():
        for member in n['members']:
            if member.get('crop') and not (folder/member['crop']).exists():raise ValueError('missing_packaged_crop')
    return {'valid':True,'cases':len(seen),'nodes':len(ns)}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['build','validate','viewer']);p.add_argument('--folder',type=Path,default=DEFAULT)
    a=p.parse_args();result=globals()[a.stage](a.folder.resolve())
    if result is not None:print(json.dumps(result))
