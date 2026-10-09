#!/usr/bin/env python3
"""Blind, deduplicated, stratified review of matched candidate budgets.

Share only reviewer/. evaluation_only/ contains route membership and sampling
probabilities, and must stay with the evaluator until labels are frozen.
"""
import argparse
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

ARMS = ('lexical', 'dense', 'hybrid')
RELATIONS = ('SUPPORTS', 'EXPLAINS_OR_ELABORATES', 'MODIFIES', 'CONTRASTS_WITH', 'REFERENCES')


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write(path, rows):
    Path(path).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def pair(row):
    return tuple(sorted((row['source_unit_id'], row['target_unit_id'])))


def rng(seed, lane):
    return random.Random(hashlib.sha256(f'{seed}:{lane}'.encode()).digest())


def sample_plan(arms, per_scope, seed):
    if per_scope < 1 or set(arms) != set(ARMS):
        raise ValueError('three arms and positive sample count required')
    lanes, membership, selected, scopes = {}, defaultdict(dict), set(), {}
    for arm in ARMS:
        rows = arms[arm]
        if len({pair(r) for r in rows}) != len(rows):
            raise ValueError('duplicate pair within arm')
        groups = defaultdict(list)
        for rank, row in enumerate(rows, 1):
            key = pair(row)
            if key[0] == key[1]:
                raise ValueError('self pair')
            if key in scopes and scopes[key] != row['scope']:
                raise ValueError('inconsistent scope')
            scopes[key] = row['scope']
            groups[row['scope']].append(key)
            membership[key][arm] = {'rank_in_file': rank, 'route_scores': row.get('route_scores', {}), 'score': row.get('score')}
        for scope, keys in sorted(groups.items()):
            n = min(per_scope, len(keys))
            lanes[arm, scope] = {'population': len(keys), 'sampled': n}
            selected.update(rng(seed, f'{arm}:{scope}').sample(sorted(keys), n))
    scopes_set = set(scopes.values())
    for scope in scopes_set:
        sizes = [lanes.get((arm, scope), {}).get('population', 0) for arm in ARMS]
        if len(set(sizes)) != 1:
            raise ValueError('candidate budgets must match within each scope')
    ordered = sorted(selected)
    rng(seed, 'task_order').shuffle(ordered)
    records = []
    for n, key in enumerate(ordered, 1):
        scope = scopes[key]
        # Each lane samples independently without replacement. A shared pair is
        # reviewed once with union inclusion probability across its memberships.
        miss = 1.0
        for arm in membership[key]:
            lane = lanes[arm, scope]
            miss *= 1 - lane['sampled'] / lane['population']
        a, b = key
        if rng(seed, ':'.join(key)).random() < .5:
            a, b = b, a
        records.append({'task_id': f'R{n:04d}', 'unit_a': a, 'unit_b': b, 'scope': scope,
                        'arm_membership': membership[key], 'inclusion_probability': 1 - miss})
    return records, {f'{arm}/{scope}': value for (arm, scope), value in sorted(lanes.items())}


