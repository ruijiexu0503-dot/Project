"""Additive, type-aware retrieval-view eligibility audit for frozen EvidenceNet Nodes."""
from __future__ import annotations
import argparse, hashlib, json, re, time
from collections import Counter
from pathlib import Path
from .common import load_config, read_jsonl, repo_path, run_dir, sha256, tokens, write_jsonl

DEFAULT_CORPUS = 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/corpus_nodes.jsonl'
DEFAULT_POLICIES = 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/corpus_policies.json'
DEFAULT_BASE_VIEWS = 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/views.jsonl'
DEFAULT_FORMULA_VIEWS = 'EvidenceNet/output/formula_retrieval_v1_20261016/formula_context/views.jsonl'

def is_formula(member, text):
    return member.get('role') == 'equ' or member.get('type') in {'equation','formula'} or bool(re.search(r'\\(?:frac|sum|int|alpha|beta|gamma|hat|mathbf)\b|\$\$', text))

def route_for(member, text):
    if is_formula(member, text): return 'formula_symbolic_retrieval'
    if member.get('role') in {'fnote','footnote'} or re.search(r'https?://|\bdoi\b|\barxiv\b', text, re.I): return 'identifier_lexical_retrieval'
    if len(tokens(text)) <= 3: return 'short_text_identifier_retrieval'
    return 'short_text_semantic_retrieval'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',required=True); ap.add_argument('--corpus',default=DEFAULT_CORPUS); ap.add_argument('--policies',default=DEFAULT_POLICIES); ap.add_argument('--base-views',default=DEFAULT_BASE_VIEWS); ap.add_argument('--formula-views',default=DEFAULT_FORMULA_VIEWS); args=ap.parse_args()
    config=load_config(args.config); out=run_dir(config); out.mkdir(parents=True,exist_ok=True)
    corpus_path, policy_path, base_path, formula_path=[repo_path(x) for x in (args.corpus,args.policies,args.base_views,args.formula_views)]
    nodes=list(read_jsonl(corpus_path)); policies=json.loads(policy_path.read_text())
    base_by_node={}
    for view in read_jsonl(base_path): base_by_node.setdefault(str(view['node_id']),[]).append(view)
    formula_by_node={}
    for view in read_jsonl(formula_path): formula_by_node.setdefault(str(view['node_id']),[]).append(view)
    audit=[]; additive=[]
    for node in sorted(nodes,key=lambda x:str(x['id'])):
        nid=str(node['id']); policy=policies[nid]; members={str(m['id']):m for m in node.get('members',[])}
        allowed=[m for m in policy.get('members',[]) if m.get('eligible')]
        original_reason=next((m.get('reason') for m in policy.get('members',[]) if not m.get('eligible') and m.get('reason')),None)
        base_count=len(base_by_node.get(nid,[])); formula_count=len(formula_by_node.get(nid,[]))
        record={'node_id':nid,'document_id':node.get('document'),'page_number':node.get('page'),'node_type':node.get('unit_type'),
                'node_status':node.get('status'),'original_policy_eligible':bool(policy.get('eligible')),
                'original_filter_reason':original_reason,'existing_base_view_count':base_count,'existing_formula_view_count':formula_count,
                'new_eligibility_status':None,'applicable_routes':[],'new_view_generated':False,'new_view_ids':[]}
        if base_count:
            record.update(new_eligibility_status='EXISTING_BASE_VIEW',applicable_routes=['existing_frozen_dense_bm25_routes'])
        elif formula_count:
            record.update(new_eligibility_status='REUSE_EXISTING_FORMULA_VIEW',applicable_routes=['formula_symbolic_retrieval'])
        elif policy.get('eligible'):
            # No token minimum: each policy-eligible member with source content receives an additive view.
            created=[]
            for item in allowed:
                member=members.get(str(item['member_id']),{}); text=str(member.get('text','')).strip()
                if not text: continue
                route=route_for(member,text); vid='STAGE1_ADD_'+hashlib.sha256((nid+'\0'+str(member.get('id'))+'\0'+text).encode()).hexdigest()[:16]
                additive.append({'view_id':vid,'node_id':nid,'document_id':node.get('document'),'article_id':node.get('article_id'),
                    'page_number':node.get('page'),'member_id':member.get('id'),'member_kind':member.get('kind'),'member_role':member.get('role'),
                    'kind':'type_aware_short_formula_or_identifier','retrieval_text':text,'quote':text,'identifiers':sorted(set(re.findall(r'\b[A-Za-z][A-Za-z0-9._/-]{1,}\b',text))),
                    'route_hint':route,'source_status':'ADDITIVE_STAGE1_SOURCE_TEXT','frozen_node_embedding_modified':False})
                created.append((vid,route))
            record.update(new_eligibility_status='ADDITIVE_VIEW_GENERATED' if created else 'ELIGIBLE_BUT_EMPTY_SOURCE',
                applicable_routes=sorted({r for _,r in created}),new_view_generated=bool(created),new_view_ids=[v for v,_ in created])
        else:
            visual=any(m.get('kind')=='visual' for m in policy.get('members',[]))
            record.update(new_eligibility_status='DEFER_VISUAL_METADATA_REVIEW' if visual else 'EXCLUDED_BY_FROZEN_POLICY',
                applicable_routes=['visual_metadata_retrieval_after_evidence_review'] if visual else [])
        audit.append(record)
    write_jsonl(out/'node_eligibility_audit.jsonl',audit); write_jsonl(out/'additive_type_aware_views.jsonl',additive)
    coverage=Counter(r['new_eligibility_status'] for r in audit)
    result={'run_id':config['run_id'],'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'canonical_nodes':len(audit),
      'nodes_with_existing_base_view':coverage['EXISTING_BASE_VIEW'],'nodes_reusing_formula_views':coverage['REUSE_EXISTING_FORMULA_VIEW'],
      'nodes_with_additive_views':coverage['ADDITIVE_VIEW_GENERATED'],'eligible_but_empty_source':coverage['ELIGIBLE_BUT_EMPTY_SOURCE'],
      'deferred_visual_metadata_review':coverage['DEFER_VISUAL_METADATA_REVIEW'],'excluded_by_frozen_policy':coverage['EXCLUDED_BY_FROZEN_POLICY'],
      'semantic_retrieval_eligible_after_adapter':coverage['EXISTING_BASE_VIEW']+coverage['REUSE_EXISTING_FORMULA_VIEW']+coverage['ADDITIVE_VIEW_GENERATED'],
      'additive_view_count':len(additive),'source_hashes':{str(p):sha256(p) for p in (corpus_path,policy_path,base_path,formula_path)},
      'contract':'Additive views only. Existing frozen views/vectors, Nodes, Structural Graph and historical outputs are read-only.'}
    (out/'eligibility_coverage.json').write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__': main()
