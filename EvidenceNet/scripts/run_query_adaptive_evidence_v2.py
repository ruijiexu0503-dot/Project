#!/usr/bin/env python3
"""Frozen-query pilot: partial support, source-only audits, query-led two-hop traversal.

Prepare never reads gold. All model calls checkpoint independently. Old runs stay immutable.
"""
import argparse
import fcntl
import hashlib
import json
import time
from pathlib import Path
from collections import defaultdict
import query_evidence_policy_v2 as policy
import run_span_evidence_selection as spans_v1
import run_query_evidence_selection as base
from query_semantic_edge_core import chat_prompt_token_count,generate_raw_text
from build_reader_anchor_ablation import ROOT, MODEL, SOURCE, DIAG, BUDGETS, render, sha

OLD_FIXED=ROOT/'migration/span_results_5218364_20261030/query_span_selection_20261030'
OLD_NAV=ROOT/'migration/span_results_5218190_20261030/top10_span_navigation_20261030'
DEFAULT_OUT=ROOT/'EvidenceNet/output/query_adaptive_evidence_v2_20261030'


def rows(path): return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]
def jsonl(path,values): path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in values))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(out,model,max_candidates=40):
    if out.exists(): raise ValueError('fresh output required')
    for parent in (OLD_FIXED,OLD_NAV):
        m=json.loads((parent/'manifest.json').read_text())
        if digest(parent/'tasks.jsonl')!=m['tasks_sha256']: raise ValueError('parent tasks changed')
    if digest(OLD_NAV/'navigation.jsonl')!=json.loads((OLD_NAV/'manifest.json').read_text())['navigation_sha256']: raise ValueError('parent navigation changed')
    fixed={t['question_id']:t for t in rows(OLD_FIXED/'tasks.jsonl')}
    nodes={n['id']:n for n in rows(SOURCE/'nodes.jsonl')};edges=rows(DIAG/'edge_records.jsonl')
    tasks=[]
    for c in rows(OLD_NAV/'navigation.jsonl'):
        qid=c['question_id'];seen=set(c['seed_nodes']);sources=set(seen)
        for hop in (1,2):
            ff=policy.frontier(edges,sources,seen,hop);sources={r['target_node'] for r in ff};seen|=sources
        if len(seen)>max_candidates: raise ValueError('two-hop envelope exceeds candidate budget; do not silently prune')
        ranking=c['node_ranking'];dense_nodes=ranking[:len(seen)]
        if not seen<=set(ranking): raise ValueError('graph endpoint lacks frozen retrieval rank')
        allnodes=seen|set(dense_nodes)|{p['node_id'] for p in fixed[qid]['packets'].values()}
        packet_map={};by_node=defaultdict(list);source_spans={};ranks={n:i+1 for i,n in enumerate(ranking)}
        for nid in sorted(allnodes):
            node=nodes[nid];allowed={m['member_id'] for m in node.get('eligible_members',[]) if m.get('eligible')}
            for m in node['members']:
                if m['id'] not in allowed or not m.get('text','').strip() or m.get('kind')=='visual': continue
                pid=f'P{len(packet_map):03d}'
                p={'packet_id':sha(nid+':'+m['id']),'node_id':nid,'member_id':m['id'],
                   'page':[str(node['document']),str(node['page'])],'text':m['text'],
                   'member_sha256':sha(m['text']),'char_start':0,'char_end':len(m['text']),
                   'base_score':-ranks[nid],'initial_node_rank':ranks[nid]}
                packet_map[pid]=p;by_node[nid].append(pid);source_spans.update(spans_v1.spans(pid,p['text']))
        lookup={(p['node_id'],p['member_id']):pid for pid,p in packet_map.items()}
        fixed_ids=[]
        for p in fixed[qid]['packets'].values():
            pid=lookup[p['node_id'],p['member_id']]
            if packet_map[pid]['text']!=p['text']: raise ValueError('fixed candidate source changed')
            fixed_ids.append(pid)
        # Preserve each experiment's own original tie-break score.
        fixed_scores={lookup[p['node_id'],p['member_id']]:p['base_score'] for p in fixed[qid]['packets'].values()}
        docs={};documents={pid:docs.setdefault(p['page'][0],f'D{len(docs)+1}') for pid,p in packet_map.items()}
        tasks.append({'question_id':qid,'question':c['question'],'seed_nodes':c['seed_nodes'],
            'node_ranking':ranking,'dense_envelope':dense_nodes,'graph_envelope':sorted(seen),
            'packets':packet_map,'by_node':dict(by_node),'source_spans':source_spans,'documents':documents,
            'fixed_packet_ids':fixed_ids,'fixed_base_scores':fixed_scores})
    # Freeze and verify original edge anchors; descriptions remain hints, not answer evidence.
    frozen_edges=[]
    for e in edges:
        card={'edge_id':e['edge_id'],'source_node_id':e['source_node_id'],'target_node_id':e['target_node_id'],
              'relation_type':e.get('relation_type'), 'relation_description':e.get('relation_description'), 'anchors':[]}
        for endpoint in e['endpoints'].values():
            node=nodes[endpoint['node_id']];members={m['id']:m for m in node['members']}
            for s in endpoint['spans']:
                if s['source_kind']!='ORIGINAL_TEXT': continue
                original=members[s['member_id']]['text']
                if sha(original)!=s['member_sha256'] or original[s['char_start']:s['char_end']]!=s['text']: raise ValueError('edge anchor integrity failed')
                card['anchors'].append({'node_id':endpoint['node_id'],'text':s['text'],'source_kind':'ORIGINAL_TEXT'})
        frozen_edges.append(card)
    out.mkdir(parents=True)
    jsonl(out/'tasks.jsonl',tasks);jsonl(out/'edges.jsonl',frozen_edges)
    code=[Path(__file__),Path(policy.__file__),Path(spans_v1.__file__),Path(base.__file__),Path(__file__).with_name('build_reader_anchor_ablation.py')]
    files=code+[model/n for n in ('tokenizer.json','tokenizer_config.json','chat_template.jinja')]
    manifest={'version':'query-adaptive-v2','tasks_sha256':digest(out/'tasks.jsonl'),'edges_sha256':digest(out/'edges.jsonl'),
        'source_sha256':{str(p):digest(p) for p in files},'queries':len(tasks),'hops':2,
        'max_candidates':max_candidates,'steering_budget':1024,'budgets':list(BUDGETS),'model':str(model),
        'parent_sha256':{str(p):digest(p) for p in (OLD_FIXED/'tasks.jsonl',OLD_NAV/'tasks.jsonl',OLD_NAV/'navigation.jsonl',SOURCE/'nodes.jsonl',DIAG/'edge_records.jsonl')},
        'reading_layer':'not imported: upstream reading_ready=false','answer_generation':False,
        'planning':'query only, no candidate/source/gold visible',
        'control':'dense prefix matches distinct nodes exposed via graph route anchors, including rejected routes; token/call costs reported separately',
        'selection':'whole packets; cited source units, untrusted semantic labels; per-requirement validation and selected-set audit',
        'scope':'24-query pilot, frozen original candidates and two-hop semantic graph; no new corpus embeddings'}
    base.save(out/'manifest.json',manifest)
    print(json.dumps({'queries':len(tasks),'max_graph_nodes':max(len(t['graph_envelope']) for t in tasks),
      'queries_with_second_hop':sum(len(t['graph_envelope'])>len(set(t['seed_nodes'])|{r['target_node'] for r in policy.frontier(frozen_edges,set(t['seed_nodes']),set(t['seed_nodes']),1)}) for t in tasks),
      'output':str(out)}))


