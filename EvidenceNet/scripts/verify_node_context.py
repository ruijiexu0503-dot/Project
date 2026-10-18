#!/usr/bin/env python3
"""Small source/crop verification pilot; reranker scores never accept edges."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from run_node_context_edges import read, rows, write, jsonl, sha, check, scope


def select_queue(scored, views, limit=120):
    """Deterministic scope quotas and structural routes, without audit labels."""
    def score(p):
        source=[x['score'] for x in p['alignments'] if views[x['a']]['kind']==views[x['b']]['kind']=='source_text']
        return max(source or [x['score'] for x in p['alignments']] or [0])
    ranked=sorted(scored,key=lambda p:(-score(p),p['pair_id']))
    selected={}
    def add(p):
        if len(selected)<limit:selected.setdefault(p['pair_id'],p)
    structural=[p for p in ranked if {'formula_introducer','caption_geometry'} & set(p['routes'])]
    for p in structural[:30]:add(p)
    for family in ['cross_document','cross_article','same_document_article_unresolved','intra_article']:
        for p in [p for p in ranked if p['scope']==family][:20]:add(p)
    for p in ranked:
        if score(p)>=0.8:add(p)
    return list(selected.values())


def validate(value, pair, nodes, policies):
    if not isinstance(value,dict) or value.get('pair_id')!=pair['pair_id']:return ['pair_id_invalid']
    if value.get('status') not in {'ACCEPT','REJECT','UNCERTAIN'}:return ['status_invalid']
    if not isinstance(value.get('reason'),str) or not value['reason'].strip():return ['reason_missing']
    if value['status']!='ACCEPT':return []
    for field,nid in [('anchor_a',pair['source']),('anchor_b',pair['target'])]:
        anchor=value.get(field,{})
        if not isinstance(anchor,dict):return ['anchor_invalid']
        allowed={(m['member_id'],m['kind']) for m in policies[nid]['members'] if m['eligible']}
        members=[m for m in nodes[nid]['members'] if (m['id'],m['kind']) in allowed and m['id']==anchor.get('member_id')]
        if anchor.get('kind')=='TEXT':
            q=anchor.get('quote','')
            if not isinstance(q,str) or len(q.strip())<8 or not any(m['kind']=='atom' and q in m['text'] for m in members):return ['quote_not_in_eligible_source_member']
        elif anchor.get('kind')=='VISUAL':
            obs=anchor.get('observation','')
            if not isinstance(obs,str) or len(obs.strip())<8 or not any(m['kind']=='visual' and m.get('crop') for m in members):return ['visual_anchor_invalid']
        else:return ['anchor_kind_invalid']
    return []


def verify(out):
    from run_own_corpus_edges import llm, MODEL
    from evidence_graph.llm_client import extract_json
    check(out)
    scored=rows(out/'scored_pairs.jsonl');views=rows(out/'views.jsonl')
    if read(out/'score_manifest.json')['scored_sha256']!=sha(out/'scored_pairs.jsonl'):raise ValueError('Scored snapshot changed')
    nodes={n['id']:n for n in rows(out/'units.jsonl')};policies=read(out/'eligibility.json')
    queue=select_queue(scored,views);jsonl(out/'verification_queue.jsonl',queue)
    model=None
    for i,pair in enumerate(queue):
        path=out/'context_decisions'/f"{pair['pair_id']}.json"
        if path.exists():continue
        targets=[];images=[]
        for label,nid in [('A',pair['source']),('B',pair['target'])]:
            allowed={(m['member_id'],m['kind']) for m in policies[nid]['members'] if m['eligible']}
            text=[];visual=[]
            for m in nodes[nid]['members']:
                if (m['id'],m['kind']) not in allowed:continue
                if m['kind']=='atom':text.append({'member_id':m['id'],'text':m['text']})
                elif m.get('crop'):
                    image=out/m['crop']
                    if not image.is_file():raise ValueError('Missing original crop '+str(image))
                    images.append(str(image));visual.append({'member_id':m['id'],'image_index':len(images)})
            targets.append({'label':label,'source_members':text,'original_crops':visual})
        prompt=('Inspect only these two evidence nodes and the supplied original image crops. '
                'Accept a concrete shared scientific claim, named object/event, measurement, definition, '
                'caption correspondence, or explanation between the endpoints. Broad topic similarity, '
                'similar colors/layout/portraits, logos, watermarks, unreadable parser symbols, and a reference '
                'to a third item are insufficient. Identical copies are duplicates: REJECT them. '
                'Do not identify people from appearance. If visual content or a formula is unclear, use UNCERTAIN. '
                'No generated image descriptions or reranker scores are evidence. '
                'Return JSON with pair_id, status (ACCEPT/REJECT/UNCERTAIN), reason. ACCEPT also needs '
                'anchor_a and anchor_b: {kind:TEXT, member_id, quote:exact contiguous source substring} '
                'or {kind:VISUAL, member_id, observation:specific visible correspondence}. '
                'An accepted relation is only symmetric RELATED_CONTEXT; do not infer support or causal direction.\n'+
                json.dumps({'pair_id':pair['pair_id'],'targets':targets},ensure_ascii=False))
        if model is None:model=llm()
        raw=model.generate_raw_with_images('Verify original evidence. JSON only.',prompt,images,900).raw
        try:value=extract_json(raw);errors=validate(value,pair,nodes,policies)
        except (ValueError,TypeError,KeyError) as exc:value={};errors=[str(exc)]
        write(path,{'pair':{'pair_id':pair['pair_id'],'source':pair['source'],'target':pair['target']},
                    'valid':not errors,'value':value,'errors':errors,'raw':raw,'prompt':prompt,
                    'input_sha256':hashlib.sha256(json.dumps(targets,sort_keys=True).encode()).hexdigest(),
                    'model':str(MODEL),'script_sha256':sha(__file__),
                    'review_status':'MODEL_CHECKED_NOT_HUMAN_VALIDATED'})
        print(json.dumps({'verified':i+1,'total':len(queue),'status':value.get('status'),'valid':not errors}),flush=True)
    decisions=[read(out/'context_decisions'/f"{p['pair_id']}.json") for p in queue]
    write(out/'verification_manifest.json',{'queue':len(queue),'scopes':dict(Counter(p['scope'] for p in queue)),
          'statuses':dict(Counter(d['value'].get('status','INVALID') if d['valid'] else 'INVALID' for d in decisions)),
          'scored_sha256':sha(out/'scored_pairs.jsonl'),'queue_sha256':sha(out/'verification_queue.jsonl'),
          'decision_files':{str(p.relative_to(out)):sha(p) for p in sorted((out/'context_decisions').glob('*.json'))},
          'independent_human_evaluation':False})
    from run_node_context_edges import report
    report(out)


def final_edges(out, pairs, nodes):
    result=[];seen=set()
    version=read(out/'manifest.json').get('verifier_version',2)
    policies=read(out/('verification_eligibility.json' if version>=3 else 'eligibility.json'))
    for p in pairs:
        for r in p.get('references',[]):
            if version>=3 and any(not any(m['eligible'] and m['kind']=='atom' and m['member_id']==r[side+'_member'] for m in policies[r[side]]['members']) for side in ['source','target']):continue
            key=(r['source'],r['target'],'REFERENCES')
            if key in seen:continue
            seen.add(key)
            result.append({'id':p['pair_id']+'::REFERENCES::'+str(len(result)),
                'source':r['source'],'target':r['target'],'type':'REFERENCES','family':'semantic',
                'direction':'A_TO_B','scope':scope(nodes[r['source']],nodes[r['target']]),
                'status':'SOURCE_MARKER_RESOLVED','human_review':'PENDING','visual_verification':'NOT_APPLICABLE',
                'representation_basis':'source_text_only','anchor_a':{'kind':'TEXT','member_id':r['source_member'],'quote':r['source_quote']},
                'anchor_b':{'kind':'TEXT','member_id':r['target_member'],'quote':r['target_quote']},
                'routes':p['routes'],'decision':{'reason':r['verification']},'reference':r})
    queued={p['pair_id'] for p in rows(out/'verification_queue.jsonl')} if (out/'verification_queue.jsonl').exists() else set()
    for p in pairs:
        path=out/'context_decisions'/f"{p['pair_id']}.json"
        if p['pair_id'] not in queued or not path.exists():continue
        d=read(path);v=d['value']
        if not d['valid'] or v.get('status')!='ACCEPT' or validate(v,p,nodes,policies):continue
        if version>=3:
            from verify_node_context_v3 import validate_v3
            validator=validate_v3
            if version==4:
                from node_context_coreference import validate_v4, duplicate_caption
                validator=validate_v4
                if duplicate_caption(nodes[p['source']],nodes[p['target']],policies):continue
            if d.get('verifier_version')!=version or d.get('critic',{}).get('status')!='CONFIRM' or validator(v,p,nodes,policies):continue
        if any(d['pair'].get(k)!=p[k] for k in ['pair_id','source','target']):raise ValueError('Decision pair changed')
        anchors={}
        for name,nid in [('anchor_a',p['source']),('anchor_b',p['target'])]:
            anchor=dict(v[name]);kind='atom' if anchor['kind']=='TEXT' else 'visual'
            member=next(m for m in nodes[nid]['members'] if m['id']==anchor['member_id'] and m['kind']==kind)
            if kind=='atom':
                start=anchor.get('char_start') if version>=3 else member['text'].index(anchor['quote'])
                if not isinstance(start,int) or member['text'][start:start+len(anchor['quote'])]!=anchor['quote']:
                    raise ValueError('Selected span no longer matches original source')
                anchor.update(char_start=start,char_end=start+len(anchor['quote']),
                              member_sha256=hashlib.sha256(member['text'].encode()).hexdigest())
            else:anchor.update(crop=member['crop'],crop_sha256=sha(out/member['crop']))
            anchors[name]=anchor
        result.append({'id':p['pair_id']+'::RELATED_CONTEXT','source':p['source'],'target':p['target'],
              'type':'RELATED_CONTEXT','family':'semantic','direction':'SYMMETRIC','scope':p['scope'],
              'status':'MODEL_SOURCE_CROP_CHECKED','human_review':'PENDING',
              'visual_verification':'MODEL_CROP_CHECKED' if any(v[a]['kind']=='VISUAL' for a in ['anchor_a','anchor_b']) else 'NOT_USED',
              'representation_basis':'original_crop_and_source' if any(v[a]['kind']=='VISUAL' for a in ['anchor_a','anchor_b']) else 'source_text_only',
              **anchors,'routes':p['routes'],'decision':{'reason':v['reason'],
                  **({'relation_basis':v['relation_basis'],'concept_a':v['concept_a'],'concept_b':v['concept_b'],
                      'critic_reason':d['critic']['reason'],
                      **({k:v[k] for k in ['shared_entity','entity_type','entity_fact_a','entity_fact_b']} if version==4 and v['relation_basis']=='SAME_NAMED_ENTITY' else {})} if version>=3 else {})}})
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    verify(parser.parse_args().output)
