#!/usr/bin/env python3
"""Broader frozen-corpus shadow test; unconfirmed article identities are isolated."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import json
import shutil

import run_article_bridge_pilot as v1
import run_article_bridge_binding_v2 as v2
from replay_article_bridge_identity_v3 import identity_gate, publish_intra
from replay_article_bridge_routing_v4 import select, pairs
from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, check

DEFAULT = ROOT / 'EvidenceNet/output/article_bridge_expanded_v5_20261012'


def prepare(out):
    if out.exists(): raise ValueError('fresh_output_required')
    source=v1.SOURCE;check(source);v1.checked(v1.DEFAULT)
    out.mkdir(parents=True);(out/'assets').symlink_to((source/'assets').resolve(),target_is_directory=True)
    nodes=rows(source/'units.jsonl');policies=read(source/'eligibility.json')
    reviewed=rows(v1.DEFAULT/'articles.jsonl');mapping={n:a['article_id'] for a in reviewed for n in a['node_ids']}
    oldpol=read(v1.DEFAULT/'eligibility.json');policies.update(oldpol)
    groups={a['article_id']:dict(a) for a in reviewed}; issues=[]
    for n in nodes:
        if n['id'] in mapping: continue
        confirmed=n.get('assignment_status')=='KNOWN_PAPER_DOCUMENT_PROFILE'
        aid='EXPANDED:'+n['document'] if confirmed else 'UNRESOLVED:'+n['id']
        mapping[n['id']]=aid
        group=groups.setdefault(aid,{'article_id':aid,'document':n['document'],'node_ids':[],
            'boundary_status':'KNOWN_PAPER_DOCUMENT_PROFILE' if confirmed else 'UNCONFIRMED_SINGLE_NODE',
            'coverage':'sampled pages only'})
        group['node_ids'].append(n['id'])
        if not confirmed: issues.append({'node_id':n['id'],'document':n['document'],'page':n['page'],
            'inherited_article_id':n.get('article_id'),'status':n.get('assignment_status'),
            'action':'isolated; no article-context propagation; same-document pairs excluded from cross-document routing'})
    for a in groups.values():a['sampled_pages']=sorted({n['page'] for n in nodes if n['id'] in a['node_ids']})
    routed={n['id']:{**n,'article_id':mapping[n['id']]} for n in nodes}
    refs,refissues=v1.unique_explicit_references(routed,policies)
    protected=[{'source':r['source'],'target':r['target'],'references':[r],'routes':['resolved_source_reference']} for r in refs]
    for name,data in [('units.jsonl',nodes),('articles.jsonl',groups.values()),('boundary_issues.jsonl',issues),
         ('protected_intra_article_candidates.jsonl',protected),('reference_issues.jsonl',refissues),
         ('reading_edges.jsonl',rows(source/'reading_edges.jsonl'))]:jsonl(out/name,data)
    write(out/'eligibility.json',policies);write(out/'unit_article_map.json',mapping);write(out/'binding_probe_spec.json',[])
    assets={m['crop']:sha(out/m['crop']) for n in nodes for m in n['members'] if m.get('crop')}
    write(out/'asset_sha256.json',assets)
    manifest=read(v1.DEFAULT/'manifest.json')
    manifest.update(experiment='article_bridge_expanded_v5',source=str(source),
        snapshot_files={p.name:sha(p) for p in out.iterdir() if p.is_file()},
        original_node_files=read(source/'manifest.json')['original_node_files'],
        limitations=['event/project ontology unchanged; concepts/methods may have no edges',
          'unconfirmed boundaries isolated; within-document linkage not evaluated for these nodes',
          'existing sampled node corpus, not newly parsed complete documents',
          'previous experiments may have seen these documents; not an independent held-out benchmark'])
    for name in ['run_article_bridge_binding_v2.py','replay_article_bridge_identity_v3.py','replay_article_bridge_routing_v4.py',Path(__file__).name]:
        p=Path(__file__).with_name(name).resolve();manifest['code_sha256'][str(p)]=sha(p)
    write(out/'manifest.json',manifest);(out/'code').mkdir()
    for p in manifest['code_sha256']:shutil.copy2(p,out/'code'/Path(p).name)
    write(out/'corpus_summary.json',{'documents':len({n['document'] for n in nodes}),
        'pages':len({(n['document'],n['page']) for n in nodes}),'nodes':len(nodes),
        'eligible_nodes':sum(p['eligible'] for p in policies.values()),'unconfirmed_nodes':len(issues),
        'new_documents_vs_bridge_v1':sorted({n['document'] for n in nodes}-{a['document'] for a in reviewed})})
    print((out/'corpus_summary.json').read_text(),flush=True)


def run(out):
    v1.checked(out)
    from run_own_corpus_edges import llm
    model=llm();nodes={n['id']:n for n in rows(out/'units.jsonl')};policies=read(out/'eligibility.json');mapping=read(out/'unit_article_map.json')
    mentions=v1.index_subjects(model,out,nodes,policies,mapping)
    v1.figure_bindings(model,out,nodes,policies,mapping,mentions)
    for name in ['subject_mentions.jsonl','context_bindings.jsonl']:shutil.copy2(out/name,out/('v1_'+name))
    groups={}
    for m in mentions:
        key=(m['article_id'],m['subject_id'])
        g=groups.setdefault(key,{'group_id':'G_'+v2.digest(key)[:12],'article_id':key[0],
            'literal_subject_id':key[1],'kind':m['kind'],'name':m['source_mention'],'mentions':[]})
        g['mentions'].append(m)
    jsonl(out/'identity_groups.jsonl',groups.values());jsonl(out/'alias_candidates.jsonl',v2.alias_candidates(list(groups.values())))
    subjects,gmap=v2.resolve_aliases(model,out);queue=v2.binding_queue(out,gmap)
    bindings=v2.verify_bindings(model,out,nodes,policies,mapping,subjects,queue)
    jsonl(out/'raw_node_subject_bindings.jsonl',bindings)
    smap={s['subject_id']:s for s in subjects}
    bindings=[identity_gate(b,smap[b['subject_id']],nodes,mapping) for b in bindings]
    jsonl(out/'node_subject_bindings.jsonl',bindings)
    # Strictly cross-DOCUMENT comparison avoids calling isolated same-page nodes different articles.
    docmap={nid:n['document'] for nid,n in nodes.items()}
    rankings=v2.full_rankings(nodes,policies)
    global12=[{'source':n,'targets':[t for t in r if docmap[n]!=docmap[t]][:12]} for n,r in sorted(rankings.items())]
    guided=select(rankings,docmap,bindings,8,4)
    for name,routes in [('global12',global12),('protected8_plus4',guided)]:
        jsonl(out/('routes_'+name+'.jsonl'),routes)
        edges=[v2.derive_pair({'pair_id':'EXP_'+v2.digest(k)[:12],'source':k[0],'target':k[1]},bindings) for k in sorted(pairs(routes))]
        jsonl(out/('edges_'+name+'.jsonl'),[e for e in edges if e['paths']])
    cross=rows(out/'edges_protected8_plus4.jsonl');intra=publish_intra(bindings)
    jsonl(out/'intra_article_semantic_edges.jsonl',intra);jsonl(out/'semantic_edges.jsonl',cross+intra)
    jsonl(out/'article_navigation_edges.jsonl',v2.navigation(bindings))
    # Source-review sample covers accepted and unbound eligible nodes per document.
    review=[];bound={b['node_id'] for b in bindings if v2.graph_binding(b)}
    for doc in sorted(set(docmap.values())):
        for status in [True,False]:
            pool=[n for n in sorted(nodes) if docmap[n]==doc and policies[n]['eligible'] and (n in bound)==status]
            for nid in pool[:3]:review.append({'node_id':nid,'document':doc,'has_binding':status,'source_review':'PENDING'})
    jsonl(out/'node_source_review_queue.jsonl',review)
    report(out)


def report(out):
    v1.checked(out)
    optional=lambda name: rows(out/name) if (out/name).exists() else []
    bs=optional('node_subject_bindings.jsonl');nodes=rows(out/'units.jsonl');pol=read(out/'eligibility.json')
    bydoc=[]
    for doc in sorted({n['document'] for n in nodes}):
        ns=[n for n in nodes if n['document']==doc];ids={n['id'] for n in ns};bound={b['node_id'] for b in bs if b['node_id'] in ids and v2.graph_binding(b)}
        bydoc.append({'document':doc,'nodes':len(ids),'eligible':sum(pol[n]['eligible'] for n in ids),'bound_nodes':len(bound),
            'visual_nodes':sum(any(m['kind']=='visual' for m in n['members']) for n in ns)})
    summary={'phase':'COMPLETE_AWAITING_SOURCE_AUDIT' if (out/'semantic_edges.jsonl').exists() else 'PARTIAL_OR_NOT_STARTED',
        'corpus':read(out/'corpus_summary.json'),'binding_statuses':dict(Counter(b['status'] for b in bs)),
        'documents':bydoc,'global12_edges':len(optional('edges_global12.jsonl')),
        'guided_edges':len(optional('edges_protected8_plus4.jsonl')),'intra_edges':len(optional('intra_article_semantic_edges.jsonl')),
        'index_errors':len(optional('index_errors.jsonl')),'retrieval_gain':'NOT_EVALUATED'}
    write(out/'summary.json',summary);(out/'REPORT.md').write_text('# Expanded corpus v5\n\n```json\n'+json.dumps(summary,indent=2)+'\n```\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','run','report']);p.add_argument('--output',type=Path,default=DEFAULT)
    a=p.parse_args();globals()[a.stage](a.output.resolve())