class Deadline(Exception): pass
class InvalidOutput(Exception): pass


class Broker:
    def __init__(self,out,model,minutes,tok,llm=None):
        self.out=out;self.model=model;self.tok=tok;self.llm=llm
        self.deadline=time.monotonic()+minutes*60
        self.directory=out/'calls';self.directory.mkdir(exist_ok=True)

    def call(self,qid,phase,instruction,payload,validator,max_tokens=8192):
        prompt=instruction+'\nSOURCE DATA:\n'+json.dumps(payload,ensure_ascii=False,sort_keys=True)
        key=sha(policy.SYSTEM+'\n'+prompt+'\n'+str(self.model))
        directory=self.directory/qid;directory.mkdir(exist_ok=True)
        path=directory/(key+'.json')
        record={'request_sha256':key,'phase':phase,'question_id':qid,'model':str(self.model),
                'instruction':instruction,'request':payload,'system':policy.SYSTEM,
                'valid':False,'result':None,'attempts':[]}
        if path.exists():
            record=json.loads(path.read_text())
            if record['request_sha256']!=key: raise ValueError('stale call cache')
            if record['valid']: return validator(record.get('parsed_result',record['result']))
        for _ in range(2):
            if time.monotonic()>=self.deadline: raise Deadline()
            current=prompt
            if record['attempts']: current+='\nValidation error: '+record['attempts'][-1]['error']+'\nReturn complete corrected JSON.'
            n=chat_prompt_token_count(self.tok,[{'role':'system','content':policy.SYSTEM},{'role':'user','content':current}],enable_thinking=False)
            if n>24576: raise InvalidOutput('prompt over limit; no truncation')
            if self.llm is None:
                from evidence_graph.llm_client import create_llm
                self.llm=create_llm({'provider':'transformers','model':str(self.model),'dtype':'bfloat16','require_cuda':True,
                    'enable_thinking':False,'max_new_tokens':8192,'device_map':'balanced','max_memory':{i:'26GiB' for i in range(4)}})
            start=time.monotonic()
            raw=generate_raw_text(self.llm,policy.SYSTEM,current,max_tokens)
            attempt={'input_tokens':n,'output_tokens':len(self.tok.encode(raw,add_special_tokens=False)),
                     'seconds':time.monotonic()-start,'raw':raw,'error':None}
            try:
                from evidence_graph.llm_client import extract_json
                parsed=extract_json(raw)
                result=validator(parsed)
            except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:
                attempt['error']=str(exc);record['attempts'].append(attempt);base.save(path,record);continue
            record.update(valid=True,result=result,parsed_result=parsed,validation_complete=not result.get('validation_issues'));record['attempts'].append(attempt);base.save(path,record)
            return result
        raise InvalidOutput(f'{phase}: '+record['attempts'][-1]['error'])


