#!/usr/bin/env python3
"""Paired article-first/reading-first experiment with common roles and assembly policy."""
import argparse
from collections import Counter
from copy import deepcopy
import itertools
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'EvidenceNet'))
import run_article_first_pilot as first
from run_hybrid_article_clustering import call,read,rows,write,jsonl,sha
from evidence_graph.article_order import sentence_block,validate_order,owned_flows,validate_paths,jaccard
from evidence_graph.hybrid_article_clustering import stable_id
from evidence_graph.llm_client import create_llm
from run_embedding_geometry_node_baseline import text_of
from bounded_geometry import pair_hint

SOURCE=ROOT/'EvidenceNet/output/hybrid_49page_stress_prepared_20261007'
OUT=ROOT/'EvidenceNet/output/article_reading_order_comparison_v1_20261015'
TASKS=[
 'shard_1/CERNCourier2022NovDec-digitaledition/page_0006',
 'shard_0/DLRmagazine_176_EN/page_0009',
 'shard_0/CLADmag_2025_H2/page_0063',
 'shard_0/CERNCourier2025JanFeb-digitaledition/page_0006',
]


def reference(index):
    """Partial source-reviewed development references, never passed to Qwen."""
    if index==0:
        groups=[['A_006','A_007','A_008','A_009','A_014','A_015','A_016','A_017','V_001','V_002'],
                ['A_018','A_021','A_022','A_023','A_024','A_026','V_003'],
                ['A_034','A_035','A_036','A_037','A_040','A_042','A_044','A_045','V_004'],
                ['A_050','A_051','A_052','A_053','A_056','A_057','V_005']]
        chains=[['A_006','A_007','A_008','A_009','A_015','A_016','A_017'],
                ['A_021','A_022','A_023','A_018','A_024','A_026'],
                ['A_034','A_035','A_036','A_037','A_042','A_040','A_045'],
                ['A_050','A_051','A_052','A_053','A_057']]
        excluded=['A_004','A_019','A_031','A_032','V_006','V_007']
        joins=[['A_015','A_016'],['A_022','A_023'],['A_023','A_018'],['A_036','A_037'],['A_051','A_052']]
        forbidden=[['A_023','A_024']]
        figures={'A_014':['V_001','V_002'],'A_044':['V_004'],'A_056':['V_005']}
    elif index==1:
        # One feature with explanatory subsections/boxes; not three independent stories.
        groups=[['D004','D005','D007','D010','D011','D014','D016','D017','D019','P_0009_A01','P_0009_A02','P_0009_A03']]
        chains=[['D004','D005','D010','D017','D019']]
        excluded=['D002','D006','D020','PDFTEXT_000'];joins=[];forbidden=[]
        figures={'D007':['P_0009_A02']}
    elif index==2:
        # Independent named project items in one stadium feature/list: item-level article contract.
        groups=[['A_004','A_005','A_006','V_001'],['A_008','A_009','A_010','A_011','A_012','A_013','V_002']]
        chains=[['A_004','A_005','A_006'],['A_008','A_009','A_010','A_011','A_012','A_013']]
        excluded=['A_001','A_015'];joins=[['A_004','A_005'],['A_010','A_011']];forbidden=[];figures={}
    else:
        groups=[['A_009','A_010','A_011','A_012','A_014','A_015','A_016','A_017','A_018','A_019','V_001','V_002'],
                ['A_026','A_027','A_030','A_033','A_034','A_035','V_003'],
                ['A_039','A_040','A_041','A_042','A_044']]
        chains=[['A_010','A_011','A_012','A_015','A_016','A_017','A_018','A_019'],
                ['A_033','A_034','A_035'],['A_039','A_040','A_041','A_042','A_044']]
        excluded=['A_003','A_004','A_006','A_024','A_046','A_049','V_004','V_005']
        joins=[['A_011','A_012'],['A_016','A_017'],['A_041','A_042']];forbidden=[]
        figures={'A_009':['V_001'],'A_014':['V_002'],'A_030':['V_003']}
    title_groups = ([['A_005'],['A_020'],['A_033','A_041','A_043','A_046'],['A_048','A_049']] if index==0 else
                    [['D000','D009','D013','D015','D018']] if index==1 else
                    [['A_003'],['A_007']] if index==2 else [['A_007'],['A_025','A_036'],['A_038','A_043']])
    return dict(article_groups=groups,title_groups=title_groups,reading_chains=chains,excluded=excluded,continuations=joins,
                forbidden_continuations=forbidden,figures=figures,annotation='assistant source-reviewed partial development reference; not independent expert gold')


