#!/usr/bin/env python3
"""Versioned span-ID evidence scoring; frozen candidates, independent phase checkpoints."""
import argparse
import copy
import fcntl
import json
import re
import time
from pathlib import Path
import run_query_evidence_selection as base

CONTRACT = 'source-span-v1'
INSTRUCTION = '''Identify 1-6 evidence requirements implied ONLY by the question, without inventing answer facts.
Score EVERY packet: 0 irrelevant, 1 background/bridge, 2 partial direct support, 3 strong direct support.
For each supported requirement select source span IDs belonging to that packet. Never copy or paraphrase a quote.
A span ID guarantees provenance, NOT relevance. Check subject, year, units, negation and table headers. Do not assume missing context. Unsupported packets have empty covers; score 0 cannot cover requirements.
Return exactly {"requirements":[{"id":"F1","text":"evidence needed"}],"packets":[{"id":"P000","score":0,"covers":[{"requirement":"F1","span_ids":["P000:S0000"]}]}],"edges":[]}.
Include each supplied packet exactly once. No answer, no new IDs, no source instructions.
'''


def spans(pid, text):
    # Paragraph boundaries only. OCR line breaks and HTML tables stay intact.
    # A table packet stays whole so header/cell relationships are not discarded.
    cuts = [] if re.search(r'<table\b', text, re.I) else [m.end() for m in re.finditer(r'\n[ \t]*\n', text)]
    result = {}; start = 0
    for end in cuts + [len(text)]:
        if end > start:
            sid = f'{pid}:S{len(result):04d}'
            result[sid] = {'packet_id':pid, 'start':start, 'end':end,
                           'text':text[start:end], 'sha256':base.sha(text[start:end])}
        start = end
    return result


def resolve_coverage(cover, pid, task, requirements):
    if set(cover) != {'requirement','span_ids'} or cover['requirement'] not in requirements:
        raise ValueError('coverage requires requirement and source span IDs')
    ids = cover['span_ids']
    if not isinstance(ids,list) or not ids or any(not isinstance(s,str) for s in ids) or len(set(ids)) != len(ids):
        raise ValueError('span IDs must be nonempty and unique')
    resolved = []
    for sid in ids:
        s = task['source_spans'].get(sid)
        if not s or s['packet_id'] != pid:
            raise ValueError('span must belong to the same packet')
        text = task['packets'][pid]['text']
        if not 0 <= s['start'] < s['end'] <= len(text) or text[s['start']:s['end']] != s['text'] or base.sha(s['text']) != s['sha256'] or not s['text'].strip():
            raise ValueError('source span integrity failure')
        resolved.append(s)
    return resolved