def render_html(tasks, package_id):
    # Escape HTML delimiters inside source text before placing JSON in a script.
    payload = json.dumps(tasks, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>候选关系盲审</title>
<style>body{font:16px system-ui;max-width:1300px;margin:24px auto;padding:0 18px}textarea{width:96%;min-height:75px}article{border:1px solid #bbb;padding:16px;overflow-wrap:anywhere}#pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}pre{white-space:pre-wrap;font:15px system-ui}img{max-width:100%;max-height:420px}select,input,button{padding:7px;margin:5px}label{display:block}small{color:#555}@media(max-width:800px){#pair{grid-template-columns:1fr}}</style>
<h1>候选关系盲审</h1><p>先判断是否存在明确关系；主题相似本身不算。可查看原页，无法判断时选 UNCERTAIN。
视觉代理文字不等于看过图片。只将这份 reviewer 文件夹交给审核者，评估映射另行保管。</p>
<p>SUPPORTS：提供证据；EXPLAINS_OR_ELABORATES：解释或展开；MODIFIES：条件、范围或限定；
CONTRASTS_WITH：明确对比（对称）；REFERENCES：可定位的显式引用，独立于前四类，可同时选择。
A_TO_B 表示 A 对 B 发挥所选功能；REFERENCES 的 A_TO_B 表示 A 引用 B。</p>
<button id="prev">上一对</button><button id="next">下一对</button><span id="position"></span>
<button id="export">导出审核 JSONL</button><label>导入已保存审核 <input id="import" type="file" accept=".jsonl"></label>
<p id="storage"></p><h2 id="task"></h2><div id="pair"></div>
<label>审核者 <input id="reviewer"></label><label>审核方式 <select id="method"><option value="">请选择</option><option>independent_human</option><option>model_assisted_human</option><option>model_only</option></select></label>
<label>明确关系 <select id="verdict"><option value="">未审核</option><option>YES</option><option>NO</option><option>UNCERTAIN</option></select></label>
<div id="relations"></div><label>判断依据 <textarea id="basis"></textarea></label>
<label>A 的证据：原文引文，或图中可定位内容 <textarea id="evidence_a"></textarea></label>
<label>B 的证据：原文引文，或图中可定位内容 <textarea id="evidence_b"></textarea></label>
<script>const tasks=''' + payload + ''', packageId=''' + json.dumps(package_id) + ''';
const kinds=['SUPPORTS','EXPLAINS_OR_ELABORATES','MODIFIES','CONTRASTS_WITH','REFERENCES'];
const defaults=t=>({task_id:t.task_id,package_id:packageId,reviewer:'',review_method:'',relation_exists:null,relations:[],basis:'',evidence_a:'',evidence_b:''});
let labels=Object.fromEntries(tasks.map(t=>[t.task_id,defaults(t)])),index=0;
try{const saved=JSON.parse(localStorage.getItem(packageId)||'null');if(saved&&tasks.every(t=>saved[t.task_id]))labels=saved;}catch(e){}
const el=id=>document.getElementById(id);
kinds.forEach(k=>{const l=document.createElement('label');l.textContent=k;const s=document.createElement('select');s.id=k;['NONE',...(k==='CONTRASTS_WITH'?['SYMMETRIC']:['A_TO_B','B_TO_A']),'UNRESOLVED'].forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;s.append(o)});l.append(s);el('relations').append(l)});
function persist(){try{localStorage.setItem(packageId,JSON.stringify(labels));el('storage').textContent='已保存到此浏览器。完成后请导出 JSONL。';}catch(e){el('storage').textContent='浏览器无法本地保存，请及时导出 JSONL。';}}
function save(){const r=labels[tasks[index].task_id];r.reviewer=el('reviewer').value;r.review_method=el('method').value;r.relation_exists=el('verdict').value||null;['basis','evidence_a','evidence_b'].forEach(k=>r[k]=el(k).value);r.relations=kinds.filter(k=>el(k).value!=='NONE').map(k=>({type:k,direction:el(k).value}));persist();}
function card(u,name){const a=document.createElement('article');const h=document.createElement('h3');h.textContent=name+' — '+u.doc_id+' / '+u.page_ids.join(', ');a.append(h);const p=document.createElement('pre');p.textContent=u.text;a.append(p);const meta=document.createElement('small');meta.textContent=JSON.stringify({unit_id:u.unit_id,description_source:u.description_source,source_fragment_ids:u.source_fragment_ids,source_visual_ids:u.source_visual_ids});a.append(meta);if(u.asset){const img=document.createElement('img');img.src=u.asset;a.append(img)}u.full_pages.forEach(src=>{const p=document.createElement('p'),link=document.createElement('a');link.href=src;link.target='_blank';link.textContent='查看原页';p.append(link);a.append(p)});if(u.missing_assets.length){const p=document.createElement('p');p.textContent='部分来源图片不可用；需要这些图片才能判断时请选择 UNCERTAIN。';a.append(p)}return a;}
function show(){const t=tasks[index],r=labels[t.task_id];el('task').textContent=t.task_id;el('position').textContent=(index+1)+' / '+tasks.length;el('pair').replaceChildren(card(t.evidence_a,'A'),card(t.evidence_b,'B'));el('reviewer').value=r.reviewer;el('method').value=r.review_method;el('verdict').value=r.relation_exists||'';['basis','evidence_a','evidence_b'].forEach(k=>el(k).value=r[k]||'');kinds.forEach(k=>el(k).value=(r.relations.find(x=>x.type===k)||{}).direction||'NONE');el('prev').disabled=index===0;el('next').disabled=index===tasks.length-1;}
el('prev').onclick=()=>{save();index--;show()};el('next').onclick=()=>{save();index++;show()};
document.querySelectorAll('textarea,select,input:not([type=file])').forEach(e=>e.addEventListener('change',save));
el('export').onclick=()=>{save();const blob=new Blob([tasks.map(t=>JSON.stringify(labels[t.task_id])).join('\\n')+'\\n'],{type:'application/x-ndjson'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='labels.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
el('import').onchange=async e=>{try{const rows=(await e.target.files[0].text()).trim().split(/\\r?\\n/).map(JSON.parse);if(rows.length!==tasks.length||new Set(rows.map(r=>r.task_id)).size!==tasks.length||rows.some(r=>!labels[r.task_id]||r.package_id!==packageId||!Array.isArray(r.relations)))throw Error('task IDs or package mismatch');labels=Object.fromEntries(rows.map(r=>[r.task_id,r]));persist();show()}catch(err){alert('导入失败：'+err.message)}};
show();</script></html>'''


def build(candidate_root, snapshot, output, per_scope=30, seed=20261004):
    if output.exists():
        raise ValueError('use a new output directory')
    paths = {arm: candidate_root / f'{arm}_budget_candidates.jsonl' for arm in ARMS}
    arms = {arm: read(path) for arm, path in paths.items()}
    plan, lanes = sample_plan(arms, per_scope, seed)
    if not plan:
        raise ValueError('empty review sample')
    units = {u['unit_id']: u for u in read(snapshot / 'units.jsonl')}
    for rows in arms.values():
        if any(key not in units for row in rows for key in pair(row)):
            raise ValueError('unknown candidate endpoint')
    reviewer = output / 'reviewer'; evaluator = output / 'evaluation_only'
    (reviewer / 'assets').mkdir(parents=True); evaluator.mkdir()
    copied = {}
    def copy_asset(path):
        source = Path(path)
        if not source.is_file():
            return None
        if str(source) not in copied:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            rel = 'assets/' + digest + source.suffix.lower()
            if not (reviewer / rel).exists():
                shutil.copy2(source, reviewer / rel)
            copied[str(source)] = rel
        return copied[str(source)]
    public_units = {}
    def evidence(uid):
        if uid in public_units:
            return public_units[uid]
        u = units[uid]
        value = {k: u.get(k) for k in ('unit_id','doc_id','page_ids','text','description_source',
                                      'source_fragment_ids','source_visual_ids')}
        value.update(asset=None, full_pages=[], missing_assets=[])
        if u.get('asset_path'):
            value['asset'] = copy_asset(u['asset_path'])
            if value['asset'] is None:
                value['missing_assets'].append('visual_asset')
        for page in u['page_ids']:
            path = snapshot / 'source_snapshots' / u['doc_id'] / page / 'input_representation.json'
            if path.exists():
                image_path = json.loads(path.read_text()).get('source_image')
                asset = copy_asset(image_path) if image_path else None
            else:
                asset = None
            if asset:
                value['full_pages'].append(asset)
            else:
                value['missing_assets'].append('source_page:' + page)
        public_units[uid] = value
        return value
    tasks = [{'task_id': r['task_id'], 'evidence_a': evidence(r['unit_a']), 'evidence_b': evidence(r['unit_b'])} for r in plan]
    write(reviewer / 'tasks.jsonl', tasks)
    task_hash = hashlib.sha256((reviewer / 'tasks.jsonl').read_bytes()).hexdigest()
    write(reviewer / 'labels_template.jsonl', [{'task_id':t['task_id'], 'package_id':task_hash, 'reviewer':'', 'review_method':'',
          'relation_exists':None, 'relations':[], 'basis':'', 'evidence_a':'', 'evidence_b':''} for t in tasks])
    write(evaluator / 'key.jsonl', plan)
    manifest = {'status':'AWAITING_INDEPENDENT_REVIEW', 'tasks':len(tasks), 'sampling_seed':seed,
                'sample_per_arm_per_scope':per_scope,'lanes':lanes,
                'tasks_sha256':task_hash, 'arm_population':{a:len(r) for a,r in arms.items()},
                'key_sha256':hashlib.sha256((evaluator/'key.jsonl').read_bytes()).hexdigest(),
                'input_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*paths.values(),snapshot/'units.jsonl']},
                'missing_assets_by_unit':sum(bool(u['missing_assets']) for u in public_units.values()),
                'copied_assets':len(set(copied.values())), 'production_modified':False,
                'limitations':['No labels generated. Only reviewer/ is blinded; never share evaluation_only/ before label freeze.',
                               'Inverse union inclusion weights are required; the pooled sample is not uniform within an arm.',
                               'Precision/yield estimates only, no recall without independent relevant-pair enumeration.']}
    (evaluator / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (reviewer / 'index.html').write_text(render_html(tasks,task_hash))
    (reviewer / 'README.txt').write_text('Open index.html locally. Inspect text and source images, then export labels.jsonl.\n'
        'The browser saves edits locally where supported; keep exported copies. Do not inspect evaluation_only before review.\n'
        'Select NO for merely shared topics and UNCERTAIN when source context is insufficient.\n'
        'For YES, select relation type/direction and record evidence from both endpoints.\n')
    print(json.dumps({k:v for k,v in manifest.items() if k not in {'input_sha256','lanes'}},indent=2))
    return manifest


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--candidates',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--per-scope',type=int,default=30)
    p.add_argument('--seed',type=int,default=20261004)
    a=p.parse_args();build(a.candidates,a.snapshot,a.output,a.per_scope,a.seed)