def role_prompt(payload):
    return '''Review source block ROLES ONLY. Do not cluster articles or infer reading order.
Return JSON {"roles":{"N001":"BODY|CAPTION|TABLE|VISUAL|STRUCTURAL|PAGE_CONTEXT|UNRESOLVED",...}}.
Cover every N once. BODY is substantive narrative; CAPTION describes a specific figure/table.
Parser types can be wrong: full narrative columns are BODY even if parser-caption; actual captions
may be parser paragraphs. Titles/decks/rubrics/bylines are STRUCTURAL. Running headers, logos,
publication labels, photo credits and page navigation are PAGE_CONTEXT. Unreadable/unsupported
annotations are UNRESOLVED. Preserve visual/table modality except explicit page chrome.
Use text, geometry and original page image; descriptions are unverified hints. Never invent words.
PAGE:\n'''+json.dumps(payload,ensure_ascii=False)


def validate_roles(value,payload):
    roles=value.get('roles') if isinstance(value,dict) else None
    if not isinstance(roles,dict):raise ValueError('roles object required')
    # Reuse strict role/modality checks without supplying or inferring article identities.
    context=[n for n in roles if roles[n]=='PAGE_CONTEXT']; other=[n for n in roles if n not in context]
    groups=[]
    for gid,kind,ids in [('content','article',other),('chrome','page_context',context)]:
        if ids:groups.append(dict(id=gid,kind=kind,nodes=ids,title_ids=[],flows=[]))
    fake=dict(groups=groups,roles=roles,page_context_title_ids=[t['label'] for t in payload['titles']],unassigned_nodes=[],conflicted_nodes=[])
    first.validate_raw(fake,payload)
    return dict(roles=roles)


def member_prompt(payload,roles,order=None):
    prompt=first.membership_prompt(payload)+'\nFROZEN_ROLE_REVIEW (identical in both experiment arms; copy exactly):\n'+json.dumps(roles)
    if order is not None:
        prompt+='\nEARLIER READING PROPOSAL:\n'+json.dumps(order)+'\nThis is fallible navigation evidence, NOT article membership. Never equate one reading flow with one article. Independent headlines remain separate even if the proposal connects them.'
    return prompt


def validate_member(value,payload,roles):
    value=first.validate_raw(value,payload)
    if value['roles']!=roles:raise ValueError('roles frozen identically across both arms; do not change them')
    return value


def order_prompt(payload,roles,member=None):
    result='''Reconstruct source reading flows on raw parsing blocks BEFORE evidence-node assembly.
Use source image, column geometry, sentence continuity and headings. Never simply sort supplied JSON
or parser IDs. Independent stories may have separate flows. Keep body/caption/footnote/sidebar flows
separate; titles, rubrics, page chrome and unresolved OCR are not body nodes. Do not invent words.
Every eligible BODY/CAPTION/TABLE/VISUAL N label must occur once in flows OR unsequenced. Put standalone
VISUAL/TABLE in unsequenced; do not put them into body/caption text flows. Uncertain order may remain
unsequenced. BODY can belong to body, sidebar or footnote flows; CAPTION only to caption flows.
Return JSON {"flows":[{"kind":"body|caption|footnote|sidebar","nodes":["N001"]}],"unsequenced":[]}.
FROZEN_ROLES:\n'''+json.dumps(roles)+'\nPAGE:\n'+json.dumps(payload,ensure_ascii=False)
    if member is not None:
        result+='\nEARLIER ARTICLE PROPOSAL:\n'+json.dumps(member)+'\nRespect confirmed article boundaries when deciding reading flows. This is a fallible membership proposal; leave unclear order unsequenced.'
    return result


