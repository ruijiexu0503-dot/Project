#!/usr/bin/env python3
"""Fixed-node source-reviewed diagnostic: subject extraction ceiling vs method relation.

A/B share the same EP gate and forced pair queue. C is a separate method-only
channel, scored against different reference labels, never a pooled accuracy.
"""
import argparse
from collections import defaultdict, Counter
from pathlib import Path
import json
import shutil

import run_article_bridge_pilot as v1
import run_article_bridge_binding_v2 as v2
import run_traffic_relevance_graph as traffic
from replay_article_bridge_identity_v3 import identity_gate
from run_node_context_edges import ROOT,read,rows,write,jsonl,sha
from run_hybrid_node_v2 import audit
from node_context_policy import eligibility
from run_typed_node_edges import catalog
import build_evidence_node_graph_viewer as viewer

SOURCE=ROOT/'EvidenceNet/output/paper_relevance_urban_traffic_20261013'
CONTROL=ROOT/'EvidenceNet/output/article_bridge_identity_v3_20261012'
DEFAULT=ROOT/'EvidenceNet/output/subject_gate_diagnostic_v1_20261014'
# Zero-based parser elements become source atom IDs D(index+1). Labels are only
# used in prepare/report, never in model inputs or candidate selection.
SPECS=[
 ('traffic_st_transformer_2001_02908',3,3,'traffic_gnn_survey_2101_11174',33,2,True,
  'Both describe Graph WaveNet learned adjacency remaining fixed after training.'),
 ('traffic_gnn_survey_2101_11174',29,1,'traffic_st_transformer_2001_02908',7,4,True,
  'Distance-independent temporal attention explanation and attention across time steps within a bounded window; not unlimited history.'),
 ('traffic_gnn_survey_2101_11174',31,4,'traffic_htvgnn_2401_10155',8,6,True,
  'DCRNN uses spatial diffusion convolution and recurrent temporal modeling; the second adds GRU encoder-decoder details.'),
 ('traffic_htvgnn_2401_10155',3,7,'fusu_landuse_2405_19055',7,8,False,
  'Future road traffic prediction vs image segmentation/change detection: task equations alone do not establish a common mechanism.'),
 ('traffic_st_transformer_2001_02908',7,8,'fusu_landuse_2405_19055',6,6,False,
  'Road sensor observations in California 2012 vs satellite urban observations in China 2018-2020: no same dataset or method mechanism.'),
 ('traffic_st_transformer_2001_02908',7,12,'landcover_image_classification_2401_09607',3,10,False,
  'MAE/RMSprop training vs cross-entropy/Adam: generic training configuration similarity is insufficient; not a claim that no comparison is possible.')]


def check(out):
    m=read(out/'manifest.json')
    for path,h in m['source_sha256'].items():
        if sha(path)!=h:raise ValueError('changed_source:'+path)
    for path,h in m['code_sha256'].items():
        if sha(path)!=h:raise ValueError('changed_code:'+path)
    for path,h in m['snapshot_files'].items():
        if sha(out/path)!=h:raise ValueError('changed_snapshot:'+path)


def oracle_bindings(annotations,nodes,mapping):
    bindings=[]
    for row in annotations:
        nid=row['node_id']
        for item in row['event_project_content']:
            if item['kind'] not in {'EVENT','PROJECT'}:raise ValueError('oracle_cannot_retype_method_as_project')
            member=next(m for m in nodes[nid]['members'] if m['kind']=='atom' and m['id']==item['member_id'])
            if member['text'][item['start']:item['end']]!=item['quote']:raise ValueError('oracle_span_changed')
            anchor={'kind':'TEXT','member_id':member['id'],'node_id':nid,'article_id':mapping[nid],
                'char_start':item['start'],'char_end':item['end'],'quote':item['quote']}
            bindings.append({'binding_id':'ORACLE_'+v2.digest([nid,item['subject_id']])[:12],
                'node_id':nid,'article_id':mapping[nid],'subject_id':item['subject_id'],
                'status':'SUPPORTED','purposes':['content_index'],
                'decision':{'aspect_type':'other','local_anchors':[anchor],'context_sources':[]}})
    return bindings


