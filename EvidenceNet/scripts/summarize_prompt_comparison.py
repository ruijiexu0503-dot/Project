#!/usr/bin/env python3
"""Summarize matched outputs; require explicit source review before a pass decision."""
import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path


def read(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(root):
    manifest=read(root/'manifest.json');criteria=read(root/'decision_criteria.json')
    signature=digest(root/'manifest.json')
    if criteria['manifest_sha256']!=signature:raise ValueError('criteria/input mismatch')
    summaries={arm:read(root/arm/'summary.json') for arm in manifest['arms']}
    for arm,data in summaries.items():
        if data['processed']!=len(manifest['cases']) or data['manifest_sha256']!=signature:
            raise ValueError(f'incomplete/mismatched arm: {arm}')
        if [c['case_id'] for c in data['cases']]!=[c['case_id'] for c in manifest['cases']]:
            raise ValueError('case order/coverage mismatch')
    fingerprints={(json.dumps(c['inference_config'],sort_keys=True),c['validator_sha256'],c['grounding_code_sha256'])
                  for data in summaries.values() for c in data['cases']}
    if len(fingerprints)!=1:raise ValueError('model or validation code differs across arms')
    reviews=read(root/'source_review.json') if (root/'source_review.json').exists() else None
    counts={arm:Counter() for arm in summaries};supported={arm:set() for arm in summaries}
    rows=[];cards=[];all_keys=set()
    if reviews:
        if reviews['summary_hashes']!={arm:digest(root/arm/'summary.json') for arm in summaries}:
            raise ValueError('review labels are bound to different outputs')
    labels={(x['arm'],x['case_id'],x['edge_index']):x for x in reviews['edges']} if reviews else {}
    if reviews and len(labels)!=len(reviews['edges']):raise ValueError('duplicate review label')
    for i,case in enumerate(manifest['cases']):
        columns=[]
        for arm,data in summaries.items():
            result=data['cases'][i];counts[arm]['invalid_responses']+=result['status']!='complete'
            counts[arm]['source_address_rejections']+=sum(
                any(marker in rejection.get('error','') for marker in
                    ('unknown span_id','span registry does not match','span_id must be'))
                for rejection in result.get('rejected',[]))
            proposed=result.get('proposed')
            proposals=proposed.get('edges') if isinstance(proposed,dict) else None
            counts[arm]['proposed']+=len(proposals) if isinstance(proposals,list) else 0
            counts[arm]['accepted']+=len(result['accepted']);entries=[]
            for n,edge in enumerate(result['accepted']):
                key=(arm,case['case_id'],n);all_keys.add(key)
                label=labels.get(key,{});decision=label.get('decision','UNREVIEWED')
                if decision not in {'SUPPORTED','UNSUPPORTED','UNCERTAIN','UNREVIEWED'}:raise ValueError('unknown decision')
                counts[arm][decision]+=1
                if decision=='SUPPORTED':supported[arm].add(case['case_id'])
                rows.append({'arm':arm,'case_id':case['case_id'],'edge_index':n,'edge':edge,
                             'decision':decision,'review_basis':label.get('basis')})
                entries.append('<li><b>'+html.escape(decision+' '+edge['relation'])+'</b><p>'+
                    html.escape(edge['anchor'])+'</p><p>'+html.escape(edge['basis'])+'</p><p>'+
                    html.escape(label.get('basis','Not source-reviewed yet'))+'</p></li>')
            columns.append('<td><h3>'+html.escape(arm)+'</h3><ul>'+''.join(entries)+'</ul></td>')
        images=''.join('<a href="'+html.escape(os.path.relpath(p,root),quote=True)+'"><img alt="'+name+'" src="'+
                       html.escape(os.path.relpath(p,root),quote=True)+'"></a>' for p,name in zip(case['images'],['Full page','Target crop']))
        cards.append('<section><h2>'+html.escape(case['case_id']+' '+case['document_id']+'/'+case['page']+' '+case['visual_id'])+
                     '</h2><p>Group: '+html.escape(case['group'])+'</p>'+images+'<table><tr>'+''.join(columns)+'</tr></table></section>')
    if set(labels)-all_keys:raise ValueError('review refers to nonexistent output edges')
    old,new=counts['legacy-v2'],counts['grounded-v3']
    controls=set(criteria['positive_control_cases'])
    complete_review=reviews is not None and set(labels)==all_keys and not any(c['UNREVIEWED'] for c in counts.values())
    checks={'complete_source_review':complete_review,
            'no_invalid_responses':all(c['invalid_responses']==0 for c in counts.values()),
            'no_new_source_address_rejections':new['source_address_rejections']<=old['source_address_rejections'],
            'all_positive_controls_preserved':controls<=supported['grounded-v3'],
            'no_new_serious_error':reviews is not None and reviews.get('new_serious_errors')==[]}
    if 'At least 50%' in criteria['semantic_gate']:
        checks['unsupported_accepted_reduced_at_least_half']=(
            old['UNSUPPORTED']>0 and new['UNSUPPORTED']<=old['UNSUPPORTED']/2)
    elif 'No increase' in criteria['semantic_gate']:
        checks['no_increase_in_unsupported_edges']=(
            new['UNSUPPORTED']<=old['UNSUPPORTED'])
        checks['no_loss_of_supported_edges']=(
            new['SUPPORTED']>=old['SUPPORTED'])
    else:
        raise ValueError('unknown source-review semantic gate')
    output={'manifest_sha256':signature,'status':'PASS' if all(checks.values()) else 'NOT_PASSED',
            'checks':checks,'counts':{a:dict(c) for a,c in counts.items()},
            'positive_controls_preserved':{a:len(controls&s) for a,s in supported.items()},
            'reviewer':reviews.get('reviewer') if reviews else None,'independent_human_gt':False,
            'scope':criteria['scope'],'edges':rows}
    (root/'evaluation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (root/'comparison.html').write_text('<!doctype html><meta charset="utf-8"><title>Frozen prompt comparison</title>'
        '<style>body{font:15px system-ui;max-width:1400px;margin:auto}td{width:50%;vertical-align:top;padding:16px}section{border-bottom:2px solid #ccc}p{white-space:pre-wrap;overflow-wrap:anywhere}img{max-height:400px;max-width:48%;vertical-align:top;margin:1%}</style>'
        '<h1>Frozen prompt comparison</h1><p>Assistant source review; not independent human GT. '+html.escape(output['status'])+'</p>'+''.join(cards))
    print(json.dumps({k:v for k,v in output.items() if k!='edges'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    summarize(p.parse_args().root)