def packet_payload(t,pid):
    return {'id':pid,'document':t['documents'][pid],'page':t['packets'][pid]['page'][1],
            'spans':[{'id':sid,'text':s['text']} for sid,s in t['source_spans'].items() if s['packet_id']==pid]}


def isolated_requirements(t,phase,instruction,payload,plan,broker,strict_validator,verdict=False,max_tokens=8192):
    result=broker.call(t['question_id'],phase,instruction,payload,
        lambda raw:policy.partition_requirements(raw,plan,strict_validator,verdict),max_tokens)
    issues=list(result['validation_issues']);by_id={r['id']:r for r in result['requirements']}
    for req in plan['requirements']:
        rid=req['id'];failures=[e for e in issues if e['requirement_id']==rid]
        if not failures:continue
        subset={'requirements':[req]}
        repair_payload={**payload,'requirements':[req],'validation_error':failures[0]['error']}
        try:
            corrected=broker.call(t['question_id'],phase+'_repair',instruction+
                '\nRepair ONLY the supplied requirement; do not return or change other requirements.',
                repair_payload,lambda raw:strict_validator(raw,subset),max_tokens)
            by_id[rid]=corrected['requirements'][0]
            issues=[e for e in issues if e['requirement_id']!=rid]
        except InvalidOutput as exc:
            by_id[rid]['missing']=['Validation unresolved after targeted retry: '+str(exc)]
    return {'requirements':[by_id[r['id']] for r in plan['requirements']],
            'validation_issues':issues,'normalizations':result['normalizations']}


def assess_packets(t,pids,plan,broker):
    results={}
    for pid in sorted(pids):
        payload={'question':t['question'],'requirements':plan['requirements'],'packet':packet_payload(t,pid)}
        results[pid]=isolated_requirements(t,'assessment',policy.ASSESS,payload,plan,broker,
            lambda raw,subplan:policy.validate_assessment(raw,subplan,pid,t['source_spans']))
    return results