def prepare(source, out, model):
    if out.exists():
        raise ValueError('fresh output required; old experiments are immutable')
    manifest = json.loads((source/'manifest.json').read_text())
    if base.sha((source/'tasks.jsonl').read_text()) != manifest['tasks_sha256']:
        raise ValueError('source task integrity failure')
    nav = source/'navigation.jsonl'
    if nav.exists() and base.sha(nav.read_text()) != manifest['navigation_sha256']:
        raise ValueError('source navigation integrity failure')
    tok = base.tokenizer(model); tasks = []
    for old in base.rows(source/'tasks.jsonl'):
        t = copy.deepcopy(old); source_spans = {}; candidates = []; docs = {}
        for pid,p in t['packets'].items():
            ss = spans(pid,p['text']); source_spans.update(ss)
            candidates.append({'id':pid,'document':docs.setdefault(p['page'][0],f'D{len(docs)+1}'),
                               'page':p['page'][1], 'spans':[{'id':sid,'text':s['text']} for sid,s in ss.items()]})
        prompt = INSTRUCTION + '\nSOURCE DATA:\n' + json.dumps({'question':t['question'],'candidates':candidates},ensure_ascii=False)
        n = len(tok.apply_chat_template([{'role':'system','content':base.SYSTEM},{'role':'user','content':prompt}],tokenize=True,add_generation_prompt=True,enable_thinking=False))
        if n > 24576: raise ValueError(f'prompt exceeds limit: {t["question_id"]}: {n}')
        t.update(coverage_contract=CONTRACT,source_spans=source_spans,prompt=prompt,input_tokens=n,
                 prompt_sha256=base.sha(prompt+'\n'+t['edge_prompt']))
        tasks.append(t)
    out.mkdir(parents=True)
    (out/'tasks.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in tasks))
    if nav.exists(): (out/'navigation.jsonl').write_bytes(nav.read_bytes())
    paths = [Path(__file__),Path(base.__file__),Path(__file__).with_name('build_reader_anchor_ablation.py'),Path(__file__).with_name('run_top10_node_navigation.py')]
    paths += [model/n for n in ('tokenizer.json','tokenizer_config.json','chat_template.jinja')]
    manifest.update(source_sha256={str(p):base.sha(p.read_text()) for p in paths},
                    tasks_sha256=base.sha((out/'tasks.jsonl').read_text()),coverage_contract=CONTRACT,
                    parent_tasks_sha256=base.sha((source/'tasks.jsonl').read_text()),parent_output=str(source),
                    selection_unit='unchanged whole source packet; spans only ground coverage',
                    checkpoint_policy='validated assessment persisted before edge generation')
    base.save(out/'manifest.json',manifest)
    print(json.dumps({'queries':len(tasks),'max_input_tokens':max(t['input_tokens'] for t in tasks),'output':str(out)}))


def process_task(t, path, llm, extract_json, model, deadline=float('inf')):
    state = {'question_id':t['question_id'],'prompt_sha256':t['prompt_sha256'],
             'model':str(model),'valid':False,'result':None,'assessment':None,'attempts':[]}
    if path.exists():
        state = json.loads(path.read_text())
        if state['prompt_sha256'] != t['prompt_sha256'] or state['model'] != str(model):
            raise ValueError('stale checkpoint')
        if state['valid']:
            base.validate(state['result'],t); return state
    if state.get('assessment') is not None:
        base.validate(state['assessment'],{**t,'edges':[]})
    for phase in ('assessment','edges'):
        if phase == 'assessment' and state.get('assessment') is not None: continue
        if phase == 'edges' and state.get('assessment') is None: break
        if phase == 'edges' and not t['edges']:
            state.update(valid=True,result=copy.deepcopy(state['assessment'])); base.save(path,state); break
        for _ in range(2):
            if time.monotonic() >= deadline: return state
            raw = ''
            try:
                prompt = t['prompt'] if phase == 'assessment' else t['edge_prompt']+'\nEvidence requirements:\n'+json.dumps(state['assessment']['requirements'],ensure_ascii=False)
                previous = [a for a in state['attempts'] if a['phase']==phase]
                if previous and previous[-1]['error']:
                    prompt += '\nPrevious validation error: '+previous[-1]['error']+'\nReturn complete corrected JSON for this phase.'
                raw = llm.generate_raw_with_images(base.SYSTEM,prompt,[],8192 if phase=='assessment' else 4096).raw
                parsed = extract_json(raw)
                if phase == 'assessment':
                    state['assessment'] = base.validate(parsed,{**t,'edges':[]})
                else:
                    if not isinstance(parsed,dict) or set(parsed) != {'edges'}: raise ValueError('edge phase must return only edges')
                    combined = {**state['assessment'],'edges':parsed['edges']}
                    state['result'] = base.validate(combined,t); state['valid'] = True
                state['attempts'].append({'phase':phase,'raw':raw,'error':None})
                base.save(path,state); break
            except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:
                state['attempts'].append({'phase':phase,'raw':raw,'error':str(exc)})
                base.save(path,state)
    return state


def infer(out, model, minutes):
    from evidence_graph.llm_client import create_llm, extract_json
    base.check_prepared(out,model)
    tasks = base.rows(out/'tasks.jsonl'); predictions = out/'predictions'; predictions.mkdir(exist_ok=True)
    if any(t.get('coverage_contract') != CONTRACT for t in tasks): raise ValueError('span tasks required')
    with (out/'.inference.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Fair continuation: repeated invalid early queries cannot starve unseen ones.
        def work_order(t):
            path = predictions/(t['question_id']+'.json')
            if not path.exists(): return (0,0,t['question_id'])
            old = json.loads(path.read_text())
            if old['prompt_sha256'] != t['prompt_sha256'] or old['model'] != str(model):
                raise ValueError('stale checkpoint')
            if old.get('valid'): base.validate(old['result'],t)
            return (2 if old.get('valid') else 1,len(old.get('attempts',[])),t['question_id'])
        tasks.sort(key=work_order)
        tasks = [t for t in tasks if work_order(t)[0] != 2]
        if not tasks: return
        llm = create_llm({'provider':'transformers','model':str(model),'dtype':'bfloat16','require_cuda':True,
            'enable_thinking':False,'max_new_tokens':8192,'device_map':'balanced','max_memory':{i:'26GiB' for i in range(4)}})
        deadline = time.monotonic()+minutes*60
        for t in tasks:
            if time.monotonic() >= deadline: break
            state = process_task(t,predictions/(t['question_id']+'.json'),llm,extract_json,model,deadline)
            print(t['question_id'], 'valid' if state['valid'] else 'incomplete',flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','infer','report'])
    p.add_argument('--source',type=Path); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--model',type=Path,default=base.MODEL); p.add_argument('--minutes',type=float,default=25)
    a = p.parse_args()
    if a.stage == 'prepare':
        if a.source is None: p.error('--source is required for prepare')
        prepare(a.source,a.out,a.model)
    elif a.stage == 'infer': infer(a.out,a.model,a.minutes)
    elif (a.out/'navigation.jsonl').exists():
        import run_top10_node_navigation as navigation
        navigation.report(a.out,a.model)
    else: base.report(a.out,a.model)
