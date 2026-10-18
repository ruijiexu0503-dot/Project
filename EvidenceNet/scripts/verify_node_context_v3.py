#!/usr/bin/env python3
"""Replay a frozen candidate queue with indexed source spans and a semantic critic."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
from run_node_context_edges import read, rows, write, jsonl, sha, check, ROOT
from node_context_policy import eligibility
from verify_node_context import validate as validate_anchors

BASES={'SAME_NAMED_ENTITY','SAME_MEASUREMENT','METHOD_MECHANISM','FORMULA_SPECIALIZATION',
       'CAPTION_CONTENT','DIRECT_COMPARISON'}


def verification_policy(nodes):
    policies=eligibility(nodes)
    for node in nodes:
        for member,entry in zip(node['members'],policies[node['id']]['members']):
            if member['kind']!='visual' or not entry['eligible']:continue
            hint=member.get('text','')
            # Description is a conservative exclusion hint, never positive evidence.
            primary_logo=re.match(r'^The image (?:displays|shows|depicts|features) (?:a |an |the )?(?:(?:circular|corporate|stylized|colourful|colorful|company)\s+){0,3}logo\b',hint,re.I)
            boxes=member.get('boxes',[])
            thin=bool(boxes) and all((b[2]-b[0])/max(b[3]-b[1],1)>8 for b in boxes)
            navigation=thin and re.search(r'\b(?:navigation|menu|functional controls|interface)\b',hint,re.I) and re.search(r'\b(?:icons|buttons|banner)\b',hint,re.I)
            if primary_logo or navigation:
                entry.update(eligible=False,reason='primary_logo_hint_unverified' if primary_logo else 'thin_navigation_banner_hint_unverified')
        policies[node['id']]['eligible']=any(m['eligible'] for m in policies[node['id']]['members'])
    return policies


def source_spans(node, policy, label):
    """Display normalized whitespace, but select immutable contiguous raw spans."""
    allowed={(m['member_id'],m['kind']) for m in policy['members'] if m['eligible']}
    members=[];lookup={}
    for member in node['members']:
        if member['kind']!='atom' or (member['id'],'atom') not in allowed:continue
        text=member['text'];spans=[]
        # Omit padding from presentation, without deleting characters in the source.
        cuts=[(m.start(),m.end()) for m in re.finditer(r'(?:~\s*){5,}',text)]
        intervals=[];cursor=0
        for lo,hi in cuts:
            intervals.append((cursor,lo));cursor=hi
        intervals.append((cursor,len(text)))
        for lo,hi in intervals:
            while lo<hi:
                end=min(lo+480,hi)
                if end<hi:
                    space=text.rfind(' ',lo+240,end)
                    if space>=0:end=space+1
                raw=text[lo:end]
                if re.search(r'\w',raw):
                    sid=f'{label}:{member["id"]}:{len(spans):03d}'
                    spans.append({'span_id':sid,'text':re.sub(r'\s+',' ',raw).strip()})
                    lookup[sid]={'member_id':member['id'],'quote':raw,'char_start':lo,'char_end':end}
                lo=end
        if spans:members.append({'member_id':member['id'],'spans':spans})
    return members,lookup


def bind_spans(value, lookups):
    value=copy.deepcopy(value)
    if value.get('status')!='ACCEPT':return value
    for name,label in [('anchor_a','A'),('anchor_b','B')]:
        anchor=value.get(name,{})
        if not isinstance(anchor,dict):raise ValueError('anchor_invalid')
        if anchor.get('kind')=='TEXT':
            span=lookups[label].get(anchor.get('span_id'))
            if span is None or span['member_id']!=anchor.get('member_id'):raise ValueError('span_not_in_target_member')
            anchor.update(span)
    if value.get('relation_basis')=='DIRECT_COMPARISON':
        sid=value.get('comparison_span_id');matches=[spans[sid] for spans in lookups.values() if sid in spans]
        if len(matches)!=1:raise ValueError('comparison_span_invalid')
        value['comparison_quote']=matches[0]['quote']
    return value


def validate_v3(value,pair,nodes,policies):
    errors=validate_anchors(value,pair,nodes,policies)
    if errors or value.get('status')!='ACCEPT':return errors
    if value.get('relation_basis') not in BASES:return ['relation_basis_invalid']
    for label in ['a','b']:
        if value.get('evidence_role_'+label)!='CONTENT':return ['non_content_endpoint']
        if not isinstance(value.get('concept_'+label),str) or not value['concept_'+label].strip():return ['endpoint_concept_missing']
        anchor=value['anchor_'+label]
        if anchor['kind']=='VISUAL':
            observation=anchor['observation']
            if re.search(r'\b(?:logo|navigation|watermark|menu icon|branding)\b',observation,re.I):return ['visual_furniture_anchor']
            if re.search(r'(?:segment(?:ed|ation)?|pixel[- ](?:wise|level)|output mask)',observation,re.I) and re.search(r'\b(?:object localization|object detection|image classification|object classification)\b',value['concept_'+label],re.I):return ['visual_concept_contradicts_observation']
    if value['relation_basis']=='DIRECT_COMPARISON':
        # A visual juxtaposition alone does not supply an explicit comparison.
        evidence=value.get('comparison_quote','')
        if not isinstance(evidence,str) or len(evidence.strip())<12:return ['explicit_comparison_missing']
        texts=[m['text'] for nid in [pair['source'],pair['target']] for m in nodes[nid]['members'] if m['kind']=='atom' and
               any(e['eligible'] and e['kind']=='atom' and e['member_id']==m['id'] for e in policies[nid]['members'])]
        if not any(evidence in t for t in texts):return ['comparison_quote_not_in_source']
        if not re.search(r'\b(?:whereas|unlike|versus|compared|comparison|rather than|in contrast|both)\b',evidence,re.I):return ['comparison_not_explicit']
    return []


def prepare(out,source,version=3):
    check(source)
    if out.exists():raise ValueError('Requires a new experiment directory')
    out.mkdir(parents=True)
    names=['pages.json','units.jsonl','views.jsonl','reading_edges.jsonl','issues.jsonl','eligibility.json',
           'excluded_members.jsonl','candidate_pairs.jsonl','candidate_manifest.json','scored_pairs.jsonl','score_manifest.json']
    for name in names:shutil.copy2(source/name,out/name)
    shutil.copytree(source/'assets',out/'assets')
    shutil.copy2(source/'verification_queue.jsonl',out/'verification_queue.jsonl')
    policies=verification_policy(rows(out/'units.jsonl'));write(out/'verification_eligibility.json',policies)
    manifest=read(source/'manifest.json')
    manifest.update(experiment=f'evidence_node_context_edges_v{version}',verifier_version=version,
                    source_verification_experiment=str(source.resolve()),
                    source_verification_manifest_sha256=sha(source/'verification_manifest.json'),
                    fixed_queue_sha256=sha(out/'verification_queue.jsonl'),
                    visual_policy='primary furniture excluded; original crops only; source-span anchors and critic required')
    manifest['snapshot_files'].update({name:sha(out/name) for name in names+['verification_eligibility.json','verification_queue.jsonl']})
    (out/'code_snapshot').mkdir()
    for name in ['verify_node_context_v3.py','verify_node_context.py','node_context_policy.py','run_node_context_edges.py']:
        shutil.copy2(Path(__file__).parent/name,out/'code_snapshot'/name)
    if version==4:shutil.copy2(Path(__file__).parent/'node_context_coreference.py',out/'code_snapshot/node_context_coreference.py')
    manifest['final_code_snapshot_sha256']={p.name:sha(p) for p in (out/'code_snapshot').glob('*.py')}
    write(out/'manifest.json',manifest)
    report(out)


def targets_for(pair,nodes,policies,out):
    targets=[];images=[];lookups={}
    for label,nid in [('A',pair['source']),('B',pair['target'])]:
        text,lookups[label]=source_spans(nodes[nid],policies[nid],label)
        visual=[];allowed={(m['member_id'],m['kind']) for m in policies[nid]['members'] if m['eligible']}
        for m in nodes[nid]['members']:
            if m['kind']=='visual' and (m['id'],'visual') in allowed and m.get('crop'):
                path=out/m['crop']
                if not path.is_file():raise ValueError('Missing original crop')
                images.append(str(path));visual.append({'member_id':m['id'],'image_index':len(images),'crop_sha256':sha(path)})
        targets.append({'label':label,'source_members':text,'original_crops':visual})
    return targets,images,lookups


def verify(out):
    from run_own_corpus_edges import llm, MODEL
    from evidence_graph.llm_client import extract_json
    check(out);nodes={n['id']:n for n in rows(out/'units.jsonl')};policies=read(out/'verification_eligibility.json')
    version=read(out/'manifest.json').get('verifier_version',3)
    validator=validate_v3
    if version==4:
        from node_context_coreference import validate_v4, duplicate_caption, CORE_RULE, CRITIC_RULE
        validator=validate_v4
    queue=rows(out/'verification_queue.jsonl');model=None
    for i,pair in enumerate(queue):
        path=out/'context_decisions'/f'{pair["pair_id"]}.json'
        targets,images,lookups=targets_for(pair,nodes,policies,out)
        fingerprint=hashlib.sha256(json.dumps(targets,sort_keys=True).encode()).hexdigest()
        if path.exists():
            if read(path).get('input_sha256')!=fingerprint:raise ValueError('Stale verification decision')
            continue
        record={'pair':{k:pair[k] for k in ['pair_id','source','target']},'input_sha256':fingerprint,
                'model':str(MODEL),'script_sha256':sha(__file__),'verifier_version':version,
                'review_status':'MODEL_AND_CRITIC_NOT_HUMAN_VALIDATED'}
        if any(not policies[pair[k]]['eligible'] for k in ['source','target']):
            value={'pair_id':pair['pair_id'],'status':'REJECT','reason':'Endpoint contains only excluded furniture members.'}
            errors=[];record['policy_rejected']=True
        elif version==4 and duplicate_caption(nodes[pair['source']],nodes[pair['target']],policies):
            value={'pair_id':pair['pair_id'],'status':'REJECT','reason':'Overlapping duplicate caption extraction on the same page.'}
            errors=[];record['duplicate_caption_rejected']=True
        else:
            prompt=('Evaluate a concrete content relationship between A and B from original source spans and crops only. '
                    'First identify the actual endpoint concepts and evidence roles. Logos, navigation bars, branding, '
                    'watermarks and unreadable crops are not CONTENT. An organization name matching its logo is REJECT. '
                    'Accept only a specific correspondence using one relation_basis: SAME_NAMED_ENTITY (a specific event, '
                    'project or object with facts at both endpoints, not a generic subject), SAME_MEASUREMENT, '
                    'METHOD_MECHANISM (one endpoint explains or implements the specific other concept), '
                    'FORMULA_SPECIALIZATION, CAPTION_CONTENT, DIRECT_COMPARISON (requires explicit comparative source text). '
                    'A pair of task labels, examples of different tasks, or a topic named in a prior-work list is REJECT. '
                    'Computer vision: one box is localization; several object boxes are detection; category scores/class '
                    'labels are classification; a pixel mask from convolution + argmax is semantic segmentation. '
                    'Do not call a pixel mask classification or bounding-box localization. Never infer property or person '
                    'identity from a shared city, appearance, or external knowledge. Duplicate caption extraction is REJECT. '
                    'Every response MUST include a non-empty reason sentence. Return JSON with this schema: '
                    '{"pair_id":"provided pair ID","status":"ACCEPT|REJECT|UNCERTAIN","reason":"one sentence explaining the endpoint correspondence or rejection"}. ACCEPT additionally requires '
                    'relation_basis, concept_a, concept_b, evidence_role_a:CONTENT, evidence_role_b:CONTENT, '
                    'anchor_a, anchor_b. TEXT anchors select an existing span_id and member_id: '
                    '{kind:TEXT,member_id,span_id}; do not copy, rewrite, shorten or combine quotes. '
                    'VISUAL anchors are {kind:VISUAL,member_id,observation:specific visible feature}. '
                    'DIRECT_COMPARISON additionally selects comparison_span_id of a source span explicitly comparing the concepts. '
                    'A supported relation is symmetric RELATED_CONTEXT, not entailment.\n'+
                    json.dumps({'pair_id':pair['pair_id'],'targets':targets},ensure_ascii=False))
            if version==4:
                prompt=CORE_RULE+'\n'+prompt+'\nTEXT anchors MUST be JSON objects such as '+json.dumps({'kind':'TEXT','member_id':'choose exact member ID','span_id':'choose exact span ID'})+'. A and B have separate IDs; do not swap them.'
            if model is None:model=llm()
            attempts=[];value={};errors=[]
            for attempt in range(2):
                request=prompt+('\nCorrect these errors rather than repeating the previous response: '+json.dumps(errors)+
                                '. reason_missing means add the mandatory reason field with a non-empty explanation sentence. '
                                'Return the entire corrected JSON object.' if attempt else '')
                if version==4 and attempt:request+='\nPrevious response to correct:\n'+attempts[-1]['raw']
                raw=model.generate_raw_with_images('Verify specific evidence correspondence. JSON only.',request,images,950).raw
                attempts.append({'raw':raw,'prompt':request})
                try:value=bind_spans(extract_json(raw),lookups);errors=validator(value,pair,nodes,policies)
                except (ValueError,TypeError,KeyError) as exc:errors=[str(exc)]
                if not errors:break
            record['attempts']=attempts
            if not errors and value.get('status')=='ACCEPT':
                critic_prompt=('Audit the proposed relation independently against these two original targets/crops. '
                               'Return {status:CONFIRM|REJECT|UNCERTAIN,reason}. CONFIRM requires a specific semantic '
                               'correspondence beyond common topic or labels, grounded at both endpoints. '
                               'Reject logo/footer connections, implicit comparisons of unrelated task examples, '
                               'duplicate caption extraction, and confusion between classification, detection, localization '
                               'and pixel-wise semantic segmentation. Shared city does not identify a property. '
                               'A diagram explaining an explicitly named task is valid; two different task examples alone '
                               'are not. Check the actual crop instead of trusting the proposed observation.\n'+
                               json.dumps({'targets':targets,'proposal':value},ensure_ascii=False))
                if version==4:critic_prompt=CRITIC_RULE+'\n'+critic_prompt
                raw=model.generate_raw_with_images('Critically audit evidence, not model confidence. JSON only.',critic_prompt,images,550).raw
                try:
                    critic=extract_json(raw)
                    if not isinstance(critic,dict) or critic.get('status') not in {'CONFIRM','REJECT','UNCERTAIN'} or not isinstance(critic.get('reason'),str) or not critic['reason'].strip():raise ValueError('critic_schema_invalid')
                    record['critic']={**critic,'raw':raw,'prompt':critic_prompt}
                    if critic['status']!='CONFIRM':
                        record['initial_acceptance']=copy.deepcopy(value)
                        value={'pair_id':pair['pair_id'],'status':critic['status'],'reason':critic['reason']}
                except (ValueError,TypeError,KeyError) as exc:errors=[str(exc)]
        record.update(valid=not errors,value=value,errors=errors)
        write(path,record)
        print(json.dumps({'verified':i+1,'total':len(queue),'status':value.get('status'),'valid':not errors}),flush=True)
    ds=[read(out/'context_decisions'/f'{p["pair_id"]}.json') for p in queue]
    write(out/'verification_manifest.json',{'queue':len(queue),'verifier_version':version,
        'scopes':dict(Counter(p['scope'] for p in queue)),
        'statuses':dict(Counter(d['value'].get('status','INVALID') if d['valid'] else 'INVALID' for d in ds)),
        'policy_rejected':sum(d.get('policy_rejected',False) for d in ds),
        'duplicate_caption_rejected':sum(d.get('duplicate_caption_rejected',False) for d in ds),
        'critic_rejected_or_uncertain':sum('initial_acceptance' in d for d in ds),
        'scored_sha256':sha(out/'scored_pairs.jsonl'),'queue_sha256':sha(out/'verification_queue.jsonl'),
        'decision_files':{str(p.relative_to(out)):sha(p) for p in sorted((out/'context_decisions').glob('*.json'))},
        'independent_human_evaluation':False})
    report(out)


def report(out):
    from run_node_context_edges import report as graph_report
    from compare_node_context_pilot import compare
    graph_report(out)
    if (out/'verification_manifest.json').exists():
        compare(out,ROOT/'EvidenceNet/output/node_context_edges_v1_20261011')
        previous=Path(read(out/'manifest.json')['source_verification_experiment'])
        before=read(previous/'verification_manifest.json');after=read(out/'verification_manifest.json')
        cases=[]
        regression_source=ROOT/'EvidenceNet/output/node_context_edges_v2_20261011'
        for old in rows(regression_source/'audit/reviewed_edges.jsonl'):
            pid=old['id'].split('::')[0];decision=read(out/'context_decisions'/f'{pid}.json')
            cases.append({'pair_id':pid,'previous_assistant_review':old['assistant_review']['status'],
                          'new_status':decision['value'].get('status'), 'new_valid':decision['valid'],
                          'new_reason':decision['value'].get('reason'),
                          'policy_rejected':decision.get('policy_rejected',False)})
        jsonl(out/'verifier_regression_cases.jsonl',cases)
        write(out/'verifier_comparison.json',{'same_queue':before['queue_sha256']==after['queue_sha256'],
              'previous_statuses':before['statuses'],'current_statuses':after['statuses'],
              'previous_experiment':str(previous),'regression_reference_experiment':str(regression_source),
              'old_four_clear_errors_still_accepted':sum(c['previous_assistant_review'].startswith('REJECT') and c['new_status']=='ACCEPT' and c['new_valid'] for c in cases),
              'old_five_broad_topic_edges_still_accepted':sum(c['previous_assistant_review']=='WEAK_BROAD_TOPIC' and c['new_status']=='ACCEPT' and c['new_valid'] for c in cases),
              'old_six_plausible_edges_retained':sum(c['previous_assistant_review'].startswith('PLAUSIBLE') and c['new_status']=='ACCEPT' and c['new_valid'] for c in cases),
              'independent_evaluation':False})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['prepare','verify','report'])
    p.add_argument('--output',required=True,type=Path);p.add_argument('--source',type=Path,default=ROOT/'EvidenceNet/output/node_context_edges_v2_20261011')
    p.add_argument('--version',type=int,choices=[3,4],default=3)
    args=p.parse_args()
    if args.stage=='prepare':prepare(args.output,args.source,args.version)
    else:check(args.output);globals()[args.stage](args.output)
