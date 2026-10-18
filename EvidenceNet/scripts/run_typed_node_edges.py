#!/usr/bin/env python3
"""Relation-routed graph pilot on immutable multimodal evidence nodes."""
import argparse
from collections import Counter, defaultdict
import gc
import hashlib
import json
from pathlib import Path
import random
import re
import shutil

from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, check, scope
from verify_node_context_v3 import verification_policy, source_spans
from node_context_policy import structured_pairs
from node_context_coreference import duplicate_caption

VISION_MODEL=ROOT/'external/models/Qwen2.5-VL-7B-Instruct'
SOURCE=ROOT/'EvidenceNet/output/node_context_edges_v3_20261011'
ENTITY_STOP=set('FIG FIGS TABLE TABLES SNR PDF PDFs CNN FFN BH BBH NS GR GW LRT FAR CL GHG EU USA US UK MD DOI ISBN'.split())


def allowed_members(node,policy):
    allowed={(m['member_id'],m['kind']) for m in policy['members'] if m['eligible']}
    return [m for m in node['members'] if (m['id'],m['kind']) in allowed]


def entities(node,policy):
    """Literal source identifiers, not asserted entity disambiguation."""
    result=[]
    patterns=[r'\b[A-Z]{1,6}[-]?\d{4,12}[A-Za-z0-9-]*\b',
              r'\b[A-Z][A-Z0-9-]{2,15}\b',
              r'\b[A-Z][a-z]{2,}(?:\s+(?:[A-Z][a-z]{2,}|of|the|and)){1,4}\b']
    for m in allowed_members(node,policy):
        if m['kind']!='atom' or m.get('role')=='equ':continue
        for pattern in patterns:
            for match in re.finditer(pattern,m['text']):
                name=match[0].strip();key=re.sub(r'\s+',' ',name).casefold()
                if name in ENTITY_STOP or re.fullmatch(r'(?:FIG|TABLE|EQ)-?\d+',name):continue
                result.append({'key':key,'name':name,'member_id':m['id'],
                               'char_start':match.start(),'char_end':match.end()})
    return result


def catalog(node,policy,label,out):
    """Short selectable IDs; raw anchors retain a preceding context overlap."""
    _,spans=source_spans(node,policy,label)
    public=[];lookup={}
    for span in spans.values():
        m=next(m for m in node['members'] if m['kind']=='atom' and m['id']==span['member_id'])
        start=max(0,span['char_start']-120);end=span['char_end']
        padding=list(re.finditer(r'(?:~\s*){5,}',m['text'][start:span['char_start']]))
        if padding:start+=padding[-1].end()
        key=f'{label}:T{len(lookup):03d}'
        anchor={'kind':'TEXT','member_id':m['id'],'quote':m['text'][start:end],
                'char_start':start,'char_end':end,'member_sha256':hashlib.sha256(m['text'].encode()).hexdigest()}
        lookup[key]=anchor;public.append({'id':key,'kind':'TEXT','text':re.sub(r'\s+',' ',anchor['quote']).strip()})
    for m in allowed_members(node,policy):
        if m['kind']=='visual' and m.get('crop'):
            key=f'{label}:V{len(lookup):03d}'
            lookup[key]={'kind':'VISUAL','member_id':m['id'],'crop':m['crop'],'crop_sha256':sha(out/m['crop'])}
            public.append({'id':key,'kind':'VISUAL','crop':m['crop']})
    return public,lookup


