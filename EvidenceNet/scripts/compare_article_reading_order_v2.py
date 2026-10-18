#!/usr/bin/env python3
"""V2 interface repair: fixed content roles and uncertain ownership are independent."""
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import shutil

import compare_article_reading_order as base
from run_hybrid_article_clustering import read, write, sha
from evidence_graph.hybrid_article_clustering import page_prompt, validate_membership
from evidence_graph.article_order import validate_order as strict_order

OUT=base.ROOT/'EvidenceNet/output/article_reading_order_comparison_v2_20261015'
OLD=base.OUT
_original_prepare=base.prepare
_original_assemble=base.assemble


def task_payload(payload,roles):
    """Only eligible content has assignable N labels; excluded text remains explicit context."""
    value=deepcopy(payload)
    eligible={'BODY','CAPTION','TABLE','VISUAL'}
    value['nodes']=[dict(n,fixed_role=roles[n['label']]) for n in payload['nodes'] if roles[n['label']] in eligible]
    value['excluded_context']=[dict(source_id=n['id'],fixed_role=roles[n['label']],bbox=n['bbox'],members=n['members'])
                               for n in payload['nodes'] if roles[n['label']] not in eligible]
    return value


def member_prompt(payload,roles,order=None):
    filtered=task_payload(payload,roles)
    prompt=page_prompt(filtered)+'''
Each visible assignable N label has a fixed_role. Do NOT output or change roles.
Roles describe content, while article ownership can independently remain uncertain. Put any content
with unclear ownership in unassigned_nodes. This never changes its BODY/VISUAL/etc. source role.
Only nodes in PAGE.nodes need assignment; excluded_context has no assignable N labels and is already retained.
Keep every T label in exactly one title_ids list or page_context_title_ids. Do not repeat a title.
Publication toolbar/logo crops may still occur among VISUAL inputs; use a page_context group when appropriate.
Return groups, page_context_title_ids, unassigned_nodes, conflicted_nodes and reason only; all flows=[].
'''
    if order is not None:
        prompt+='\nEARLIER READING PROPOSAL (fallible; does not define articles):\n'+base.json.dumps(order)
    return prompt


def validate_member(value,payload,roles):
    filtered=task_payload(payload,roles)
    if not isinstance(value,dict):raise ValueError('membership object required')
    trial=deepcopy(value)
    if 'roles' in trial and trial['roles']!=roles:
        raise ValueError('do not output/change content roles; membership only')
    trial.pop('roles',None)
    expected={n['label'] for n in filtered['nodes']}
    # Model may repeat already-excluded labels in unassigned; record and normalize only that harmless case.
    excluded={n['label'] for n in payload['nodes']}-expected
    ua=trial.get('unassigned_nodes',[])
    if not isinstance(ua,list):raise ValueError('unassigned_nodes list required')
    if any(not isinstance(n,str) for n in ua):raise ValueError('unassigned source labels must be strings')
    removed=[n for n in ua if n in excluded]
    trial['unassigned_nodes']=[n for n in ua if n not in excluded]
    try:
        checked=validate_membership(trial,filtered)
    except ValueError as exc:
        ts=[t for g in trial.get('groups',[]) if isinstance(g,dict) for t in g.get('title_ids',[])]+trial.get('page_context_title_ids',[])
        title_expected=Counter(t['label'] for t in payload['titles']);actual=Counter(ts)
        raise ValueError(str(exc)+'; title missing='+str(sorted((title_expected-actual).elements()))+
                         '; title duplicate/extra='+str(sorted((actual-title_expected).elements()))) from exc
    checked['roles']=deepcopy(roles) # Source roles remain fixed; never generated again by membership.
    checked['unassigned_nodes'].extend(sorted(excluded))
    checked['interface_normalization']=dict(already_excluded_unassigned=removed,retained_nonassignable=sorted(excluded))
    return checked


def order_prompt(payload,roles,member=None):
    filtered=task_payload(payload,roles)
    filtered_roles={n['label']:roles[n['label']] for n in filtered['nodes']}
    content_member=None
    if member is not None:
        content_member={k:deepcopy(member[k]) for k in ['groups','page_context_title_ids','unassigned_nodes','conflicted_nodes']}
        content_member['unassigned_nodes']=[n for n in content_member['unassigned_nodes'] if n in filtered_roles]
    prompt=base_order_prompt(filtered,filtered_roles,content_member)
    prompt+='\nEXACT READING CHECKLIST: '+base.json.dumps(dict(
        body=[n for n in filtered_roles if filtered_roles[n]=='BODY'],
        captions=[n for n in filtered_roles if filtered_roles[n]=='CAPTION'],
        standalone=[n for n in filtered_roles if filtered_roles[n] in {'VISUAL','TABLE'}]))
    prompt+='\nOnly these assignable N labels must appear in flows or unsequenced. excluded_context is already retained separately; never sequence it. Use fixed_role, not parser_type, for flow kinds.'
    return prompt