def prepare(out):
    if out.exists():raise ValueError('fresh_output_required')
    traffic.check(SOURCE)
    out.mkdir(parents=True);viewer.PREPARED=SOURCE/'prepared'
    pages={};node_lookup={};fingerprints={};selected={};pairs=[];labels=[]
    def endpoint(doc,page,element):
        task=f'{doc}/page_{page:04d}';aid=f'D{element+1:04d}'
        if task not in pages:
            files=list((SOURCE/'nodes').glob(f'batch_*/hybrid/{task}/evidence_nodes.jsonl'))
            if len(files)!=1:raise ValueError('node_page_not_unique_or_ready:'+task)
            path=files[0];hybrid_root=Path(str(path.parent).split('/hybrid/',1)[0])/'hybrid'
            if not audit(task,SOURCE/'prepared',hybrid_root)['valid'] or not read(path.parent/'run_summary.json')['decision_valid']:raise ValueError('invalid_page:'+task)
            fingerprints[str(path)]=sha(path)
            rep=SOURCE/'prepared'/task/'input_representation.json';fingerprints[str(rep)]=sha(rep)
            page_record=viewer.build_page(path,out);pages[task]=page_record
            for n in page_record['nodes']:
                n.update(document=doc,page=page,article_id=doc+'::PAPER',task=task)
                node_lookup[n['id']]=n
        hits=[n for n in pages[task]['nodes'] if any(m['kind']=='atom' and m['id']==aid for m in n['members'])]
        if len(hits)!=1:raise ValueError('source_element_not_unique:'+task+':'+aid)
        n=hits[0];selected[n['id']]=n
        return n['id'],{'document':doc,'page':page,'member_id':aid,
            'text':next(m['text'] for m in n['members'] if m['kind']=='atom' and m['id']==aid)}
    for da,pa,ea,db,pb,eb,positive,reason in SPECS:
        a,sa=endpoint(da,pa,ea);b,sb=endpoint(db,pb,eb);pid='DIAG_'+v2.digest([a,b])[:12]
        pairs.append({'pair_id':pid,'source':a,'target':b,'cohort':'new_method','forced_for_diagnosis':True})
        labels.append({'pair_id':pid,'method_correspondence':positive,'shared_event_project':False,
            'rationale':reason,'source_review':[sa,sb],'reviewer':'assistant_source_review_not_independent_human_gold'})
    old={n['id']:n for n in rows(CONTROL/'units.jsonl')};fingerprints[str(CONTROL/'units.jsonl')]=sha(CONTROL/'units.jsonl')
    a='DLRmagazine_176_EN_page_0012_HY_013';b='DLRmagazine_176_EN_page_0012_HY_015';c='CERNCourier2022NovDec-digitaledition_page_0006_HY_016'
    control_map=read(CONTROL/'unit_article_map.json')
    fingerprints[str(CONTROL/'unit_article_map.json')]=sha(CONTROL/'unit_article_map.json')
    for nid in [a,b,c]:
        selected[nid]={**old[nid],'article_id':control_map[nid]}
    for x,y,same in [(a,b,True),(a,c,False)]:
        pid='DIAG_'+v2.digest([x,y])[:12];pairs.append({'pair_id':pid,'source':x,'target':y,'cohort':'old_calibration','forced_for_diagnosis':True})
        labels.append({'pair_id':pid,'method_correspondence':None,'shared_event_project':same,
            'rationale':'Known AHEAD project identity positive / unrelated Open Science negative; reused calibration, not new generalization evidence.'})
    mapping={nid:n['article_id'] for nid,n in selected.items()};policies=eligibility(list(selected.values()))
    for nid in [a,b,c]:policies[nid]=read(CONTROL/'eligibility.json')[nid]
    annotations=[]
    for nid,n in selected.items():
        content=[]
        if nid in {a,b}:
            member=next(m for m in n['members'] if m['kind']=='atom' and 'AHEAD' in m['text']);lo=member['text'].index('AHEAD')
            content=[{'subject_id':'PROJECT:AHEAD','kind':'PROJECT','member_id':member['id'],'start':lo,'end':lo+5,'quote':'AHEAD'}]
        annotations.append({'node_id':nid,'event_project_content':content,
            'review_note':'Source-reviewed named method/dataset/task description is not an EVENT/PROJECT; no type coercion.' if not content else 'Known project local content; calibration only.'})
    jsonl(out/'units.jsonl',selected.values());write(out/'eligibility.json',policies);write(out/'unit_article_map.json',mapping)
    groups=defaultdict(list)
    for nid,aid in mapping.items():groups[aid].append(nid)
    jsonl(out/'articles.jsonl',[{'article_id':aid,'node_ids':sorted(ids)} for aid,ids in sorted(groups.items())])
    jsonl(out/'pairs.jsonl',sorted(pairs,key=lambda p:p['pair_id']))
    jsonl(out/'evaluation/pair_reference.jsonl',labels);jsonl(out/'evaluation/node_oracle.jsonl',annotations)
    jsonl(out/'protected_intra_article_candidates.jsonl',[]);write(out/'binding_probe_spec.json',[])
    write(out/'pages.json',list(pages.values()))
    fingerprints.update({str(p):sha(p) for p in (out/'assets').rglob('*') if p.is_file()})
    code=[Path(__file__),Path(v1.__file__),Path(v2.__file__),Path(traffic.__file__),
        Path(__file__).with_name('replay_article_bridge_identity_v3.py'),Path(__file__).with_name('run_typed_node_edges.py')]
    write(out/'manifest.json',{'experiment':'subject_gate_diagnostic_v1','source_sha256':fingerprints,
        'code_sha256':{str(p.resolve()):sha(p) for p in code},'sampling':{'do_sample':False,'enable_thinking':False},
        'snapshot_files':{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and 'assets' not in p.parts},
        'fixed_pairs':len(pairs),'new_method_pairs':6,'controls':2,'scope':'text-first methods diagnostic, not multimodal accuracy benchmark',
        'protocol':'A automated EP binding; B source-reviewed node EP binding with same gate; C method-only pair verifier; separate reference labels',
        'model':str(ROOT/'external/models/Qwen3.5-35B-A3B'),'retrieval_gain':'NOT_EVALUATED'})
    jsonl(out/'oracle_bindings.jsonl',oracle_bindings(annotations,selected,mapping))
    report(out)


