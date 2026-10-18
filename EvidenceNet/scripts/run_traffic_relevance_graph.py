#!/usr/bin/env python3
"""Full-paper reading graph and bounded, source-grounded semantic diagnostic.

Method correspondence is a separate channel, not a shared EVENT/PROJECT gate.
All semantic outputs remain model proposals pending source review.
"""
import argparse
from collections import Counter,defaultdict
import gc
import json
from pathlib import Path

from run_node_context_edges import ROOT,read,rows,write,jsonl,sha
from run_fact_grounded_edges import call_json,digest
from run_typed_node_edges import catalog
from node_context_policy import eligibility
from run_hybrid_node_v2 import audit
import build_evidence_node_graph_viewer as viewer

DEFAULT=ROOT/'EvidenceNet/output/paper_relevance_urban_traffic_20261013'


def check(root):
    manifest=read(root/'manifest.json')
    for path,h in {**manifest['source_sha256'],**manifest['code_sha256']}.items():
        if sha(path)!=h:raise ValueError('changed_input:'+path)
    for path,h in manifest['prepared_sha256'].items():
        if sha(root/path)!=h:raise ValueError('changed_prepared:'+path)


def assemble(root):
    check(root);out=root/'graph';out.mkdir(parents=True,exist_ok=True)
    viewer.PREPARED=root/'prepared'
    tasks=read(root/'prepared/manifest.json')['tasks']
    paths=sorted((root/'nodes').glob('batch_*/hybrid/**/evidence_nodes.jsonl'))
    if len(paths)!=len(tasks):raise ValueError(f'incomplete_nodes:{len(paths)}/{len(tasks)}')
    pages=[];nodes=[];hashes={};seen=set()
    for path in paths:
        task=str(path.parent).split('/hybrid/',1)[1];seen.add(task)
        hybrid_root=Path(str(path.parent).split('/hybrid/',1)[0])/'hybrid'
        if not audit(task,root/'prepared',hybrid_root)['valid'] or not read(path.parent/'run_summary.json')['decision_valid']:
            raise ValueError('node_audit_failed:'+task)
        hashes[str(path)]=sha(path);page=viewer.build_page(path,out);pages.append(page)
        for node in page['nodes']:
            node.update(document=page['document'],page=int(page['page']),article_id=page['document']+'::PAPER',
                        assignment_status='KNOWN_PAPER_DOCUMENT_PROFILE',task=task)
            nodes.append(node)
    if seen!=set(tasks):raise ValueError('task_coverage_mismatch')
    if len({n['id'] for n in nodes})!=len(nodes):raise ValueError('duplicate_node_id')
    policies=eligibility(nodes)
    for n in nodes:
        for e in policies[n['id']]['members']:
            m=next(m for m in n['members'] if m['id']==e['member_id'] and m['kind']==e['kind'])
            if m.get('role') in {'reference','catalogue','header','foot','watermark'} or m.get('type') in {'heading','furniture'}:
                e.update(eligible=False,reason='metadata_not_content')
        policies[n['id']]['eligible']=any(e['eligible'] for e in policies[n['id']]['members'])
    reading=[]
    # Parser order determines navigation, not sentence identity or semantic support.
    for doc in sorted({n['document'] for n in nodes}):
        text=[n for n in nodes if n['document']==doc and policies[n['id']]['eligible'] and
              any(m['kind']=='atom' and m.get('role') in {'para','half_para','list','equ'} for m in n['members'])]
        text.sort(key=lambda n:(n['page'],n['min_order'] if n['min_order'] is not None else 1e9,n['id']))
        for a,b in zip(text,text[1:]):
            if b['page']-a['page']>1:continue
            reading.append({'source':a['id'],'target':b['id'],'type':'NEXT','family':'reading_order',
                'cross_page':a['page']!=b['page'],'status':'PARSER_ORDER_NAVIGATION_NOT_SENTENCE_MERGE'})
    jsonl(out/'units.jsonl',nodes);write(out/'eligibility.json',policies);write(out/'pages.json',pages)
    jsonl(out/'reading_edges.jsonl',reading);write(out/'node_input_sha256.json',hashes)
    print(json.dumps({'pages':len(pages),'nodes':len(nodes),'reading_edges':len(reading)}),flush=True)