base_order_prompt=base.order_prompt


def validate_order(value,payload,roles):
    if not isinstance(value,dict):raise ValueError('reading object required')
    trial=deepcopy(value)
    unsequenced=trial.get('unsequenced')
    if not isinstance(unsequenced,list):raise ValueError('unsequenced list required')
    known={n['label'] for n in payload['nodes']}
    excluded={n for n in known if roles[n] not in {'BODY','CAPTION','TABLE','VISUAL'}}
    if any(not isinstance(n,str) or n not in known for n in unsequenced):
        raise ValueError('unknown source label in unsequenced')
    moved=[n for n in unsequenced if n in excluded]
    trial['unsequenced']=[n for n in unsequenced if n not in excluded]
    checked=strict_order(trial,payload,roles)
    checked['excluded_unsequenced']=moved # Not silently discarded: source IDs/roles remain in the raw snapshot.
    return checked


def assemble(raw,member,pool,decision,rep,desc,task):
    effective=deepcopy(member)
    context={n for g in member['groups'] if g['kind']=='page_context' for n in g['nodes']}
    uncertain=set(member.get('unassigned_nodes',[]))|set(member['conflicted_nodes'])
    for n,role in member['roles'].items():
        if n in context:effective['roles'][n]='PAGE_CONTEXT'
        elif n in uncertain and role in {'BODY','CAPTION','TABLE','VISUAL'}:effective['roles'][n]='UNRESOLVED'
    # Eligibility derived from article ownership is separate from immutable source modality/role.
    nodes,exclusions,checks=_original_assemble(raw,effective,pool,decision,rep,desc,task)
    lookup=raw['block_lookup']
    for n in nodes:
        n['source_block_roles']={label:member['roles'][label] for label in n['raw_block_labels']}
    for exclusion in exclusions:
        label=next((k for k,v in lookup.items() if v['kind']==exclusion['kind'] and v['source_id']==exclusion['source_id']),None)
        if label is not None:exclusion['source_role']=member['roles'][label]
    return nodes,exclusions,checks


def prepare(out):
    existed=(out/'manifest.json').exists()
    _original_prepare(out)
    if existed:return
    # Reuse exactly the shared role review and embeddings from V1, not model article/reading proposals.
    for i in range(len(base.TASKS)):
        for name in ['roles.json','embeddings.json']:
            original=OLD/('page_%d'%i)/name
            shutil.copy2(original,out/('page_%d'%i)/name)
    protocol=read(out/'protocol.json')
    protocol.update(interface_version=2,role_and_membership_independent=True,shared_roles_reused_from=str(OLD),
        changes=['membership/reading receive eligible N labels only; excluded source context retained',
                 'roles frozen externally, not regenerated in membership output',
                 'unknown article ownership does not require changing source content role',
                 'already-excluded unsequenced labels normalized with explicit provenance; invalid flows still rejected'])
    write(out/'protocol.json',protocol)
    manifest=read(out/'manifest.json')
    extra=[Path(__file__),out/'protocol.json']+[out/('page_%d'%i)/name for i in range(len(base.TASKS)) for name in ['roles.json','embeddings.json']]
    manifest['files'].update({str(p.resolve()):sha(p) for p in extra})
    write(out/'manifest.json',manifest)


def install():
    base.prepare=prepare
    base.member_prompt=member_prompt
    base.validate_member=validate_member
    base.order_prompt=order_prompt
    base.validate_order=validate_order
    base.assemble=assemble


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','run','report'])
    p.add_argument('--output',type=Path,default=OUT);p.add_argument('--page',type=int,choices=range(4));p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    args=p.parse_args();install()
    if args.command=='prepare':prepare(args.output)
    elif args.command=='run':
        if args.page is None:p.error('--page required')
        base.run_page(args.output,args.page,args.device)
    else:
        result=base.report(args.output);write(args.output/'comparison.json',result);print(base.json.dumps(result))