def build_candidates(nodes,policies,reading,old_scored,visual_pairs=()):
    pool={}
    def add(a,b,kind,route,rank=0,entity=None):
        if a==b or not policies[a]['eligible'] or not policies[b]['eligible']:return
        if duplicate_caption(nodes[a],nodes[b],policies):return
        a,b=sorted((a,b));key=(a,b,kind)
        p=pool.setdefault(key,{'source':a,'target':b,'relation_type':kind,'scope':scope(nodes[a],nodes[b]),
                              'routes':[],'rank_signal':0,'entity_hints':[]})
        if route not in p['routes']:p['routes'].append(route)
        p['rank_signal']=max(p['rank_signal'],float(rank))
        if entity and entity not in p['entity_hints']:p['entity_hints'].append(entity)
    structured,issues=structured_pairs(nodes,policies,reading)
    references=[]
    for p in structured:
        references.extend(p.get('references',[]))
        if 'caption_geometry' in p['routes']:add(p['source'],p['target'],'CAPTION_FOR','caption_geometry',1)
        if 'formula_introducer' in p['routes']:add(p['source'],p['target'],'EXPLAINS','formula_introducer',1)
        elif 'reading_neighbor' in p['routes']:add(p['source'],p['target'],'EXPLAINS','reading_neighbor',0.5)
    index=defaultdict(dict)
    for n in nodes.values():
        for e in entities(n,policies[n['id']]):index[e['key']].setdefault(n['id'],[]).append(e)
    for key,hits in sorted(index.items()):
        ids=sorted(hits)
        if len(ids)<2:continue
        # Per-entity scope budgets; lexical context ranks only the candidate pool.
        for a in ids:
            for family in ['intra_article','cross_article','cross_document','same_document_article_unresolved']:
                candidates=[b for b in ids if b!=a and scope(nodes[a],nodes[b])==family]
                ta=set(re.findall(r'\w+',nodes[a]['text'].lower()))
                candidates.sort(key=lambda b:(-len(ta&set(re.findall(r'\w+',nodes[b]['text'].lower()))),b))
                for b in candidates[:6]:add(a,b,'SAME_ENTITY','source_entity_index',1,{'key':key,'name':hits[a][0]['name']})
    for p in old_scored:
        if p['source'] not in nodes or p['target'] not in nodes:continue
        score=max([x['score'] for x in p.get('alignments',[])] or [0])
        add(p['source'],p['target'],'RELATED_CONTENT','text_or_description_retrieval',score)
    for p in visual_pairs:add(p['source'],p['target'],'RELATED_CONTENT','original_crop_vision',p['score'])
    result=[]
    for _,p in sorted(pool.items()):
        p['pair_id']=f'TYPED_{len(result):05d}';result.append(p)
    return result,references,index,issues


def select_queue(candidates,nodes,old_queue,limit=320,seed=20261012):
    """Regression pairs plus new stratified routes, without using audit labels."""
    rng=random.Random(seed);selected={};degree=Counter()
    def add(p,cohort):
        if len(selected)>=limit:return
        if p['pair_id'] not in selected:
            selected[p['pair_id']]={**p,'cohort':cohort}
            degree[p['source']]+=1;degree[p['target']]+=1
    by_pair=defaultdict(list)
    for p in candidates:by_pair[tuple(sorted((p['source'],p['target'])))].append(p)
    for old in old_queue:
        choices=by_pair.get(tuple(sorted((old['source'],old['target']))),[])
        if choices:
            priority={'CAPTION_FOR':0,'SAME_ENTITY':1,'EXPLAINS':2,'RELATED_CONTENT':3}
            add(min(choices,key=lambda p:(priority[p['relation_type']],p['pair_id'])),'old_pair_regression')
    buckets=defaultdict(list)
    for p in candidates:
        visual=any(nodes[p[k]]['visual_count'] for k in ['source','target'])
        strength='lower' if p['rank_signal']<0.8 else 'higher'
        buckets[(p['relation_type'],p['scope'],visual,strength)].append(p)
    queues=[]
    for key,items in sorted(buckets.items()):
        rng.shuffle(items)
        # Prefer unrepresented nodes within each independent route/modality stratum.
        items.sort(key=lambda p:degree[p['source']]+degree[p['target']],reverse=True)
        queues.append(items)
    while len(selected)<limit and any(queues):
        for bucket in queues:
            while bucket and bucket[-1]['pair_id'] in selected:bucket.pop()
            if bucket:add(bucket.pop(),'new_stratified')
    return list(selected.values())


