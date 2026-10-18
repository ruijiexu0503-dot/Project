#!/usr/bin/env python3
"""Read-only re-score existing edge experiments by actual eligible endpoint members."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT/'data/benchmarks/evidence_edges_v1_20261014'
OUTPUT = ROOT/'EvidenceNet/output/edge_modality_error_audit_20261015'
GROUPS = ['T-T','T-M','M-M','EMPTY']


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def endpoint(node, formulas):
    eligible = {(m['kind'],m['member_id']) for m in node['eligible_members'] if m['eligible']}
    members = [m for m in node['members'] if (m['kind'],m['id']) in eligible]
    if not members:
        return 'EMPTY'
    nontext = any(m['kind'] != 'atom' or m.get('type') == 'table' or m.get('role') == 'tab'
                  or '<table' in m.get('text','').lower()
                  or formulas and m.get('role') == 'equ' for m in members)
    return 'M' if nontext else 'T'


def group(case,nodes,formulas):
    kinds = [endpoint(nodes[case[k]['source_collection'],case[k]['node_id']],formulas) for k in ['A','B']]
    return 'EMPTY' if 'EMPTY' in kinds else 'M-M' if kinds==['M','M'] else 'T-T' if kinds==['T','T'] else 'T-M'


def rate(n,d):
    return n/d if d else None


def summarize(records,policy):
    result={}
    for name in GROUPS:
        selected=[r for r in records if r['groups'][policy]==name]
        count=Counter(total=len(selected))
        for r in selected:
            if not r['valid']:
                count['invalid']+=1;continue
            if r['gold'] is None:
                count['unresolved']+=1;continue
            if r['predicted'] is None:
                count['abstain']+=1;continue
            gold,pred=r['gold'],r['predicted'];count['evaluable']+=1
            count['tp' if gold and pred else 'fp' if pred else 'fn' if gold else 'tn']+=1
            if r.get('exact_correct') is not None:
                count['exact_evaluable']+=1;count['exact_errors']+=not r['exact_correct']
                count['accepted_type_direction_errors']+=bool(pred and gold and not r['exact_correct'])
        for key in ['invalid','unresolved','abstain','evaluable','tp','fp','fn','tn']:
            count.setdefault(key,0)
        result[name]=dict(count,existence_error_rate=rate(count['fp']+count['fn'],count['evaluable']),
            false_discovery_rate=rate(count['fp'],count['tp']+count['fp']),
            false_positive_rate=rate(count['fp'],count['fp']+count['tn']),
            miss_rate=rate(count['fn'],count['tp']+count['fn']))
    return result


def percentage(value):
    return '—' if value is None else f'{100*value:.1f}%'


def main(out):
    inputs=[SUITE/'nodes.jsonl',SUITE/'cases.jsonl',
        ROOT/'EvidenceNet/output/article_reading_order_comparison_v3_gpu_20261015/page_2/source_review.json']
    nodes={(n['source_collection'],n['id']):n for n in rows(inputs[0])}
    cases=rows(inputs[1]);bycase={c['suite_case_id']:c for c in cases};bytask={c['case_id']:c for c in cases}
    records=[]
    def add(scheme,case,valid,gold,pred,**extra):
        records.append(dict(scheme=scheme,case_id=case['suite_case_id'],source_group=case['group_id'],
            groups={p:group(case,nodes,f) for p,f in [('visual_table_equation',True),('visual_table',False)]},
            endpoints={k:case[k]['node_id'] for k in ['A','B']},valid=valid,gold=gold,predicted=pred,**extra))
    related=ROOT/'EvidenceNet/output/relatedness_ordinal_mixed_v1_20261015'
    inputs += [related/'evaluation/reference.jsonl',related/'predictions.jsonl',related/'summary.json']
    predictions={r['task_id']:r for r in rows(related/'predictions.jsonl')}
    for ref in rows(related/'evaluation/reference.jsonl'):
        p=predictions[ref['task_id']]
        add('related_mixed',bycase[ref['suite_case_id']],p['valid'],
            min(ref['allowed_levels'])>=2 if ref['cutoff_evaluable'] else None,
            p['result']['level']>=2 if p['valid'] else None,
            level=(p.get('result') or {}).get('level'),allowed_levels=ref['allowed_levels'],
            reason=(p.get('result') or {}).get('reason'),limitation=(p.get('result') or {}).get('limitation'))
    roots=[('four_tag_description',ROOT/'EvidenceNet/output/split_taxonomy_current_suite_qwen_descriptions_v2_20261015',None),
           ('four_tag_mixed_nontext_subset',ROOT/'EvidenceNet/output/split_taxonomy_modality_comparison_v1_20261015','mixed')]
    for scheme,root,mode in roots:
        refpath=root/'evaluation/reference.jsonl';predpath=root/('' if mode is None else mode)/'predictions.jsonl'
        inputs += [refpath,predpath]
        refs={r['task_id']:r for r in rows(refpath)}
        for p in rows(predpath):
            ref=refs[p['task_id']];allowed=ref['allowed_semantic_readings'];s=p.get('semantic') or {}
            gold=allowed[0]['relation']!='REJECT_UNCERTAIN' if ref['semantic_status']!='UNRESOLVED' else None
            pred=s.get('relation')!='REJECT_UNCERTAIN' if p['valid'] else None
            exact=any(s.get('relation')==a['relation'] and (a['relation']=='CONTRASTS_WITH' or
                (s.get('source_node_id'),s.get('target_node_id'))==(a['source_node_id'],a['target_node_id'])) for a in allowed) if p['valid'] and gold is not None else None
            add(scheme,bycase[ref['suite_case_id']],p['valid'],gold,pred,exact_correct=exact,
                predicted_semantic=s,allowed_readings=allowed,
                independent_reference_false_positive=bool(p['valid'] and not ref['references']['exists'] and p['references']['exists']))
    old=ROOT/'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/verifier/predictions.jsonl'
    inputs.append(old)
    for p in rows(old):
        case=bytask[p['task_id']];r=p['response'];status=(r.get('value') or {}).get('status')
        add('previous_concrete_protocol',case,r['valid'],case['label']=='POSITIVE' if case['label'] in ['POSITIVE','NEGATIVE'] else None,
            status=='ACCEPT' if r['valid'] and status in ['ACCEPT','REJECT'] else None,
            reason=(r.get('value') or {}).get('reason'))
    schemes=list(dict.fromkeys(r['scheme'] for r in records))
    result={p:{s:summarize([r for r in records if r['scheme']==s],p) for s in schemes}
            for p in ['visual_table_equation','visual_table']}
    # Reconcile with each frozen experiment's native reference scope, including EMPTY separately.
    expected={'related_mixed':dict(tp=29,fp=6,fn=2,tn=19),
              'four_tag_description':dict(tp=16,fp=0,fn=10,tn=25),
              'four_tag_mixed_nontext_subset':dict(tp=9,fp=0,fn=0,tn=4),
              'previous_concrete_protocol':dict(tp=12,fp=3,fn=5,tn=22)}
    for scheme,counts in expected.items():
        actual={key:sum(g[key] for g in result['visual_table_equation'][scheme].values()) for key in counts}
        if actual!=counts:
            raise ValueError(f'Native score reconciliation failed: {scheme}: {actual}')
    out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'cases.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    manifest=dict(files={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs+[Path(__file__)]},
        primary_policy='visual_table_equation',
        definition='T: eligible ordinary textual members only; M: at least one original visual, table or standalone equ-role formula; generated descriptions do not change source modality; empty evidence separate.',
        alternative_policy='visual_table preserves earlier image/table-only modality-comparison convention; LaTeX formulas remain text there.',
        labels='Assistant source-reviewed development references, not independent gold. Different protocols retain native relation definitions. No unlabeled natural pairs scored.',
        denominators='Existence error=(FP+FN)/resolved valid decisions; false-discovery rate=FP/(TP+FP); false-positive rate=FP/(FP+TN); miss rate=FN/(TP+FN).')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    primary=result['visual_table_equation']
    text=['# Edge errors by actual endpoint modality','',
        '2026-10-15. Re-analysis of existing predictions only; no new inference or graph changes.',
        '', 'T = ordinary text; M = node containing an original image, table or standalone formula. '
        'Only eligible members count. Describing an image as text does not make its source a T node. '
        'Empty evidence is reported separately. The alternative image/table-only convention is included in summary.json.',
        '', '## Latest RELATED mixed-input protocol', '',
        '103 predictions exist, but only the frozen 58-case suite has reference readings. '
        '56 have resolved cutoff labels; two uncertain cases are excluded from existence scores. '
        'One of the 56 is deliberately empty evidence and is not included in the three substantive groups.', '',
        '| Pair | Resolved cases | Positive / negative | Wrong existence decisions | False edges / accepted edges | Missed / positives |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name in GROUPS[:3]:
        c=primary['related_mixed'][name]
        text.append(f"| {name} | {c['evaluable']} | {c['tp']+c['fn']} / {c['fp']+c['tn']} | {c['fp']+c['fn']}/{c['evaluable']} ({percentage(c['existence_error_rate'])}) | {c['fp']}/{c['tp']+c['fp']} ({percentage(c['false_discovery_rate'])}) | {c['fn']}/{c['tp']+c['fn']} |")
    text += ['', 'Observed highest RELATED existence/false-edge error is M–M. '
        'This is not a universal modality ranking: its five resolved cases contain four negatives and one positive, '
        'while T–M contains ten positives and no resolved negative. The M–M errors reuse the EuroSAT sample-image '
        'node and a small group of remote-sensing cases, so they are not independent document samples.', '',
        'If standalone equations remain T, RELATED counts become T–T: 5/42 errors, 3/23 accepted edges false; '
        'T–M: 0/8 errors, no negatives; M–M unchanged at 3/5 errors and 3/4 accepted edges false. '
        'The main observed risk does not depend on the formula convention.', '',
        '## Error cases in latest RELATED run','',
        '| Case | Pair | Error | Evidence in model reason |','| --- | --- | --- | --- |']
    for r in records:
        if r['scheme']=='related_mixed' and r['gold'] is not None and r['gold']!=r['predicted']:
            why=r['reason'].replace('|','/')
            text.append(f"| {r['case_id']} | {r['groups']['visual_table_equation']} | {'FP' if r['predicted'] else 'FN'} | {why} |")
    text += ['', 'The three M–M false edges are N04 (segmentation results vs EuroSAT sample images), '
        'N21 (different remote-sensing dataset imagery vs EuroSAT samples), and N22 (FUSU-Net architecture '
        'vs EuroSAT samples). In all three, shared domain or object categories are promoted from '
        'level 1 navigation/theme to level 2 evidence connection. The three T–T false positives '
        '(N07/N08/N20) have the same broad dataset/sensor-family failure. Thus the observed problem '
        'also concerns relation definition/thresholding and is not isolated to visual encoding.', '',
        '## Other protocols must remain separate', '',
        '| Protocol | Pair | Wrong existence / evaluable | False / accepted | Exact type+direction errors |',
        '| --- | --- | ---: | ---: | ---: |']
    for scheme in schemes[1:]:
        for name in GROUPS[:3]:
            c=primary[scheme][name]
            if not c['total']:continue
            exact=f"{c.get('exact_errors',0)}/{c['exact_evaluable']}" if c.get('exact_evaluable') else 'not scored'
            text.append(f"| {scheme} | {name} | {c['fp']+c['fn']}/{c['evaluable']} | {c['fp']}/{c['tp']+c['fp']} | {exact} |")
    text += ['', 'The four-function description verifier rejected all resolved M–M negatives but also missed '
        'its sole M–M positive. Its mixed-image/table subset recovered that positive with no semantic FP '
        'on the five resolved M–M cases. That subset has no T–T controls under the same prompt/backend, '
        'so it cannot establish a three-way mixed-modality ranking. Type/direction error and explicit-reference '
        'error are different from whether an edge should exist; exact readings remain provisional.', '',
        '## Latest CLAD experiment is a separate text–image diagnostic', '',
        'GPU 80131 contains text–image source-pair verification only, with 11 unique candidates, 10 valid '
        'outputs and four accepted proposals. After the user clarified that same-specific-subject '
        'navigation is a valid edge, source review retains three scoped ILLUSTRATES edges and one '
        'symmetric RELATED edge (A006/V001). The previous claim of 1/4 false edges (25%) is withdrawn: '
        'the image and paragraph concern the same stadium, although the image does not show the entire '
        'sports-city masterplan. This is a review-policy clarification, not a new inference improvement '
        'or a measured population error rate of zero. Original narrow illustration references and '
        'model outputs remain unchanged, with the earlier review archived. One additional '
        'pair is format-pending due to line-wrap dehyphenation, not a semantic negative. The four node '
        'conditions share these decisions; do not count them four times. No T–T or M–M controls exist '
        'in this CLAD run, so it cannot rank the three pair types.', '',
        '## Practical interpretation', '',
        'Prioritize M–M hard-negative review for generic visual similarity and one-endpoint content leaking '
        'into the other. T–M needs additional genuine hard negatives before its measured zero error can '
        'be interpreted. For T–T, inspect missed concrete links and relation type/direction separately. '
        'A balanced follow-up should include positive and difficult negative examples in all three strata, '
        'cover multiple independent documents/assets, and keep relation policy fixed.', '',
        'Raw per-case classifications, modality conventions and frozen input hashes are retained alongside '
        'this report. All scores use their original frozen protocol-specific readings; the user-clarified '
        'broader navigation policy has not been re-annotated across all 58 cases. These are '
        'assistant-reviewed development diagnostics, not corpus-wide or final-user-policy error rates.']
    (out/'REPORT.md').write_text('\n'.join(text)+'\n')
    print(json.dumps(dict(output=str(out),primary=primary['related_mixed']),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=OUTPUT)
    main(p.parse_args().output)