def prepare(out):
    if (out/'manifest.json').exists():verify(out);return
    out.mkdir(parents=True,exist_ok=True); fingerprints={}
    for i,task in enumerate(TASKS):
        rep=read(SOURCE/task/'input_representation.json')
        paths=list((ROOT/'EvidenceNet/output/hybrid_49page_stress_run_20261007').glob('batch_*/embedding_geometry/visual_descriptions.jsonl'))
        desc={}
        for path in paths:
            selected=[r for r in rows(path) if r['task']==task]
            if selected:
                if desc:raise ValueError('duplicate description source')
                desc={r['visual_id']:r for r in selected};fingerprints[str(path.resolve())]=sha(path)
        if set(desc)!={v['visual_bundle_id'] for v in rep['visual_bundles']}:raise ValueError('missing descriptions: '+task)
        for row in desc.values():
            p=Path(row['crop'])
            if sha(p)!=row['crop_sha256']:raise ValueError('stale description crop')
            fingerprints[str(p.resolve())]=sha(p)
        for name in ['input_representation.json','original.png']:
            p=SOURCE/task/name;fingerprints[str(p.resolve())]=sha(p)
        raw=first.raw_input(rep,desc); ref=reference(i)
        available={a['atom_id'] for a in rep['atoms']}|{v['visual_bundle_id'] for v in rep['visual_bundles']}
        referenced=set(sum(ref['article_groups']+ref['reading_chains']+ref['continuations']+ref['forbidden_continuations'],[]))|set(ref['excluded'])|set(sum(ref['title_groups'],[]))|set(ref['figures'])|set(sum(ref['figures'].values(),[]))
        if referenced-available:raise ValueError('invalid reference IDs '+str(referenced-available))
        dest=out/('page_%d'%i)
        for name,value in [('raw_input.json',raw),('source.json',rep),('descriptions.json',desc),('reference.json',ref)]:
            write(dest/name,value);fingerprints[str((dest/name).resolve())]=sha(dest/name)
    write(out/'protocol.json',dict(tasks=TASKS,arms=['article_first','reading_first'],presentations=['original','reversed'],
        common_model=str(first.MODEL),common_embedding=str(first.EMBEDDING),common_role_review=True,
        stage_orders=dict(article_first=['roles','membership','raw reading','node composition','node reading edges'],
                          reading_first=['roles','raw reading','membership','node composition','node reading edges']),
        input_reversal='reverse supplied raw-node and title list only; labels, contents, geometry and image unchanged',
        deterministic_model=True,independent_holdout=False,semantic_edges_generated=False,cross_page_evaluated=False,
        comparison_limits='4 development spreads; order robustness is not stochastic run stability or full-document accuracy'))
    files=[Path(__file__),Path(first.__file__),ROOT/'EvidenceNet/evidence_graph/article_order.py',
           ROOT/'EvidenceNet/evidence_graph/hybrid_article_clustering.py',ROOT/'EvidenceNet/scripts/run_hybrid_article_clustering.py',
           ROOT/'EvidenceNet/evidence_graph/llm_client.py',ROOT/'EvidenceNet/scripts/bounded_geometry.py',
           ROOT/'EvidenceNet/scripts/run_embedding_geometry_node_baseline.py',ROOT/'EvidenceNet/scripts/evidence_node_guards.py',out/'protocol.json']
    fingerprints.update({str(p.resolve()):sha(p) for p in files})
    write(out/'manifest.json',dict(files=fingerprints))
    print(json.dumps(dict(prepared_pages=len(TASKS),paired_results=16)),flush=True)


def verify(out):
    for path,digest in read(out/'manifest.json')['files'].items():
        if sha(Path(path))!=digest:raise ValueError('changed comparison source/code: '+path)