def pack_and_verify(t,pids,assessments,plan,broker,budget,mode,joint_groups=None):
    packets={pid:dict(t['packets'][pid]) for pid in pids}
    if mode=='fixed':
        for pid,p in packets.items():p['base_score']=t['fixed_base_scores'][pid]
    joint_pack=getattr(policy,'pack_with_joint',None)
    packed=(joint_pack(packets,assessments,joint_groups or [],budget,broker.tok,render)
            if joint_pack and joint_groups else policy.pack(packets,assessments,budget,broker.tok,render))
    available={sid:s for sid,s in t['source_spans'].items() if s['packet_id'] in packed['selected_ids']}
    if packed['selected_ids']:
        verdict=isolated_requirements(t,'selected_set_audit',policy.VERIFY,
            {'question':t['question'],'requirements':plan['requirements'],
             'packets':[packet_payload(t,pid) for pid in packed['selected_ids']]},plan,broker,
            lambda raw,subplan:policy.validate_verdict(raw,subplan,available),True,4096)
    else:
        make_empty=getattr(policy,'empty_verdict',None)
        verdict={'requirements':[(make_empty(r,'No evidence selected within this budget') if make_empty else
            {'id':r['id'],'status':'missing','exhaustive':False,'span_ids':[],
             'missing':['No evidence selected within this budget']}) for r in plan['requirements']]}
    text=render(packed['packets'])
    return {**packed,'budget':budget,'evidence_text':text,'evidence_tokens':len(broker.tok.encode(text,add_special_tokens=False)),
            'sufficiency':verdict,'sufficiency_is_model_estimate':True}