def prepare(out,source):
    check(source)
    if out.exists():raise ValueError('Requires new output directory')
    out.mkdir(parents=True)
    names=['pages.json','units.jsonl','reading_edges.jsonl','issues.jsonl','scored_pairs.jsonl']
    for name in names:shutil.copy2(source/name,out/name)
    shutil.copy2(source/'verification_queue.jsonl',out/'old_verification_queue.jsonl')
    shutil.copytree(source/'assets',out/'assets')
    nodes=rows(out/'units.jsonl');pol=verification_policy(nodes);write(out/'eligibility.json',pol)
    pairs,refs,index,issues=build_candidates({n['id']:n for n in nodes},pol,rows(out/'reading_edges.jsonl'),rows(out/'scored_pairs.jsonl'))
    jsonl(out/'candidate_hypotheses.jsonl',pairs);jsonl(out/'source_references.jsonl',refs)
    write(out/'entity_index.json',index);jsonl(out/'reference_issues.jsonl',issues)
    manifest=read(source/'manifest.json')
    manifest.update(experiment='typed_evidence_node_edges_v1',source_experiment=str(source.resolve()),
                    snapshot_files={n:sha(out/n) for n in names+['old_verification_queue.jsonl','eligibility.json']},
                    architecture='structural rules + source entity index + semantic/visual routes + typed verification',
                    queue_limit=320,seed=20261012,independent_human_evaluation=False,
                    visual_encoder=str(VISION_MODEL),visual_feature_status='exploratory pooled vision features, not calibrated retrieval embeddings')
    (out/'code_snapshot').mkdir()
    for name in ['run_typed_node_edges.py','verify_node_context_v3.py','node_context_coreference.py','node_context_policy.py','run_node_context_edges.py']:
        shutil.copy2(Path(__file__).parent/name,out/'code_snapshot'/name)
    manifest['code_snapshot_sha256']={p.name:sha(p) for p in (out/'code_snapshot').glob('*.py')}
    write(out/'manifest.json',manifest)
    coverage(out,pairs)


def vision_candidates(out):
    import numpy as np
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText,AutoProcessor
    if not torch.cuda.is_available():raise RuntimeError('GPU required')
    nodes=rows(out/'units.jsonl');pol=read(out/'eligibility.json');items=[]
    for node in nodes:
        for m in allowed_members(node,pol[node['id']]):
            if m['kind']=='visual' and m.get('crop'):items.append({'node_id':node['id'],'member_id':m['id'],'crop':m['crop']})
    processor=AutoProcessor.from_pretrained(VISION_MODEL,local_files_only=True)
    model=AutoModelForImageTextToText.from_pretrained(VISION_MODEL,local_files_only=True,dtype=torch.bfloat16,device_map='auto').eval()
    device=next(model.model.visual.parameters()).device;vectors=[]
    for i,item in enumerate(items):
        with Image.open(out/item['crop']) as source:
            im=source.convert('RGB');im.thumbnail((768,768))
            inputs=processor.image_processor(images=[im],return_tensors='pt').to(device)
            with torch.inference_mode():
                features=model.get_image_features(pixel_values=inputs['pixel_values'],image_grid_thw=inputs['image_grid_thw'],return_dict=True).pooler_output
                v=features[0].float().mean(dim=0);v=torch.nn.functional.normalize(v,dim=0)
            vectors.append(v.cpu().numpy());im.close()
        print(json.dumps({'vision_crops':i+1,'total':len(items)}),flush=True)
    del model;gc.collect();torch.cuda.empty_cache()
    matrix=np.asarray(vectors);np.save(out/'crop_vectors.npy',matrix);jsonl(out/'crop_views.jsonl',items)
    similarity=matrix@matrix.T;ns={n['id']:n for n in nodes};pool={}
    for i,item in enumerate(items):
        counts=Counter();seen=set()
        for j in np.argsort(-similarity[i],kind='stable'):
            a,b=item['node_id'],items[j]['node_id'];family=scope(ns[a],ns[b])
            if a==b or b in seen or counts[family]>=3:continue
            seen.add(b);counts[family]+=1;key=tuple(sorted((a,b)))
            value={'source':key[0],'target':key[1],'score':float(similarity[i,j])}
            if value['score']>pool.get(key,{'score':-1})['score']:pool[key]=value
    jsonl(out/'vision_pairs.jsonl',pool.values())
    pairs,refs,index,issues=build_candidates(ns,pol,rows(out/'reading_edges.jsonl'),rows(out/'scored_pairs.jsonl'),list(pool.values()))
    jsonl(out/'candidate_hypotheses.jsonl',pairs)
    queue=select_queue(pairs,ns,rows(out/'old_verification_queue.jsonl'))
    jsonl(out/'verification_queue.jsonl',queue)
    write(out/'candidate_manifest.json',{'candidate_sha256':sha(out/'candidate_hypotheses.jsonl'),
        'queue_sha256':sha(out/'verification_queue.jsonl'),'crop_vectors_sha256':sha(out/'crop_vectors.npy'),
        'vision_pairs':len(pool),'vision_crops':len(items),'queue':len(queue)})
    coverage(out,pairs,queue)