def compose_candidates(raw,member,order,vectors,size):
    import numpy as np
    flows,cross=owned_flows(order,member);lookup=raw['block_lookup'];bylabel={n['label']:n for n in raw['payload']['nodes']}
    pairs=[]; seen=set()
    for f in flows:
        if f['kind']!='body':continue
        for a,b in zip(f['nodes'],f['nodes'][1:]):
            if (a,b) in seen:continue
            seen.add((a,b))
            lt=bylabel[a]['members'][0]['text'];rt=bylabel[b]['members'][0]['text']
            if sentence_block(lt,rt):continue
            def rect(n):
                box=bylabel[n]['bbox'];return box if box and isinstance(box[0],list) else [box]
            geometry=min(pair_hint(x,y,[],size)['score'] for x in rect(a) for y in rect(b))
            pairs.append(dict(candidate_id='P%03d'%(len(pairs)+1),left=a,right=b,article_group=f['article_group'],
                              geometry_score=float(geometry),embedding_cosine=float(np.dot(vectors[a],vectors[b]))))
    # All same-article visuals are judged jointly for each caption; embedding/geometry provide ranking.
    figure_pool=[]
    for g in member['groups']:
        if g['kind']!='article':continue
        for cap in [n for n in g['nodes'] if member['roles'][n]=='CAPTION']:
            ranked=[]
            for visual in [n for n in g['nodes'] if member['roles'][n]=='VISUAL']:
                def rect(n):
                    box=bylabel[n]['bbox'];return box if box and isinstance(box[0],list) else [box]
                score=min(pair_hint(a,b,[],size)['score'] for a in rect(cap) for b in rect(visual))
                ranked.append(dict(visual=visual,geometry_score=float(score),embedding_cosine=float(np.dot(vectors[cap],vectors[visual]))))
            # Keep all local images together on bounded smoke pages; no threshold removes part of a figure.
            figure_pool.append(dict(caption=cap,article_group=g['id'],visuals=sorted(ranked,key=lambda r:(r['geometry_score'],-r['embedding_cosine']))))
    return dict(pairs=pairs,figures=figure_pool),flows,cross


def composition_prompt(raw,member,pool):
    return '''Decide source-exact evidence composition inside the FIXED article map.
BODY pairs are consecutive in an earlier fallible reading proposal. CONTINUATION requires a single
sentence/word split by parsing, not just the same paragraph/topic. A new quotation or independent sentence
is SEPARATE. Do not repair corrupted OCR by guessing missing words. Use all source blocks for context.
For each CAPTION, select the COMPLETE figure's visual crops jointly; a portrait strip may span several
crops. Do not attach a whole-figure caption to just one part. Return scope PARTIAL/UNCERTAIN if the supplied
assets cannot establish the whole scope. Only COMPLETE groups will be combined; no visual may belong to
two complete captions. Do not absorb BODY into images. Original geometry/image overrides parser sequence.
Return JSON {"pairs":[{"candidate_id":"P001","decision":"CONTINUATION|SEPARATE"}],
"figures":[{"caption":"N001","visuals":["N002"],"scope":"COMPLETE|PARTIAL|UNCERTAIN|NONE"}]}.
Cover every supplied pair and caption once. Prefer separation when uncertain. JSON only.
ROLES:\n'''+json.dumps(member['roles'])+'\nBLOCKS:\n'+json.dumps(raw['payload'],ensure_ascii=False)+'\nCANDIDATES:\n'+json.dumps(pool)