def run_task(t,edges,mode,broker):
    qid=t['question_id']
    proposed=broker.call(qid,'query_plan',policy.PLAN,{'question':t['question']},policy.validate_plan,4096)
    review=broker.call(qid,'query_plan_review',policy.PLAN_REVIEW,
        {'question':t['question'],'plan':proposed},lambda r:policy.validate_plan_review(r,proposed),4096)
    kept={r['id'] for r in review['decisions'] if r['keep']}
    plan={'requirements':[r for r in proposed['requirements'] if r['id'] in kept]}
    def pids(nodes):return sorted({p for n in nodes for p in t['by_node'].get(n,[])})
    traces=[];arms={};joint_groups=[]
    if mode=='fixed':
        ids=t['fixed_packet_ids'];assessments=assess_packets(t,ids,plan,broker)
        arms['fixed_fact_coverage']=(ids,assessments)
    else:
        visited=set(t['seed_nodes']);sources=set(visited);exposed=set(visited)
        assessments=assess_packets(t,pids(visited),plan,broker)
        arms['seed10']=(pids(visited),dict(assessments))
        verdict=pack_and_verify(t,pids(visited),assessments,plan,broker,1024,mode)['sufficiency']
        edge_map={e['edge_id']:e for e in edges}
        for hop in (1,2):
            missing=policy.unresolved(verdict)
            if not missing:
                traces.append({'hop':hop,'stop':'selected_sources_sufficient','verdict':verdict});break
            routes=policy.frontier(edges,sources,visited,hop)
            if not routes:
                traces.append({'hop':hop,'stop':'no_unvisited_graph_neighbors','missing':missing});break
            decisions=[]
            # Bound each call, never silently drop frontier routes or source anchors.
            for offset in range(0,len(routes),6):
                batch=routes[offset:offset+6]
                cards=[{**r,'edge':edge_map[r['edge_id']]} for r in batch]
                nav=broker.call(qid,'navigation',policy.NAVIGATE,
                    {'question':t['question'],'requirements':plan['requirements'],'unresolved':missing,
                     'selected_source_audit':verdict,'routes':cards},
                    lambda result:policy.validate_routes(result,cards,missing),4096)
                decisions.extend(nav['routes'])
                exposed.update(r['target_node'] for r in batch)
            selected_routes={r['id'] for r in decisions if r['follow']}
            accepted=[r for r in routes if r['id'] in selected_routes]
            sources={r['target_node'] for r in accepted};visited|=sources
            assessments.update(assess_packets(t,pids(sources),plan,broker))
            route_joint_audits=[]
            group_builder=getattr(policy,'joint_group',None)
            if group_builder:
                for route in accepted:
                    route_ids=pids({route['source_node'],route['target_node']})
                    available={sid:s for sid,s in t['source_spans'].items() if s['packet_id'] in route_ids}
                    audit=isolated_requirements(t,'route_joint_audit',policy.VERIFY,
                        {'question':t['question'],'requirements':plan['requirements'],
                         'route':route,'packets':[packet_payload(t,pid) for pid in route_ids]},plan,broker,
                        lambda raw,subplan:policy.validate_verdict(raw,subplan,available),True,4096)
                    group=group_builder(audit,t['source_spans'],route)
                    if group:joint_groups.append(group)
                    route_joint_audits.append({'route':route,'audit':audit,'joint_group':group})
            previous=verdict
            verdict=pack_and_verify(t,pids(visited),assessments,plan,broker,1024,mode)['sufficiency']
            traces.append({'hop':hop,'missing_before':missing,'source_audit_before':previous,
                           'routes':routes,'decisions':decisions,'followed':accepted,
                           'route_joint_audits':route_joint_audits,
                           'actual_gain':getattr(policy,'actual_gain',lambda a,b:None)(previous,verdict),
                           'source_audit_after':verdict})
            if not sources:break
        arms['graph_adaptive']=(pids(visited),assessments)
        if joint_groups:arms['graph_adaptive_joint']=(pids(visited),assessments,joint_groups)
        # The control sees as many nodes as graph navigation exposed, including rejected anchors.
        dense_nodes=t['node_ranking'][:len(exposed)]
        dense_ids=pids(dense_nodes);dense_assessments=assess_packets(t,dense_ids,plan,broker)
        arms['dense_exposure_matched']=(dense_ids,dense_assessments)
        traces.append({'inspected_nodes':sorted(exposed),'visited_nodes':sorted(visited),
                       'dense_control_nodes':dense_nodes,'count_match':len(exposed)==len(dense_nodes),
                       'cost_note':'Node exposure matched; prompts/tokens and call counts are not assumed equal.'})
    records=[];issues=[]
    for arm,arm_data in arms.items():
        ids,assessments=arm_data[:2];arm_joint_groups=arm_data[2] if len(arm_data)>2 else []
        for pid,assessment in assessments.items():
            issues.extend({'arm':arm,'packet_id':pid,**e} for e in assessment.get('validation_issues',[]))
        for budget in BUDGETS:
            record=pack_and_verify(t,ids,assessments,plan,broker,budget,mode,arm_joint_groups)
            issues.extend({'arm':arm,'budget':budget,**e} for e in record['sufficiency'].get('validation_issues',[]))
            records.append({'arm':arm,'question_id':qid,'question':t['question'],
                            'candidate_packet_ids':ids,**record})
    return {'question_id':qid,'proposed_plan':proposed,'plan_review':review,'plan':plan,'mode':mode,
            'records':records,'trace':traces,'processing_finished':True,'complete':not issues,
            'validation_issues':issues,'answer_llm_run':False}


def check(out,model):
    base.check_prepared(out,model)
    m=json.loads((out/'manifest.json').read_text())
    if digest(out/'edges.jsonl')!=m['edges_sha256']:raise ValueError('frozen edges changed')
    for t in rows(out/'tasks.jsonl'):
        for pid,p in t['packets'].items():
            if sha(p['text'])!=p['member_sha256']:raise ValueError('packet source changed')
            for sid,s in t['source_spans'].items():
                if s['packet_id']==pid and (p['text'][s['start']:s['end']]!=s['text'] or sha(s['text'])!=s['sha256']):raise ValueError('span source changed')