def coverage(out,pairs,queue=()):
    nodes=rows(out/'units.jsonl');pol=read(out/'eligibility.json')
    summary={'nodes':len(nodes),'eligible_nodes':sum(p['eligible'] for p in pol.values()),
             'candidate_hypotheses':len(pairs),'candidate_nodes':len({p[k] for p in pairs for k in ['source','target']}),
             'candidate_types':dict(Counter(p['relation_type'] for p in pairs)),
             'candidate_scopes':dict(Counter(p['scope'] for p in pairs)),
             'queue':len(queue),'queue_nodes':len({p[k] for p in queue for k in ['source','target']}),
             'queue_types':dict(Counter(p['relation_type'] for p in queue)),
             'queue_scopes':dict(Counter(p['scope'] for p in queue)),
             'queue_cohorts':dict(Counter(p['cohort'] for p in queue)),
             'uncovered_eligible_nodes':[n['id'] for n in nodes if pol[n['id']]['eligible'] and not any(n['id'] in [p['source'],p['target']] for p in pairs)],
             'production_modified':False,'retrieval_quality_evaluated':False}
    write(out/'coverage.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='uncovered_eligible_nodes'}),flush=True)


CRITERIA={
 'SAME_ENTITY':'Decide if BOTH nodes refer to the same specific event, project, object, person or organization and EACH states a content fact about it. Complementary facts, different measurement frames, or project results versus leadership are valid. Bare names, logos, generic topic/task categories and unresolved identity are not. This is a contextual coreference link, not entailment or numerical agreement. Entity hints only nominate candidates; verify identity and facts in originals.',
 'CAPTION_FOR':'Decide whether one endpoint is a caption directly describing the ORIGINAL visual at the other endpoint. Do not borrow a third image. A neighbouring caption for another image is insufficient. Direction is caption to visual.',
 'EXPLAINS':'Decide whether one endpoint explains/defines/elaborates the specific formula, mechanism, claim or term at the other. A general-to-specific formula relation or formula-to-definition correspondence qualifies. Mere reading adjacency or common topic does not. Direction is explanation to explained content.',
 'RELATED_CONTENT':'Decide whether both endpoints have a specific content correspondence (shared measurement, method/application, explicit comparison or compatible concrete finding). Broad topic, visual style, portraits, generic task labels, brand logos and similar descriptions do not qualify. A weak possible association should be UNCERTAIN. This edge is symmetric.'}


def request_targets(pair,nodes,policies,out):
    targets=[];lookups={};images=[]
    for label,key in [('A','source'),('B','target')]:
        public,lookup=catalog(nodes[pair[key]],policies[pair[key]],label,out)
        for entry in public:
            if entry['kind']=='VISUAL':
                images.append(str(out/entry.pop('crop')));entry['image_index']=len(images)
        targets.append({'label':label,'evidence':public});lookups[label]=lookup
    return targets,lookups,images


def validate_response(value,lookups,kind):
    if not isinstance(value,dict):return ['response_not_object']
    if value.get('status') not in {'ACCEPT','REJECT','UNCERTAIN'}:return ['status_invalid']
    if not isinstance(value.get('reason'),str) or not value['reason'].strip():return ['reason_missing']
    if value.get('direction') not in {'A_TO_B','B_TO_A','SYMMETRIC'}:return ['direction_invalid']
    if kind in {'SAME_ENTITY','RELATED_CONTENT'} and value['direction']!='SYMMETRIC':return ['symmetric_relation_required']
    if kind in {'CAPTION_FOR','EXPLAINS'} and value['status']=='ACCEPT' and value['direction']=='SYMMETRIC':return ['directed_relation_required']
    for label in ['A','B']:
        ref=value.get('anchor_'+label.lower())
        if not isinstance(ref,str) or ref not in lookups[label]:return ['anchor_not_in_endpoint_catalog']
        anchor=lookups[label][ref]
        if anchor['kind']=='VISUAL':
            obs=value.get('observation_'+label.lower())
            if not isinstance(obs,str) or len(obs.strip())<8:return ['visual_observation_missing']
            if value['status']=='ACCEPT' and re.search(r'\b(?:logo|navigation|watermark|branding)\b',obs,re.I):return ['furniture_is_not_positive_evidence']
    return []


def judge(model,pair,targets,lookups,images,audit=False):
    from evidence_graph.llm_client import extract_json
    schema={'status':'ACCEPT|REJECT|UNCERTAIN','reason':'one grounded sentence',
            'direction':'A_TO_B|B_TO_A|SYMMETRIC','anchor_a':'choose one A evidence ID',
            'anchor_b':'choose one B evidence ID','observation_a':'visible observation or empty string',
            'observation_b':'visible observation or empty string'}
    prompt=CRITERIA[pair['relation_type']]+'\nInspect only these originals; generated descriptions are not supplied. '
    prompt+='Return ALL fields in this JSON schema. ACCEPT and REJECT both require actual endpoint anchors; use UNCERTAIN if content cannot be assessed. '
    if audit:prompt='Blind second assessment: identify the strongest concrete correspondence AND any plausible alternative interpretation in your reason. Do not assume a candidate is true. '+prompt
    prompt+=json.dumps(schema)+'\n'+json.dumps({'relation_type':pair['relation_type'],'candidate_identifiers':pair['entity_hints'],'targets':targets},ensure_ascii=False)
    attempts=[];value={};errors=[]
    for attempt in range(2):
        request=prompt
        if attempt:request+='\nCorrect errors '+json.dumps(errors)+'. Previous output: '+attempts[-1]['raw']
        raw=model.generate_raw_with_images('Judge the specified relationship from original evidence. JSON only.',request,images,700).raw
        attempts.append({'raw':raw,'prompt':request})
        try:value=extract_json(raw);errors=validate_response(value,lookups,pair['relation_type'])
        except (ValueError,TypeError,KeyError) as exc:errors=[str(exc)]
        if not errors:break
    anchors={}
    if not errors:
        for label in ['A','B']:
            a=dict(lookups[label][value['anchor_'+label.lower()]])
            if a['kind']=='VISUAL':a['observation']=value['observation_'+label.lower()]
            anchors['anchor_'+label.lower()]=a
    return {'valid':not errors,'value':value,'errors':errors,'anchors':anchors,'attempts':attempts,
            'status':'FORMAT_PENDING' if errors else value['status']}


def verify(out):
    from run_own_corpus_edges import llm,MODEL
    check(out);cm=read(out/'candidate_manifest.json')
    if cm['candidate_sha256']!=sha(out/'candidate_hypotheses.jsonl') or cm['queue_sha256']!=sha(out/'verification_queue.jsonl'):raise ValueError('Candidate snapshot changed')
    nodes={n['id']:n for n in rows(out/'units.jsonl')};pol=read(out/'eligibility.json');queue=rows(out/'verification_queue.jsonl');model=llm()
    for i,pair in enumerate(queue):
        path=out/'decisions'/f'{pair["pair_id"]}.json'
        targets,lookups,images=request_targets(pair,nodes,pol,out)
        fingerprint=hashlib.sha256(json.dumps(targets,sort_keys=True).encode()).hexdigest()
        if path.exists():
            if read(path)['input_sha256']!=fingerprint:raise ValueError('Stale decision')
            continue
        d=judge(model,pair,targets,lookups,images)
        write(path,{**d,'pair':pair,'input_sha256':fingerprint,'model':str(MODEL),'script_sha256':sha(__file__)})
        print(json.dumps({'verified':i+1,'total':len(queue),'status':d['status']}),flush=True)
    # Blind repeat samples ACCEPT and REJECT, balanced across relation/scope/modality.
    buckets=defaultdict(list)
    for pair in queue:
        d=read(out/'decisions'/f'{pair["pair_id"]}.json')
        if d['status'] in {'ACCEPT','REJECT'}:
            visual=any(nodes[pair[k]]['visual_count'] for k in ['source','target'])
            buckets[(d['status'],pair['relation_type'],pair['scope'],visual)].append(pair)
    rng=random.Random(20261012);audit=[]
    for bucket in buckets.values():rng.shuffle(bucket)
    while len(audit)<64 and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(audit)<64:audit.append(buckets[key].pop())
    jsonl(out/'audit_queue.jsonl',audit)
    for pair in audit:
        path=out/'repeat_decisions'/f'{pair["pair_id"]}.json'
        if path.exists():continue
        targets,lookups,images=request_targets(pair,nodes,pol,out)
        # A blind re-evaluation by the same model is a consistency check, not independent labels.
        result=judge(model,pair,targets,lookups,images,audit=True)
        write(path,{**result,'pair':pair,'review_status':'SAME_MODEL_BLIND_REPEAT_NOT_HUMAN_VALIDATION'})
    ds=[read(out/'decisions'/f'{p["pair_id"]}.json') for p in queue]
    write(out/'verification_manifest.json',{'queue':len(queue),'statuses':dict(Counter(d['status'] for d in ds)),
        'audit_queue':len(audit),'queue_sha256':sha(out/'verification_queue.jsonl'),
        'decision_files':{str(p.relative_to(out)):sha(p) for folder in ['decisions','repeat_decisions'] for p in sorted((out/folder).glob('*.json'))},
        'independent_human_evaluation':False})
    report(out)


def report(out):
    from build_own_corpus_edge_viewer import render
    nodes=rows(out/'units.jsonl');ns={n['id']:n for n in nodes};edges=[]
    for r in rows(out/'source_references.jsonl'):
        if any(e['source']==r['source'] and e['target']==r['target'] and e['type']=='REFERENCES' for e in edges):continue
        edges.append({'id':f'REF_{len(edges):04d}','source':r['source'],'target':r['target'],'type':'REFERENCES',
            'family':'semantic','direction':'A_TO_B','scope':scope(ns[r['source']],ns[r['target']]),
            'status':'SOURCE_MARKER_RESOLVED','representation_basis':'source_text_only','visual_verification':'NOT_APPLICABLE',
            'anchor_a':{'kind':'TEXT','quote':r['source_quote'],'member_id':r['source_member']},
            'anchor_b':{'kind':'TEXT','quote':r['target_quote'],'member_id':r['target_member']},'decision':{'reason':r['verification']}})
    decisions=[];states=Counter();disagreements=[]
    for path in sorted((out/'decisions').glob('*.json')):
        d=read(path);p=d['pair'];state=d['status'];repeat=out/'repeat_decisions'/path.name
        if repeat.exists():
            second=read(repeat)
            if second['status']!=state:
                disagreements.append({'pair_id':p['pair_id'],'first':state,'repeat':second['status']});state='REVIEW_PENDING'
        states[state]+=1
        decisions.append({'pair':p,'valid':d['valid'],'value':{**d['value'],'status':state},'errors':d['errors']})
        if state!='ACCEPT':continue
        a,b=p['source'],p['target'];direction=d['value']['direction'];anchors=d['anchors']
        if direction=='B_TO_A':a,b=b,a;anchors={'anchor_a':anchors['anchor_b'],'anchor_b':anchors['anchor_a']}
        visual=any(x['kind']=='VISUAL' for x in anchors.values())
        edges.append({'id':p['pair_id']+'::'+p['relation_type'],'source':a,'target':b,'type':p['relation_type'],
            'family':'semantic','scope':p['scope'],'direction':'SYMMETRIC' if direction=='SYMMETRIC' else 'A_TO_B',
            'status':'MODEL_SOURCE_CHECKED','human_review':'PENDING','representation_basis':'original_crop_and_source' if visual else 'source_text_only',
            'visual_verification':'MODEL_CROP_CHECKED' if visual else 'NOT_USED',**anchors,'routes':p['routes'],
            'decision':{'reason':d['value']['reason']}})
    aggregates=defaultdict(list)
    for edge in edges:
        aa,bb=ns[edge['source']].get('article_id'),ns[edge['target']].get('article_id')
        if aa and bb and aa!=bb and edge['scope'] in {'cross_document','cross_article'}:
            aggregates[(aa,bb,edge['type'])].append(edge['id'])
    article_edges=[{'source_article':a,'target_article':b,'type':kind,'supporting_edge_ids':ids,
                    'status':'AGGREGATE_OF_NODE_EDGES','human_review':'PENDING'}
                   for (a,b,kind),ids in sorted(aggregates.items())]
    jsonl(out/'article_edges.jsonl',article_edges)
    reading=rows(out/'reading_edges.jsonl');coverage_data=read(out/'coverage.json')
    summary={**{k:v for k,v in coverage_data.items() if k!='uncovered_eligible_nodes'},
        'pages':len(read(out/'pages.json')),'reading_edges':len(reading),'semantic_edges':len(edges),'article_edges':len(article_edges),'decisions':len(decisions),'candidates':coverage_data['queue'],
        'semantic_types':dict(Counter(e['type'] for e in edges)),'semantic_scopes':dict(Counter(e['scope'] for e in edges)),
        'decision_states':dict(states),'repeat_disagreements':len(disagreements),
        'complete':(out/'verification_manifest.json').exists(),'production_modified':False,'retrieval_quality_evaluated':False}
    jsonl(out/'semantic_edges.jsonl',edges);jsonl(out/'pending_repeat_disagreements.jsonl',disagreements)
    write(out/'summary.json',summary)
    payload={'pages':read(out/'pages.json'),'nodes':nodes,'reading':reading,'semantic':edges,'article_edges':article_edges,
             'decisions':decisions,'summary':summary,'issues':rows(out/'issues.jsonl')}
    write(out/'graph_data.json',payload);render(out,payload);print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['prepare','candidates','verify','report'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,default=SOURCE);args=p.parse_args()
    if args.stage=='prepare':prepare(args.output,args.source)
    else:
        check(args.output)
        if args.stage=='candidates':vision_candidates(args.output)
        else:globals()[args.stage](args.output)