def validate_composition(value,pool):
    if not isinstance(value,dict) or not isinstance(value.get('figures'),list):raise ValueError('figures list required')
    first.validate_nodes(dict(pairs=value.get('pairs'),captions=[]),dict(pairs=pool['pairs'],captions=[]))
    lookup={r['caption']:r for r in pool['figures']};seen=[];used=[]
    for row in value['figures']:
        if not isinstance(row,dict) or row.get('caption') not in lookup:raise ValueError('unknown caption')
        cap=row['caption'];seen.append(cap);visuals=row.get('visuals')
        expected={r['visual'] for r in lookup[cap]['visuals']}
        if not isinstance(visuals,list) or any(not isinstance(v,str) or v not in expected for v in visuals) or len(visuals)!=len(set(visuals)):
            raise ValueError('visual group outside article candidate ownership')
        if row.get('scope') not in {'COMPLETE','PARTIAL','UNCERTAIN','NONE'}:raise ValueError('figure scope required')
        if row['scope']=='COMPLETE':
            if not visuals:raise ValueError('complete figure requires a visual')
            used.extend(visuals)
        if row['scope']=='NONE' and visuals:raise ValueError('NONE figure must be empty')
    if Counter(seen)!=Counter(lookup.keys()) or len(used)!=len(set(used)):raise ValueError('cover all captions, no duplicated figure ownership')
    pairs={r['candidate_id']:r for r in pool['pairs']}
    validate_paths([(pairs[r['candidate_id']]['left'],pairs[r['candidate_id']]['right']) for r in value['pairs'] if r['decision']=='CONTINUATION'])
    return value


def assemble(raw,member,pool,decision,rep,desc,task):
    cap_pool=[];cap_dec=[]
    for group in decision['figures']:
        if group['scope']!='COMPLETE':continue
        for visual in group['visuals']:
            cid='C%03d'%(len(cap_pool)+1)
            cap_pool.append(dict(candidate_id=cid,caption=group['caption'],visual=visual))
            cap_dec.append(dict(candidate_id=cid,decision='ATTACH'))
    nodes,exclusions,checks=first.assemble(raw,member,dict(pairs=[],captions=cap_pool),dict(pairs=[],captions=cap_dec),rep,desc,task)
    pairmap={r['candidate_id']:r for r in pool['pairs']}
    selected=[(pairmap[r['candidate_id']]['left'],pairmap[r['candidate_id']]['right']) for r in decision['pairs'] if r['decision']=='CONTINUATION']
    paths=validate_paths(selected);bylabel={label:n for n in nodes for label in n['raw_block_labels']};source={a['atom_id']:a for a in rep['atoms']}
    merged=[];consumed=set()
    for path in paths:
        members=[bylabel[n] for n in path]
        if any(n['unit_type']!='TEXT' or len(n['raw_block_labels'])!=1 for n in members):raise ValueError('body path endpoints must be singleton text nodes')
        if len({n['article_id'] for n in members})!=1 or members[0]['article_id'] is None:raise ValueError('path crosses article')
        if any(sentence_block(text_of(source[members[i]['source_atom_ids'][0]]),text_of(source[members[i+1]['source_atom_ids'][0]])) for i in range(len(members)-1)):
            raise ValueError('path violates sentence guard')
        aids=[a for n in members for a in n['source_atom_ids']]
        node=deepcopy(members[0]);node.update(source_atom_ids=aids,
            source_fragment_ids=[f['fragment_id'] for a in aids for f in source[a]['text_fragments']],
            plain_text='\n'.join(text_of(source[a]) for a in aids),raw_block_labels=path,
            geometry_members=[g for n in members for g in n['geometry_members']],
            node_id=stable_id(rep['document_id']+'_'+rep['page']+'_AO_',aids))
        merged.append(node);consumed.update(n['node_id'] for n in members)
    result=[n for n in nodes if n['node_id'] not in consumed]+merged
    if Counter(a for n in result for a in n['source_atom_ids'])!=Counter(a for n in nodes for a in n['source_atom_ids']):raise ValueError('body composition lost or duplicated source')
    if Counter(f for n in result for f in n['source_fragment_ids'])!=Counter(f for n in nodes for f in n['source_fragment_ids']):raise ValueError('body composition lost fragments')
    for n in result:n['node_policy']='article_order_comparison_common_composition_v1'
    return result,exclusions,checks


