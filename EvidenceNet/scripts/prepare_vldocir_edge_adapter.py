#!/usr/bin/env python3
"""Adapt frozen VL-DocIR hybrid-v2 nodes to the post-node edge contract."""
from __future__ import annotations
import argparse, json, hashlib
from pathlib import Path
from run_node_context_edges import rows, jsonl, write, sha
from edge_source_roles import attach_source_roles, classify_node

ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(); p.add_argument('--nodes',type=Path,required=True); p.add_argument('--pages',type=Path,required=True); p.add_argument('--prepared',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    if a.output.exists(): raise ValueError('fresh adapter output required')
    pages={ (x['document_id'],int(x['page_number'])):x for x in rows(a.pages) }
    nodes=[]; policies={}; seen=set()
    for f in a.nodes.rglob('evidence_nodes.jsonl'):
        if 'hybrid' not in f.parts: continue
        for x in rows(f):
            nid=x['node_id']
            if nid in seen: continue
            seen.add(nid)
            task=x['hybrid_model_decision_file'].split('/nodes/')[1].split('/hybrid/')[0] if '/nodes/' in x.get('hybrid_model_decision_file','') else None
            # derive page identity from the node id and containing directory
            page_dir=f.parent.name; doc=page_dir.rsplit('/page_',1)[0] if '/page_' in page_dir else None
            if doc is None:
                parts=f.parts; page_name=next((z for z in parts if z.startswith('page_')),None); doc=parts[parts.index(page_name)-1] if page_name else None
            page_no=int(page_name.split('_')[1]) if page_name else None
            if (doc,page_no) not in pages: raise ValueError('page metadata missing '+str((doc,page_no)))
            pr=pages[doc,page_no]
            rep=json.loads((a.prepared/doc/f'page_{page_no:04d}'/'input_representation.json').read_text())
            if rep['official_image_sha256'] != pr['sha256']: raise ValueError('Page source mismatch')
            members=[]; allowed=[]
            text=str(x.get('plain_text') or '')
            boxes=[g['bbox'] for g in x.get('geometry_members',[]) if g.get('bbox')]
            mid=nid+'_TEXT'; members.append({'id':mid,'kind':'atom','type':'text','text':text,'boxes':boxes,'role':'text'}); allowed.append({'member_id':mid,'kind':'atom','eligible':bool(text.strip())})
            if x.get('visual_description'):
                vid=nid+'_VISUAL'; members.append({'id':vid,'kind':'visual','type':'description','text':str(x['visual_description']),'boxes':boxes,'role':'visual'}); allowed.append({'member_id':vid,'kind':'visual','eligible':True})
            node={'id':nid,'document':doc,'page':page_no,'article_id':doc,'source_collection':'vldocir','task':f'{doc}/page_{page_no:04d}','source_image_path':pr['image_path'],'members':members,'eligible_members':allowed,'node_type':x.get('unit_type'),'source_atom_ids':x.get('source_atom_ids',[]),'source_visual_bundle_ids':x.get('source_visual_bundle_ids',[])}
            node.update(source_image_sha256=pr['sha256'], geometry_image_size=rep['image_size'],
                        article_assignment='single_HTML_document; dataset document identity')
            node=attach_source_roles(node,rep)
            node['source_role_audit']=classify_node(node)
            nodes.append(node); policies[nid]={'eligible':True,'members':allowed}
    jsonl(a.output/'nodes.jsonl',nodes); write(a.output/'policies.json',policies)
    write(a.output/'manifest.json',{'source_nodes':str(a.nodes.resolve()),'source_pages':str(a.pages.resolve()),'node_count':len(nodes),'code_sha256':sha(Path(__file__)),
        'source_role_code_sha256':sha(Path(__file__).with_name('edge_source_roles.py'))})
    print(json.dumps({'nodes':len(nodes),'pages':len({(n['document'],n['page']) for n in nodes})}))
if __name__=='__main__': main()
