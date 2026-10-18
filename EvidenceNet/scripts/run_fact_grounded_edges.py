#!/usr/bin/env python3
"""Fixed-candidate comparison of direct and independently grounded fact judgments."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import shutil

from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, check
from run_typed_node_edges import catalog, request_targets, report as graph_report

SOURCE = ROOT/'EvidenceNet/output/typed_node_edges_v1_20261012'
KINDS = {'EVENT','PROJECT','METHOD','MEASUREMENT','PERSON','OBJECT','ORGANIZATION','CONCEPT'}
SYMMETRIC = {'SAME_EVENT','SAME_PROJECT','SAME_OBJECT','METHOD_CORRESPONDENCE','MEASUREMENT_CONTEXT','ORGANIZATION_CONTEXT'}
DIRECTED = {'CAPTION_FOR','EXPLAINS','DEFINITION_TO_INSTANCE'}
RELATIONS = SYMMETRIC | DIRECTED
SPEC = '''Choose the actual relationship, independently of the candidate route.
SAME_EVENT: both facts identify the same specific occurrence, not merely the same instrument or organization.
SAME_PROJECT: both facts concern the same named project and assert content about it.
SAME_OBJECT: both facts concern the same identifiable person/object, not the same image category or portrait style.
METHOD_CORRESPONDENCE: a specific shared mechanism or method with concrete description/application, not generic task labels.
MEASUREMENT_CONTEXT: same measured object/quantity with compatible or explicitly differing conditions; preserve units, time and reference frame. This does not assert numerical equality or entailment.
CAPTION_FOR: caption describes the actual visual at the other endpoint; direction caption to visual.
EXPLAINS: one endpoint concretely explains the other's formula/mechanism/claim; direction explanation to explained content.
DEFINITION_TO_INSTANCE: one defines a category/term and the other explicitly instantiates/applies it; direction definition to instance.
ORGANIZATION_CONTEXT: shared institution or instrument only; keep as INDEX_ONLY, not a positive evidence edge.
Bare names, publication marks, broad topics, visual style and unsupported identity do not constitute a content relationship.
Do not transfer a fact from one endpoint to the other. Unknown identity or missing support means UNCERTAIN.'''


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def norm(value):
    return ' '.join(value.casefold().split())


def prepare(out,source,limit=80):
    check(source)
    if out.exists():raise ValueError('Use a fresh experiment directory')
    queue=rows(source/'verification_queue.jsonl');selected={}
    # Freeze all inspected cross-document accepted edges, plus prior regression pairs.
    required={e['id'].split('::')[0] for e in rows(source/'semantic_edges.jsonl') if e['scope']=='cross_document'}
    for name in ['old_case_regression.jsonl','old_omission_regression.jsonl']:
        for case in rows(source/'audit'/name):
            required.update(e.split('::')[0] for e in case['new_edge_ids'] if e.startswith('TYPED_'))
    required.update(['TYPED_01886','TYPED_04532','TYPED_07990','TYPED_00808'])
    for p in queue:
        if p['pair_id'] in required:selected[p['pair_id']]={**p,'pilot_cohort':'known_case_regression'}
    if len(selected)>limit:raise ValueError('Budget smaller than required regression set')
    buckets={}
    for p in queue:
        if p['pair_id'] not in selected:buckets.setdefault((p['relation_type'],p['scope']),[]).append(p)
    rng=random.Random(20261012)
    for bucket in buckets.values():rng.shuffle(bucket)
    while len(selected)<min(limit,len(queue)) and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(selected)<limit:
                p=buckets[key].pop();selected[p['pair_id']]={**p,'pilot_cohort':'stratified_development_sample'}
    out.mkdir(parents=True)
    names=['pages.json','units.jsonl','reading_edges.jsonl','issues.jsonl','eligibility.json','source_references.jsonl']
    for name in names:shutil.copy2(source/name,out/name)
    shutil.copytree(source/'assets',out/'assets')
    jsonl(out/'verification_queue.jsonl',selected.values())
    ns={p[k] for p in selected.values() for k in ['source','target']}
    coverage={'nodes':len(rows(out/'units.jsonl')),'queue':len(selected),'queue_nodes':len(ns),
              'candidate_hypotheses':len(queue),'queue_scopes':dict(Counter(p['scope'] for p in selected.values())),
              'uncovered_eligible_nodes':[]}
    write(out/'coverage.json',coverage)
    manifest=read(source/'manifest.json')
    manifest.update(experiment='independent_fact_edges_v1',source_experiment=str(source),
                    snapshot_files={n:sha(out/n) for n in names+['verification_queue.jsonl']},
                    script_sha256=sha(__file__),typed_helper_sha256=sha(Path(__file__).with_name('run_typed_node_edges.py')),
                    design='same node pairs, same model, same relation specification; direct vs isolated supported facts',
                    development_sample=True,independent_human_evaluation=False)
    write(out/'manifest.json',manifest)
    shutil.copy2(__file__,out/'code_snapshot.py')
    baseline=[]
    for p in selected.values():
        old=read(source/'decisions'/f'{p["pair_id"]}.json')
        baseline.append({'pair':p,'old_status':old['status'],'old_value':old['value']})
    jsonl(out/'previous_decisions.jsonl',baseline)
    print(json.dumps(coverage),flush=True)


def validate_facts(value,lookup,*,subject_normalizer=norm):
    if not isinstance(value,dict) or not isinstance(value.get('facts'),list):raise ValueError('facts_list_required')
    if len(value['facts'])>10:raise ValueError('too_many_facts')
    result=[]
    for fact in value['facts']:
        if not isinstance(fact,dict):raise ValueError('fact_object_required')
        if fact.get('subject_kind') not in KINDS:raise ValueError('subject_kind_invalid')
        for field in ['subject','predicate','qualifiers','observation']:
            if not isinstance(fact.get(field),str):raise ValueError('fact_field_missing:'+field)
        if not fact['subject'].strip() or len(fact['predicate'].split())<2:raise ValueError('bare_name_not_fact')
        ids=fact.get('evidence_ids');sid=fact.get('subject_evidence_id')
        if not isinstance(ids,list) or not ids or not all(isinstance(i,str) and i in lookup for i in ids):raise ValueError('fact_evidence_invalid')
        if not isinstance(sid,str) or sid not in ids:raise ValueError('subject_evidence_invalid')
        a=lookup[sid]
        if a['kind']=='TEXT' and subject_normalizer(fact['subject']) not in subject_normalizer(a['quote']):raise ValueError('subject_not_in_source')
        if any(lookup[i]['kind']=='VISUAL' for i in ids) and len(fact['observation'].strip())<8:raise ValueError('original_visual_observation_required')
        result.append({**fact,'id':f'F{len(result):03d}','anchors':[lookup[i] for i in ids]})
    return result


def call_json(model,prompt,images,validate,tokens=1600):
    from evidence_graph.llm_client import extract_json
    attempts=[];value={};errors=[];bound=None
    for i in range(2):
        request=prompt
        if i:request+='\nCorrect these schema/source errors: '+json.dumps(errors)+'\nPrevious output: '+attempts[-1]['raw']
        raw=model.generate_raw_with_images('Use only the supplied source evidence. Return JSON.',request,images,tokens).raw
        attempts.append({'prompt':request,'raw':raw})
        try:
            value=extract_json(raw);bound=validate(value);errors=[];break
        except (ValueError,KeyError,TypeError) as exc:errors=[str(exc)]
    return {'valid':not errors,'value':value,'bound':bound,'errors':errors,'attempts':attempts}


def extract_node(model,node,policy,out):
    public,lookup=catalog(node,policy,'N',out);images=[]
    for entry in public:
        if entry['kind']=='VISUAL':images.append(str(out/entry.pop('crop')));entry['image_index']=len(images)
    fingerprint=digest({'evidence':public,'anchors':lookup})
    path=out/'facts'/f'{node["id"]}.json'
    if path.exists():
        record=read(path)
        if record['input_sha256']!=fingerprint:raise ValueError('stale_fact_input')
        return record
    schema={'facts':[{'subject':'verbatim source mention; do not canonicalize from external knowledge',
        'subject_kind':'EVENT|PROJECT|METHOD|MEASUREMENT|PERSON|OBJECT|ORGANIZATION|CONCEPT',
        'subject_evidence_id':'N:T000 or actual visual evidence ID','predicate':'one explicit content assertion',
        'qualifiers':'time, negation, uncertainty, quantity/unit, reference frame and conditions; empty if absent',
        'evidence_ids':['actual N evidence IDs'],'observation':'original visible content if image used, otherwise empty'}]}
    prompt='''Extract up to 10 independent content facts ONLY from this single node. Read all members, including the final spans.
Never use another node or prior knowledge. A bare identifier, logo or publication mark is not a fact; return an empty list for it.
Keep distinct objects/events separate. An instrument or institution is not a particular occurrence.
Do not infer person identity from a portrait or diagram purpose from visual style. Preserve scientific qualifiers.
Subject must be a literal mention at subject_evidence_id; image subjects must be visibly justified.
Unknown anaphora remains unresolved rather than inventing a named entity. Return this schema: '''+json.dumps(schema)+'\n'+json.dumps(public,ensure_ascii=False)
    extracted=call_json(model,prompt,images,lambda v:validate_facts(v,lookup),2200)
    supported=[];support=None
    if extracted['valid'] and extracted['bound']:
        facts=extracted['bound']
        # Per-node check still never sees a candidate partner or relation outcome.
        support_prompt='''Check each proposed fact against ONLY this node's originals. A fact is supported only if its subject,
assertion and ALL qualifiers are grounded. Do not infer a specific event from its instrument, a project from its institution,
or fill missing identity/conditions from world knowledge. Return {"checks":[{"fact_id":"F000","status":"SUPPORTED|UNSUPPORTED|UNCERTAIN","reason":"grounded explanation"}]}.
Review every fact exactly once.\n'''+json.dumps({'evidence':public,'facts':facts},ensure_ascii=False)
        def validate_support(v):
            checks=v.get('checks')
            if not isinstance(checks,list) or len(checks)!=len(facts):raise ValueError('support_coverage')
            if Counter(c.get('fact_id') for c in checks)!=Counter(f['id'] for f in facts):raise ValueError('support_ids')
            for c in checks:
                if c.get('status') not in {'SUPPORTED','UNSUPPORTED','UNCERTAIN'} or not isinstance(c.get('reason'),str):raise ValueError('support_schema')
            return checks
        support=call_json(model,support_prompt,images,validate_support,1800)
        if support['valid']:
            ids={c['fact_id'] for c in support['bound'] if c['status']=='SUPPORTED'}
            supported=[f for f in facts if f['id'] in ids]
    record={'node_id':node['id'],'input_sha256':fingerprint,'extraction':extracted,'source_check':support,
            'supported_facts':supported,'status':'READY' if extracted['valid'] and (not extracted['bound'] or support and support['valid']) else 'FACT_PENDING',
            'independent_human_validation':False}
    write(path,record);return record


def validate_relation(value,lookups,facts=None):
    if not isinstance(value,dict):raise ValueError('relation_object')
    status=value.get('status')
    if status not in {'ACCEPT','REJECT','UNCERTAIN','INDEX_ONLY'}:raise ValueError('status_invalid')
    if not isinstance(value.get('reason'),str) or not value['reason'].strip():raise ValueError('reason_required')
    if status not in {'ACCEPT','INDEX_ONLY'}:return {'anchors':{}}
    kind=value.get('relation_type')
    if kind not in RELATIONS:raise ValueError('relation_type_invalid')
    if (kind=='ORGANIZATION_CONTEXT')!=(status=='INDEX_ONLY'):raise ValueError('organization_context_is_index_only')
    direction=value.get('direction')
    if kind in SYMMETRIC and direction!='SYMMETRIC':raise ValueError('symmetric_required')
    if kind in DIRECTED and direction not in {'A_TO_B','B_TO_A'}:raise ValueError('directed_required')
    bound={};chosen={}
    for label in ['A','B']:
        if facts is not None:
            fid=value.get('fact_'+label.lower());available={f['id']:f for f in facts[label]}
            if not isinstance(fid,str) or fid not in available:raise ValueError('fact_not_in_endpoint')
            chosen[label]=available[fid]
            aid=value.get('anchor_'+label.lower())
            if aid not in chosen[label]['evidence_ids']:raise ValueError('anchor_not_supporting_selected_fact')
        aid=value.get('anchor_'+label.lower())
        if not isinstance(aid,str) or aid not in lookups[label]:raise ValueError('anchor_not_in_endpoint')
        anchor=dict(lookups[label][aid])
        if anchor['kind']=='VISUAL':
            obs=value.get('observation_'+label.lower())
            if not isinstance(obs,str) or len(obs.strip())<8:raise ValueError('visual_observation_required')
            anchor['observation']=obs
        bound['anchor_'+label.lower()]=anchor
    if kind=='CAPTION_FOR':
        source,target=('anchor_a','anchor_b') if direction=='A_TO_B' else ('anchor_b','anchor_a')
        if bound[source]['kind']!='TEXT' or bound[target]['kind']!='VISUAL':raise ValueError('caption_requires_text_to_original_visual')
    if facts is not None:
        required={'SAME_EVENT':{'EVENT'},'SAME_PROJECT':{'PROJECT'},'SAME_OBJECT':{'PERSON','OBJECT'}}.get(kind)
        if required and any(chosen[k]['subject_kind'] not in required for k in ['A','B']):raise ValueError('identity_subject_kind_mismatch')
    return {'anchors':bound,'selected_facts':chosen}


def endpoint_facts(record,label):
    return [{**f,'evidence_ids':[label+i[1:] for i in f['evidence_ids']],
             'subject_evidence_id':label+f['subject_evidence_id'][1:]} for f in record['supported_facts']]


def judge_pair(model,pair,nodes,pol,out,facts=None):
    targets,lookup,images=request_targets(pair,nodes,pol,out)
    schema={'status':'ACCEPT|REJECT|UNCERTAIN|INDEX_ONLY','relation_type':'one specified type, or NONE',
            'direction':'A_TO_B|B_TO_A|SYMMETRIC for positive/index relationships; NONE for no relationship',
            'reason':'explain both endpoint facts and the bridge; do not borrow content',
            'anchor_a':'actual A evidence ID or empty for no relationship','anchor_b':'actual B evidence ID or empty for no relationship',
            'observation_a':'visible content if visual, otherwise empty','observation_b':'visible content if visual, otherwise empty'}
    if facts is not None:
        schema.update(fact_a='one supplied A fact ID or empty for no relationship',fact_b='one supplied B fact ID or empty for no relationship')
    prompt=SPEC+'\nReturn '+json.dumps(schema)+'\n'+json.dumps({'targets':targets},ensure_ascii=False)
    if facts is not None:
        prompt+='\nUse only independently source-checked facts below for a positive relationship. Originals are available to check them, not to invent missing facts. If no supported facts are available but source content remains assessable, return UNCERTAIN rather than assuming no relationship. '+json.dumps(facts,ensure_ascii=False)
    fingerprint=digest({'targets':targets,'anchors':lookup,'facts':facts,'spec':SPEC})
    record=call_json(model,prompt,images,lambda v:validate_relation(v,lookup,facts),1000)
    value=record['value'];bound=record['bound'] or {}
    return {**record,'pair':{**pair,'proposed_relation_type':pair['relation_type'],'relation_type':value.get('relation_type',pair['relation_type'])},
            'status':value['status'] if record['valid'] else 'FORMAT_PENDING',
            'anchors':bound.get('anchors',{}),'selected_facts':bound.get('selected_facts',{}),'input_sha256':fingerprint}


def run(out):
    from run_own_corpus_edges import llm
    check(out);manifest=read(out/'manifest.json')
    if manifest['script_sha256']!=sha(__file__) or manifest['typed_helper_sha256']!=sha(Path(__file__).with_name('run_typed_node_edges.py')):raise ValueError('experiment_code_changed')
    queue=rows(out/'verification_queue.jsonl');nodes={n['id']:n for n in rows(out/'units.jsonl')};pol=read(out/'eligibility.json');model=llm()
    ids=sorted({p[k] for p in queue for k in ['source','target']});facts={}
    for i,nid in enumerate(ids):
        facts[nid]=extract_node(model,nodes[nid],pol[nid],out)
        print(json.dumps({'facts_done':i+1,'total_nodes':len(ids),'status':facts[nid]['status'],'supported':len(facts[nid]['supported_facts'])}),flush=True)
    for arm in ['direct_control','decisions']:
        for i,pair in enumerate(queue):
            path=out/arm/f'{pair["pair_id"]}.json'
            if path.exists():continue
            fs=None if arm=='direct_control' else {label:endpoint_facts(facts[pair[key]],label) for label,key in [('A','source'),('B','target')]}
            if arm=='decisions' and any(facts[pair[k]]['status']!='READY' for k in ['source','target']):
                d={'pair':pair,'valid':False,'value':{},'status':'FACT_PENDING','errors':['endpoint_fact_pipeline_incomplete'],'anchors':{}}
            else:d=judge_pair(model,pair,nodes,pol,out,fs)
            write(path,d);print(json.dumps({'arm':arm,'judged':i+1,'total':len(queue),'status':d['status']}),flush=True)
    write(out/'verification_manifest.json',{'queue':len(queue),'complete':True,'independent_human_evaluation':False,
          'artifact_sha256':{str(p.relative_to(out)):sha(p) for folder in ['facts','direct_control','decisions'] for p in sorted((out/folder).glob('*.json'))}})
    report(out)


def report(out):
    queue=rows(out/'verification_queue.jsonl');old={d['pair']['pair_id']:d for d in rows(out/'previous_decisions.jsonl')};comparison=[]
    for pair in queue:
        entry={'pair':pair,'previous':old[pair['pair_id']]}
        for arm in ['direct_control','decisions']:
            path=out/arm/f'{pair["pair_id"]}.json';entry[arm]=read(path) if path.exists() else {'status':'NOT_RUN'}
        comparison.append(entry)
    jsonl(out/'paired_comparison.jsonl',comparison)
    summary={'pairs':len(queue),'nodes':len({p[k] for p in queue for k in ['source','target']}),
        'direct_control_statuses':dict(Counter(e['direct_control']['status'] for e in comparison)),
        'fact_arm_statuses':dict(Counter(e['decisions']['status'] for e in comparison)),
        'transitions':dict(Counter(e['direct_control']['status']+' -> '+e['decisions']['status'] for e in comparison)),
        'complete':(out/'verification_manifest.json').exists(),'independent_human_evaluation':False,
        'development_sample':True,'retrieval_quality_evaluated':False}
    write(out/'comparison_summary.json',summary)
    graph_report(out)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=['prepare','run','report'])
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--limit',type=int,default=80);args=parser.parse_args()
    if args.stage=='prepare':prepare(args.output,args.source,args.limit)
    else:check(args.output);globals()[args.stage](args.output)