def reachability(edges):
    graph={}
    for a,b in edges:graph.setdefault(a,set()).add(b)
    result=set()
    for start in graph:
        queue=list(graph[start]);seen=set()
        while queue:
            cur=queue.pop()
            if cur in seen:continue
            seen.add(cur);result.add((start,cur));queue.extend(graph.get(cur,[]))
    return result


def evaluate(raw,member,order,nodes,excluded,ref):
    source=raw['block_lookup'];owner={source[n]['source_id']:g['id'] for g in member['groups'] if g['kind']=='article' for n in g['nodes'] if member['roles'][n] not in {'UNRESOLVED','STRUCTURAL','PAGE_CONTEXT'}}
    expected={n:i for i,g in enumerate(ref['article_groups']) for n in g};counts=Counter()
    for a,b in itertools.combinations(sorted(expected),2):
        actual=a in owner and b in owner and owner[a]==owner[b];positive=expected[a]==expected[b]
        counts['tp' if actual and positive else 'fp' if actual else 'fn' if positive else 'tn']+=1
    flows,cross=owned_flows(order,member)
    raw_edges=[(source[a]['source_id'],source[b]['source_id']) for f in flows if f['kind']=='body' for a,b in zip(f['nodes'],f['nodes'][1:])]
    reached=reachability(raw_edges);refs=[(a,b) for chain in ref['reading_chains'] for a,b in zip(chain,chain[1:])]
    exclusion_ids={r['source_id'] for r in excluded}
    compositions=set((a,b) for n in nodes if n['unit_type']=='TEXT' for a,b in zip(n['source_atom_ids'],n['source_atom_ids'][1:]))
    figures={a:set(n['source_visual_bundle_ids']) for n in nodes for a in n['source_atom_ids'] if n['source_visual_bundle_ids']}
    title_owner={t['id']:next((g['id'] for g in member['groups'] if g['kind']=='article' and t['label'] in g['title_ids']),None) for t in raw['payload']['titles']}
    title_checks=[]
    for gold_group,titles in zip(ref['article_groups'],ref.get('title_groups',[])):
        anchor=gold_group[0]
        title_checks.extend(bool(title_owner.get(t)) and title_owner[t]==owner.get(anchor) for t in titles)
    return dict(title_ownership_total=len(title_checks),title_ownership_correct=sum(title_checks),article_pair_confusion=dict(counts),article_reference_nodes=len(expected),assigned_reference_nodes=sum(n in owner for n in expected),
        reading_constraints=len(refs),reading_recovered=sum((a,b) in reached for a,b in refs),reading_reversed=sum((b,a) in reached for a,b in refs),
        raw_cross_article_adjacencies=len(cross),reference_exclusions=len(ref['excluded']),excluded_correct=sum(n in exclusion_ids for n in ref['excluded']),
        continuation_positive_total=len(ref['continuations']),continuation_recovered=sum(tuple(p) in compositions for p in ref['continuations']),
        forbidden_joins=sum(tuple(p) in compositions for p in ref['forbidden_continuations']),
        figures_total=len(ref['figures']),figure_scope_exact=sum(figures.get(cap,set())==set(vs) for cap,vs in ref['figures'].items()),
        note='partial development source reference; reading metric is reachability, not exact adjacency')


def snapshot(raw,member,order,nodes):
    lookup=raw['block_lookup'];owner={lookup[n]['source_id']:g['id'] for g in member['groups'] if g['kind']=='article' for n in g['nodes'] if member['roles'][n] not in {'UNRESOLVED','STRUCTURAL','PAGE_CONTEXT'}}
    cocluster=[tuple(sorted((a,b))) for a,b in itertools.combinations(owner,2) if owner[a]==owner[b]]
    flows,_=owned_flows(order,member)
    edges=[(lookup[a]['source_id'],lookup[b]['source_id']) for f in flows if f['kind']=='body' for a,b in zip(f['nodes'],f['nodes'][1:])]
    groups=[tuple(sorted(n['source_atom_ids']+n['source_visual_bundle_ids'])) for n in nodes]
    title_links=[(t['id'],lookup[n]['source_id']) for t in raw['payload']['titles'] for g in member['groups']
                 if g['kind']=='article' and t['label'] in g['title_ids'] for n in g['nodes'] if lookup[n]['source_id'] in owner]
    return dict(title_memberships=sorted(title_links),assigned_sources=sorted(owner),article_pairs=sorted(cocluster),reading_edges=sorted(edges),node_groups=sorted(groups))