def candidates(root):
    check(root)
    import numpy as np
    from run_node_embedding_geometry_pilot import embed
    out=root/'graph';nodes={n['id']:n for n in rows(out/'units.jsonl')};policies=read(out/'eligibility.json')
    ids=sorted(n for n in nodes if policies[n]['eligible'])
    vectors=np.asarray(embed(['\n'.join(m.get('text','') for m in nodes[n]['members']) for n in ids],ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B'))
    np.save(out/'node_vectors.npy',vectors);write(out/'vector_node_ids.json',ids)
    sim=vectors@vectors.T;bydoc=defaultdict(list)
    for i,nid in enumerate(ids):bydoc[nodes[nid]['document']].append(i)
    pool={}
    def add(i,j,route):
        a,b=sorted([ids[i],ids[j]])
        if a==b:return
        p=pool.setdefault((a,b),{'pair_id':'TRAFFIC_'+digest([a,b])[:14],'source':a,'target':b,'routes':[],
            'similarity':float(sim[i,j]),'scope':'intra_article' if nodes[a]['document']==nodes[b]['document'] else 'cross_document'})
        if route not in p['routes']:p['routes'].append(route)
    # All document pairs get equal budgets, independent of supplied relevance groups.
    docs=sorted(bydoc)
    for x,da in enumerate(docs):
        for db in docs[x+1:]:
            options=sorted(((float(sim[i,j]),i,j) for i in bydoc[da] for j in bydoc[db]),reverse=True)
            degree=Counter();chosen=0
            for score,i,j in options:
                if degree[i]>=3 or degree[j]>=3:continue
                add(i,j,'cross_document_dense');degree[i]+=1;degree[j]+=1;chosen+=1
                if chosen>=24:break
    for doc,indices in bydoc.items():
        options=sorted(((float(sim[i,j]),i,j) for off,i in enumerate(indices) for j in indices[off+1:]),reverse=True)
        degree=Counter();chosen=0
        for score,i,j in options:
            if degree[i]>=2 or degree[j]>=2:continue
            add(i,j,'intra_article_dense');degree[i]+=1;degree[j]+=1;chosen+=1
            if chosen>=12:break
    jsonl(out/'semantic_candidates.jsonl',pool.values())
    write(out/'candidate_policy.json',{'cross_document_pairs':24,'intra_article_per_paper':12,
        'candidate_count':len(pool),'group_labels_used':False,'shared_subject_required':False,
        'scope':'bounded diagnostic graph; not exhaustive semantic relations',
        'visual_retrieval':'generated description; original crop required for verification'})


def validate(value,lookups):
    if not isinstance(value,dict) or value.get('status') not in {'ACCEPT','REJECT','UNCERTAIN'}:raise ValueError('status')
    for field in ['source_content','target_content','shared_mechanism','conditions','reason']:
        if not isinstance(value.get(field),str):raise ValueError('missing_'+field)
    anchors={}
    for side in ['A','B']:
        selected=value.get(side+'_evidence_ids')
        if not isinstance(selected,list) or any(not isinstance(k,str) or k not in lookups[side] for k in selected):raise ValueError('anchor_ownership_'+side)
        anchors[side]=[lookups[side][k] for k in selected]
        if value['status']=='ACCEPT' and not selected:raise ValueError('missing_endpoint_evidence')
    if value['status']=='ACCEPT':
        if value.get('relation') not in {'METHOD_CORRESPONDENCE','DATASET_CORRESPONDENCE','MEASUREMENT_COMPARISON'}:raise ValueError('relation')
        if any(not value[f].strip() for f in ['source_content','target_content','shared_mechanism']):raise ValueError('missing_content_correspondence')
        for side in ['A','B']:
            if any(a['kind']=='VISUAL' for a in anchors[side]) and not str(value.get(side+'_visual_observation','')).strip():raise ValueError('visual_observation_required')
    return {**value,'anchors':anchors,'review_status':'MODEL_PROPOSAL_SOURCE_REVIEW_REQUIRED'}


def verify(root):
    check(root)
    from run_own_corpus_edges import llm
    out=root/'graph';nodes={n['id']:n for n in rows(out/'units.jsonl')};policies=read(out/'eligibility.json');model=llm();decisions=[]
    for pair in rows(out/'semantic_candidates.jsonl'):
        evidence={};lookups={};images=[]
        for side,key in [('A','source'),('B','target')]:
            public,lookup=catalog(nodes[pair[key]],policies[pair[key]],side,out)
            for entry in public:
                if entry['kind']=='VISUAL':images.append(str(out/entry.pop('crop')));entry['image_index']=len(images)
            evidence[side]=public;lookups[side]=lookup
        prompt='''Inspect the TWO original evidence nodes. Identify concrete correspondence, not broad topical similarity.
Do not require shared EVENT/PROJECT names. Do not infer a relationship from document titles or subject area.
METHOD_CORRESPONDENCE requires the same specific described mechanism, or its concrete application at both endpoints;
merely saying Transformer, CNN, machine learning, urban, spatial or temporal is insufficient.
DATASET_CORRESPONDENCE requires the same identifiable dataset with substantive description/use at both ends;
sharing a task, satellite family, sensor category or similar abbreviations is insufficient.
MEASUREMENT_COMPARISON requires the same target quantity and explicit conditions permitting a meaningful comparison.
Different tasks/metrics/data splits prevent treating two numerical scores as directly comparable.
A bibliography entry, contents preview, author affiliation or bare method list is not substantive evidence.
First state EACH endpoint's actual local content separately, then the concrete correspondence and any limitations.
Never copy facts from the other endpoint. Generated visual descriptions are not supplied as proof: inspect the original image.
REJECT when there is only generic topic overlap or incompatible objects; UNCERTAIN when evidence is insufficient.
No causal, entails, supports, or contradicts edge is permitted. Return JSON:
{"status":"ACCEPT|REJECT|UNCERTAIN","relation":"METHOD_CORRESPONDENCE|DATASET_CORRESPONDENCE|MEASUREMENT_COMPARISON|NONE",
"source_content":"","target_content":"","shared_mechanism":"","conditions":"","reason":"",
"A_evidence_ids":[],"B_evidence_ids":[],"A_visual_observation":"","B_visual_observation":""}
''' + json.dumps(evidence,ensure_ascii=False)
        fingerprint=digest({'prompt':prompt,'images':[sha(p) for p in images]})
        path=out/'decisions'/(pair['pair_id']+'.json')
        if path.exists():
            record=read(path)
            if record['input_sha256']!=fingerprint:raise ValueError('stale_pair')
        else:
            response=call_json(model,prompt,images,lambda v:validate(v,lookups),1800)
            record={'pair':pair,'input_sha256':fingerprint,'response':response};write(path,record)
        decisions.append(record)
        print(pair['pair_id'],record['response']['bound']['status'] if record['response']['valid'] else 'FORMAT_PENDING',flush=True)
    jsonl(out/'semantic_decisions.jsonl',decisions)
    jsonl(out/'semantic_edges.jsonl',[{**r['pair'],**r['response']['bound']} for r in decisions if r['response']['valid'] and r['response']['bound']['status']=='ACCEPT'])
    report(root)


def report(root):
    out=root/'graph';out.mkdir(parents=True,exist_ok=True)
    optional=lambda n:rows(out/n) if (out/n).exists() else []
    decisions=[read(p) for p in sorted((out/'decisions').glob('*.json'))]
    statuses=Counter(r['response']['bound']['status'] if r['response']['valid'] else 'FORMAT_PENDING' for r in decisions)
    summary={'node_batches_complete':len(list((root/'nodes').glob('batch_*/audit.json'))),
        'expected_node_batches':len(read(root/'prepared/manifest.json')['batches']),
        'nodes':len(optional('units.jsonl')),'reading_edges':len(optional('reading_edges.jsonl')),
        'semantic_candidates':len(optional('semantic_candidates.jsonl')),'semantic_decisions':len(decisions),'statuses':dict(statuses),
        'phase':'COMPLETE_AWAITING_SOURCE_REVIEW' if (out/'semantic_edges.jsonl').exists() else 'PARTIAL_OR_PENDING',
        'retrieval_gain':'NOT_EVALUATED','document_groups_are_pair_gold':False}
    write(out/'summary.json',summary)
    data={'summary':summary,'pages':read(out/'pages.json') if (out/'pages.json').exists() else [],
        'reading':optional('reading_edges.jsonl'),'semantic':optional('semantic_edges.jsonl'),'decisions':decisions}
    payload=json.dumps(data,ensure_ascii=False).replace('</','<\\/')
    html='''<!doctype html><meta charset="utf-8"><title>Traffic evidence graph</title><style>body{font:16px system-ui;margin:2rem}pre{white-space:pre-wrap}img{max-width:90%;max-height:600px}details{border:1px solid #ccc;padding:12px;margin:8px}</style><h1>Evidence nodes and links</h1><p>Semantic edges are model proposals pending source review.</p><main id="root"></main><script type="application/json" id="data">PAYLOAD</script><script>
const d=JSON.parse(document.getElementById('data').textContent),root=document.getElementById('root');
function txt(tag,s,p){const e=document.createElement(tag);e.textContent=s;p.appendChild(e);return e}
function detail(s,p){const e=txt('details','',p);txt('summary',s,e);return e}
function img(s,p){if(!s)return;const i=document.createElement('img');i.src=s;i.loading='lazy';p.appendChild(i)}
txt('pre',JSON.stringify(d.summary,null,2),root);
for(const page of d.pages){const box=detail(page.document+' / '+page.page,root);img(page.image,box);txt('pre',JSON.stringify(page.titles,null,2),box);for(const n of page.nodes){const b=detail(n.id,box);for(const m of n.members){txt('pre',m.kind+' '+m.id+'\\n'+m.text,b);img(m.crop,b)}txt('pre',JSON.stringify([...d.reading,...d.semantic].filter(e=>e.source===n.id||e.target===n.id),null,2),b)}}
const log=detail('All semantic decisions, including rejection and uncertainty',root);for(const r of d.decisions){const b=detail(r.pair.pair_id,log);txt('pre',JSON.stringify(r,null,2),b)}
</script>'''
    (out/'viewer.html').write_text(html.replace('PAYLOAD',payload));(out/'REPORT.md').write_text('# Traffic relevance pipeline\n\n```json\n'+json.dumps(summary,indent=2)+'\n```\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['assemble','candidates','verify','report','check']);p.add_argument('--root',type=Path,default=DEFAULT)
    a=p.parse_args();globals()[a.stage](a.root.resolve())