def run(out):
    check(out)
    from run_own_corpus_edges import llm
    model=llm();nodes={n['id']:n for n in rows(out/'units.jsonl')};policies=read(out/'eligibility.json');mapping=read(out/'unit_article_map.json')
    # Model sees no pair references or oracle file.
    mentions=v1.index_subjects(model,out,nodes,policies,mapping)
    shutil.copy2(out/'subject_mentions.jsonl',out/'v1_subject_mentions.jsonl');jsonl(out/'v1_context_bindings.jsonl',[])
    groups={}
    for m in mentions:
        key=(m['article_id'],m['subject_id']);g=groups.setdefault(key,{'group_id':'G_'+v2.digest(key)[:12],
            'article_id':key[0],'literal_subject_id':key[1],'kind':m['kind'],'name':m['source_mention'],'mentions':[]});g['mentions'].append(m)
    jsonl(out/'identity_groups.jsonl',groups.values());jsonl(out/'alias_candidates.jsonl',v2.alias_candidates(list(groups.values())))
    subjects,gmap=v2.resolve_aliases(model,out);queue=v2.binding_queue(out,gmap)
    raw=v2.verify_bindings(model,out,nodes,policies,mapping,subjects,queue);jsonl(out/'raw_node_subject_bindings.jsonl',raw)
    smap={s['subject_id']:s for s in subjects}
    bindings=[identity_gate(b,smap[b['subject_id']],nodes,mapping) for b in raw]
    jsonl(out/'node_subject_bindings.jsonl',bindings)
    jsonl(out/'A_decisions.jsonl',[v2.derive_pair(p,bindings) for p in rows(out/'pairs.jsonl')])
    methods=[]
    for pair in rows(out/'pairs.jsonl'):
        if pair['cohort']!='new_method':continue
        public={};lookups={};images=[]
        for side,key in [('A','source'),('B','target')]:
            entries,lookup=catalog(nodes[pair[key]],policies[pair[key]],side,out)
            for e in entries:
                if e['kind']=='VISUAL':images.append(str(out/e.pop('crop')));e['image_index']=len(images)
            public[side]=entries;lookups[side]=lookup
        prompt='''Judge only concrete METHOD_CORRESPONDENCE between the two original evidence nodes.
Accept only a specific common mechanism described at both ends, an explanation and its concrete application,
or the same named method with the same technically specified behavior or limitation. Method lists and generic
terms such as Transformer, CNN, urban, spatial, temporal or training are not enough by themselves.
Different objects/tasks are not automatically negative when the actual specific mechanism corresponds;
shared topic or merely being comparable is not positive. Preserve window limits, training vs inference,
optimizer/loss differences and qualifications. Never import the other endpoint's facts into local content.
Do not require a shared event/project. Reject when no concrete method correspondence is supported; use
UNCERTAIN for ambiguous/incomplete evidence. No supports/causal/contradicts assertion.
Return {"status":"ACCEPT|REJECT|UNCERTAIN","relation":"METHOD_CORRESPONDENCE|NONE",
"source_content":"","target_content":"","shared_mechanism":"","conditions":"","reason":"",
"A_evidence_ids":[],"B_evidence_ids":[],"A_visual_observation":"","B_visual_observation":""}.
''' + json.dumps(public,ensure_ascii=False)
        def validate(v):
            result=traffic.validate(v,lookups)
            if result['status']=='ACCEPT' and result['relation']!='METHOD_CORRESPONDENCE':raise ValueError('method_only_diagnostic')
            return result
        response=v1.cached_call(model,out,'method_'+pair['pair_id'],prompt,images,validate,1600)
        methods.append({'pair_id':pair['pair_id'],'status':response['bound']['status'] if response['valid'] else 'FORMAT_PENDING',
            'decision':response['bound'],'errors':response['errors']})
        jsonl(out/'C_decisions.jsonl',methods)
    report(out)