def run_page(out,index,device):
    prepare(out);verify(out);page=out/('page_%d'%index);raw=read(page/'raw_input.json');rep=read(page/'source.json');desc=read(page/'descriptions.json');ref=read(page/'reference.json')
    import torch
    from PIL import Image
    torch.set_num_threads(32 if device=='cpu' else 16)
    if not (page/'embeddings.json').exists():
        vectors=first.embed_cpu([n['members'][0]['text'] for n in raw['payload']['nodes']])
        write(page/'embeddings.json',{n['label']:v.tolist() for n,v in zip(raw['payload']['nodes'],vectors)})
    vectors=read(page/'embeddings.json');image=str(SOURCE/TASKS[index]/'original.png')
    with Image.open(image) as im:size=im.size
    model=create_llm(dict(provider='transformers',model=str(first.MODEL),dtype='bfloat16',device_map='cpu' if device=='cpu' else 'auto',require_cuda=device!='cpu',enable_thinking=False))
    write(page/'execution.json',dict(device=device,job_id=__import__('os').environ.get('SLURM_JOB_ID'),model=str(first.MODEL)))
    role_result=call(model,page/'roles.json',role_prompt(raw['payload']),[image],lambda v:validate_roles(v,raw['payload']),2200)
    if not role_result['valid']:raise RuntimeError('shared role review failed')
    roles=role_result['value']['roles'];results=[]
    # Counterbalance which order runs first across pages/presentations.
    for variation in range(2):
        payload=deepcopy(raw['payload'])
        if variation:payload['nodes'].reverse();payload['titles'].reverse()
        arms=['article_first','reading_first']
        if (index+variation)%2:arms.reverse()
        for arm in arms:
            start=time.monotonic();dest=page/('%s_%d'%(arm,variation));summary_path=dest/'summary.json'
            if summary_path.exists():results.append(read(summary_path));continue
            member=None;order=None;records=[]
            try:
                for stage in (['membership','reading'] if arm=='article_first' else ['reading','membership']):
                    if stage=='membership':
                        rec=call(model,dest/'membership.json',member_prompt(payload,roles,order),[image],lambda v:validate_member(v,payload,roles),3400)
                        if rec['valid']:member=rec['value']
                    else:
                        rec=call(model,dest/'raw_reading.json',order_prompt(payload,roles,member),[image],lambda v:validate_order(v,payload,roles),2200)
                        if rec['valid']:order=rec['value']
                    records.append(rec)
                    if not rec['valid']:raise RuntimeError(stage+' failed structural validation')
                armraw=dict(raw,payload=payload)
                pool,flows,cross=compose_candidates(armraw,member,order,vectors,size);write(dest/'candidates.json',pool)
                rec=call(model,dest/'composition.json',composition_prompt(armraw,member,pool),[image],lambda v:validate_composition(v,pool),2200)
                records.append(rec)
                if not rec['valid']:raise RuntimeError('composition failed structural validation')
                nodes,excluded,checks=assemble(armraw,member,pool,rec['value'],rep,desc,TASKS[index]);jsonl(dest/'evidence_nodes.jsonl',nodes);jsonl(dest/'excluded_blocks.jsonl',excluded)
                bylabel={label:n['node_id'] for n in nodes for label in n['raw_block_labels']};edges=[]
                for f in flows:
                    # Preserve raw adjacency; collapse consecutive labels only when they are the SAME node.
                    for a,b in zip(f['nodes'],f['nodes'][1:]):
                        if a in bylabel and b in bylabel and bylabel[a]!=bylabel[b]:
                            edges.append(dict(source=bylabel[a],target=bylabel[b],type='NEXT',flow_kind=f['kind'],article_group=f['article_group']))
                jsonl(dest/'reading_edges.jsonl',edges)
                write(dest/'snapshot.json',snapshot(armraw,member,order,nodes))
                summary=dict(complete=True,page=index,arm=arm,presentation=variation,source_checks=checks,nodes=len(nodes),
                    unresolved_nodes=sum(n['article_id'] is None for n in nodes),articles=sum(g['kind']=='article' for g in member['groups']),
                    metrics=evaluate(armraw,member,order,nodes,excluded,ref),seconds=time.monotonic()-start,
                    invalid_attempts=sum(sum(not a['valid'] for a in r['attempts']) for r in records),
                    inference_calls=sum(len(r['attempts']) for r in records),
                    response_chars=sum(len(a.get('raw') or '') for r in records for a in r['attempts']))
            except Exception as exc:
                summary=dict(complete=False,page=index,arm=arm,presentation=variation,error=str(exc),seconds=time.monotonic()-start)
            write(summary_path,summary);results.append(summary);print(json.dumps(summary),flush=True)
    write(page/'summary.json',dict(results=results,complete=all(r['complete'] for r in results)))
    if not all(r['complete'] for r in results):raise RuntimeError('one or more comparison conditions failed; inspect page summary')