def infer(out,model,mode,minutes,limit=None,query_ids=None):
    check(out,model);tasks=rows(out/'tasks.jsonl');edges=rows(out/'edges.jsonl')
    configure=getattr(policy,'configure_edges',None)
    if configure:edges=configure(edges,mode)
    identity=sha((out/'manifest.json').read_text()+'\n'+str(model)+'\n'+mode)
    if query_ids:
        if not set(query_ids)<={t['question_id'] for t in tasks}:raise ValueError('unknown query ID')
        tasks=[t for t in tasks if t['question_id'] in query_ids]
    if limit is not None:tasks=tasks[:limit]
    run=out/mode;run.mkdir(exist_ok=True);pred=run/'predictions';pred.mkdir(exist_ok=True)
    with (run/'.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        broker=Broker(run,model,minutes,base.tokenizer(model))
        # Prefer least-attempted queries to avoid retry starvation; stages are independently cached.
        tasks.sort(key=lambda t:(len(list((run/'calls'/t['question_id']).glob('*.json'))),t['question_id']))
        for t in tasks:
            path=pred/(t['question_id']+'.json')
            if path.exists():
                previous=json.loads(path.read_text())
                if previous.get('run_identity')!=identity:raise ValueError('stale query prediction')
                if previous.get('complete'):continue
            if time.monotonic()>=broker.deadline:break
            try:
                result=run_task(t,edges,mode,broker);result['run_identity']=identity;base.save(path,result)
                print(t['question_id'],'complete' if result['complete'] else 'partial_validation',flush=True)
            except Deadline:
                base.save(path,{'question_id':t['question_id'],'complete':False,'checkpoint_reason':'time_budget','run_identity':identity})
                print(t['question_id'],'checkpoint saved at time budget',flush=True);break
            except InvalidOutput as exc:
                base.save(path,{'question_id':t['question_id'],'complete':False,'error':str(exc),'run_identity':identity})
                print(t['question_id'],str(exc),flush=True)
    report(out,mode)


def report(out,mode):
    run=out/mode;pred=run/'predictions';tasks=rows(out/'tasks.jsonl');statuses=[];records=[];costs=[]
    for t in tasks:
        path=pred/(t['question_id']+'.json');r=json.loads(path.read_text()) if path.exists() else None
        done=bool(r and r.get('complete'))
        state='complete' if done else ('partial_validation' if r and r.get('processing_finished') else ('protocol_failure' if r and r.get('error') else ('time_checkpoint' if r and r.get('checkpoint_reason')=='time_budget' else 'unprocessed')))
        statuses.append({'question_id':t['question_id'],'complete':done,'state':state,
                         'error':r.get('error') if r else None,'validation_issues':r.get('validation_issues',[]) if r else []})
        if r and r.get('processing_finished'):
            records.extend({**record,'query_validation_complete':done} for record in r['records'])
        calls=[json.loads(p.read_text()) for p in (run/'calls'/t['question_id']).glob('*.json')]
        attempts=[a for c in calls for a in c['attempts']]
        costs.append({'question_id':t['question_id'],'calls':len(attempts),'input_tokens':sum(a['input_tokens'] for a in attempts),
                      'output_tokens':sum(a['output_tokens'] for a in attempts),'generation_seconds':sum(a['seconds'] for a in attempts),
                      'phase_calls':{phase:sum(len(c['attempts']) for c in calls if c['phase']==phase) for phase in sorted({c['phase'] for c in calls})}})
    jsonl(run/'selected.jsonl',records);jsonl(run/'costs.jsonl',costs)
    status={'total_queries':len(tasks),'complete_queries':sum(r['complete'] for r in statuses),'complete':all(r['complete'] for r in statuses),
            'queries':statuses,'answer_llm_run':False,'cost_scope':'actual shared cached calls across arms, not isolated per-arm runtime'}
    base.save(run/'status.json',status);print(json.dumps(status))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','infer','report','check'])
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT);parser.add_argument('--model',type=Path,default=MODEL)
    parser.add_argument('--mode',choices=['fixed','navigation'],default='navigation')
    parser.add_argument('--minutes',type=float,default=25);parser.add_argument('--limit',type=int)
    parser.add_argument('--query-id',action='append',dest='query_ids',help='Explicit smoke subset only; full report retains all 24 queries')
    args=parser.parse_args()
    if args.stage=='prepare':prepare(args.out,args.model)
    elif args.stage=='check':check(args.out,args.model);print('ADAPTIVE_PREFLIGHT_OK')
    elif args.stage=='infer':infer(args.out,args.model,args.mode,args.minutes,args.limit,args.query_ids)
    else:report(args.out,args.mode)