def report(out):
    check(out);pairs=rows(out/'pairs.jsonl');nodes={n['id']:n for n in rows(out/'units.jsonl')};mapping=read(out/'unit_article_map.json')
    oracle=oracle_bindings(rows(out/'evaluation/node_oracle.jsonl'),nodes,mapping)
    b={p['pair_id']:v2.derive_pair(p,oracle) for p in pairs};jsonl(out/'B_decisions.jsonl',b.values())
    optional=lambda name:rows(out/name) if (out/name).exists() else []
    a={d['pair_id']:d for d in optional('A_decisions.jsonl')};c={d['pair_id']:d for d in optional('C_decisions.jsonl')}
    refs={d['pair_id']:d for d in rows(out/'evaluation/pair_reference.jsonl')}
    index_errors=optional('index_errors.jsonl')
    parent=SOURCE/'graph/semantic_candidates.jsonl'
    natural={frozenset((p['source'],p['target'])) for p in rows(parent)} if parent.exists() else None
    comparison=[]
    for p in pairs:
        pid=p['pair_id'];ref=refs[pid]
        comparison.append({**p,'reference_shared_event_project':ref['shared_event_project'],
            'reference_method_correspondence':ref['method_correspondence'],
            'A_shared_subject':bool(a[pid]['paths']) if pid in a else None,'B_shared_subject':bool(b[pid]['paths']),
            'A_status':a.get(pid,{}).get('status','NOT_RUN'),
            'C_method_status':c.get(pid,{}).get('status','NOT_RUN' if p['cohort']=='new_method' else 'NOT_APPLICABLE'),
            'natural_candidate':(frozenset((p['source'],p['target'])) in natural) if natural is not None and p['cohort']=='new_method' else None})
    jsonl(out/'comparison.jsonl',comparison)
    scored=[x for x in comparison if x['cohort']=='new_method']
    complete=len(a)==len(pairs) and len(c)==6 and not index_errors and all(d['status']!='BINDING_PENDING' for d in a.values()) and all(d['status']!='FORMAT_PENDING' for d in c.values())
    summary={'phase':'COMPLETE_AWAITING_SOURCE_AUDIT' if complete else 'PREPARED_OR_PARTIAL',
        'new_method_pairs':6,'old_calibration_pairs':2,'nodes':len(nodes),
        'method_reference_positive':sum(x['reference_method_correspondence'] for x in scored),
        'positive_method_pairs_outside_even_oracle_EP_gate':sum(x['reference_method_correspondence'] and not x['B_shared_subject'] for x in scored),
        'C_statuses':dict(Counter(x['C_method_status'] for x in scored)),
        'A_index_errors':len(index_errors),
        'reference_review':'assistant-reviewed original text, not independent expert ground truth',
        'retrieval_gain':'NOT_EVALUATED','note':'A/B evaluate EP navigation; C evaluates method correspondence. Do not compare pooled accuracies or call missing EP identity a semantic rejection.'}
    write(out/'summary.json',summary)
    (out/'REPORT.md').write_text('# Subject gate diagnostic\n\n```json\n'+json.dumps(summary,indent=2)+'\n```\n\n'+json.dumps(comparison,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','run','report']);p.add_argument('--output',type=Path,default=DEFAULT)
    a=p.parse_args();globals()[a.stage](a.output.resolve())