def report(out):
    results=[];stability=[]
    for i in range(len(TASKS)):
        page=out/('page_%d'%i)
        for arm in ['article_first','reading_first']:
            for v in range(2):
                path=page/('%s_%d'%(arm,v))/'summary.json'
                if path.exists():results.append(read(path))
            paths=[page/('%s_%d'%(arm,v))/'snapshot.json' for v in range(2)]
            if all(p.exists() for p in paths):
                a,b=map(read,paths);stability.append(dict(page=i,arm=arm,**{k+'_jaccard':jaccard(map(tuple,a[k]) if k!='assigned_sources' else a[k],map(tuple,b[k]) if k!='assigned_sources' else b[k]) for k in ['article_pairs','reading_edges','node_groups','assigned_sources','title_memberships']}))
    # Array workers write separate page summaries; a report can be rebuilt after all finish.
    arm_metrics={}
    for arm in ['article_first','reading_first']:
        selected=[r for r in results if r['arm']==arm and r['complete']]
        totals=Counter();confusion=Counter()
        for row in selected:
            confusion.update(row['metrics']['article_pair_confusion'])
            totals.update({k:v for k,v in row['metrics'].items() if isinstance(v,(int,float))})
        tp,fp,fn=confusion['tp'],confusion['fp'],confusion['fn']
        arm_metrics[arm]=dict(completed_conditions=len(selected),failed_conditions=sum(r['arm']==arm and not r['complete'] for r in results),
            article_pair_confusion=dict(confusion),article_pair_precision=tp/(tp+fp) if tp+fp else None,
            article_pair_recall=tp/(tp+fn) if tp+fn else None,
            totals=dict(totals),seconds=sum(r['seconds'] for r in selected),
            invalid_attempts=sum(r.get('invalid_attempts',0) for r in selected))
    aggregate=dict(arm_metrics=arm_metrics,expected_results=16,available_results=len(results),complete=len(results)==16 and all(r['complete'] for r in results),results=results,stability=stability)
    # Unique report per worker to avoid concurrent writes to a shared temporary path.
    return aggregate


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','run','report']);p.add_argument('--output',type=Path,default=OUT)
    p.add_argument('--page',type=int,choices=range(4));p.add_argument('--device',choices=['cpu','cuda'],default='cpu');args=p.parse_args()
    if args.command=='prepare':prepare(args.output)
    elif args.command=='run':
        if args.page is None:p.error('--page required for bounded worker')
        run_page(args.output,args.page,args.device)
    else:
        write(args.output/'comparison.json',report(args.output));print(json.dumps(report(args.output)),flush=True)
