#!/usr/bin/env python3
"""Record scoped source-review notes and export separately reviewed CLAD link additions."""
from collections import Counter
import json

from run_text_multimodal_diagnostic_v2 import DATA,OUT,CLAD
from run_node_context_edges import read,rows,write,jsonl,sha

NOTES={
 'REL_1220f5375a531bb3':('SENSOR_IS_NOT_DATASET','拒绝这条连接有依据，但 Sentinel 是影像任务／来源，不能把它作为与 EuroSAT 对立的数据集名称。应说正文解释另一项具体方法，图中是 EuroSAT 样例，未给出相应机制。'),
 'REL_33f10751f4aaec67':('CROSS_ENDPOINT_THEME','两端是不同体育场，拒绝合理；但只有正文端讨论体育城总体规划，不应说两端都讨论该规划。'),
 'REL_35ebf2b7a2a42863':('UNVERIFIED_VENUE_NAME','以图中 FC Barcelona 标识和正文 Al-Ahly/Cairo 区分即可。不要把未在输入中明确标出的 Camp Nou 名称作为已经验证的来源事实。'),
 'REL_7084b02aa7d9350f':('UNVERIFIED_VENUE_NAME','图中是 FC Barcelona 标识的球场，正文为 Stade Hassan II；无需额外断言场馆一定叫 Camp Nou。'),
 'REL_4e983ccfac7b28cf':('WRONG_ENTITY_TYPE','moussen 是文中的传统聚会／设计灵感词，不是体育场项目名。相关项目身份由 Stade Hassan II/Casablanca 标题上下文解析。'),
 'REL_7571abc9f1d1a2c9':('CONTEXT_WORDING','图文均明确标识 EuroSAT，连接有效。限制应说原文城市列表未完整，不应暗示另外提供了未出现的城市上下文。'),
 'REL_a43c1ff2abcf36bf':('CROSS_ENDPOINT_RESOLUTION','EuroSAT 身份、27000 张、10 类对应成立。10 m 只由表格端给出，不能因为正文提到 Sentinel-2 就说正文也给出／暗示相同分辨率；64×64 是像素尺寸。'),
 'REL_b7591ba8ef1d6a4c':('RENDERING_NOT_COMPLETED_STATE','同一 Stade Hassan II 主体和帐篷形屋顶关联成立，但图是建筑效果图，不能称为 completed state 或据此确认建成状态。'),
 'REL_cfa744c6410304b5':('CULTURAL_SCOPE','同一体育场身份足以建立关联。将文化设计陈述和可见屋顶形态分别记录，不以外部文化归属推断替代两个端点的实际内容。'),
 'REL_d3a573fa3f4a525f':('DENYING_PRESENT_FIGURE_DESCRIPTION','拒绝 FUSU 采集说明与 EuroSAT 样例的连接有依据；但 FUSU 正文确实解释 Fig.2 的中心覆盖与对齐关系，不能说它只提及而没有描述该图。'),
 'REL_ecfbbb1c0b6b734f':('MECHANISM_SCOPE','Q/K/V 线性映射、Dot Product 和依赖聚合有具体对应，可保留。原图未明确展示缩放因子，不将图示对应扩大为所有缩放细节或完整实现完全一致。'),
}


def main():
    cases=rows(DATA/'cases.jsonl');preds={p['task_id']:p for p in rows(OUT/'predictions.jsonl')}
    if len(preds)!=len(cases):raise ValueError('Wait for all diagnostic predictions')
    scope={r['case_id']:r for r in read(DATA/'reference_scope_review.json')}
    review=[];counts=Counter();native=read(OUT/'summary.json')
    for c in cases:
        p=preds[c['case_id']];gold=scope.get(c['case_id'],{}).get('reviewed_label',c['label'])
        result=p.get('result') or {};status=result.get('status')
        note=NOTES.get(c['case_id'])
        if gold=='UNCERTAIN':verdict='SCOPE_UNCERTAIN';counts['scope_ambiguous']+=1
        elif not p['valid']:verdict='INVALID';counts['invalid']+=1
        elif status=='UNCERTAIN':verdict='MODEL_UNCERTAIN';counts['model_uncertain']+=1
        else:
            key='tp' if gold=='LINK' and status=='LINK' else 'fp' if status=='LINK' else 'fn' if gold=='LINK' else 'tn'
            counts[key]+=1;verdict='KEEP_LINK' if key=='tp' else 'KEEP_NO_LINK' if key=='tn' else 'NEEDS_REVIEW'
        if note:counts['prose_scope_repairs']+=1
        review.append(dict(case_id=c['case_id'],reviewed_label=gold,edge_verdict=verdict,
            prose_flag=note[0] if note else None,
            reason=note[1] if note else scope[c['case_id']]['reason'] if c['case_id'] in scope else
                '连接判定与原始节点／图像身份或具体内容对应一致；保留模型所列范围限制。',
            reviewer='assistant_source_review_not_independent_gold',original_reference_preserved=True))
    write(OUT/'source_review.json',review)
    write(OUT/'reviewed_summary.json',dict(counts=dict(counts),native_summary=native,
        excluded_scope_case_ids=list(scope),label_policy='Original frozen labels preserved; one pre-prediction scope review excluded from primary binary scoring',
        limitations='Small reused development assets; many easy identity swaps; no generalization or retrieval-quality claim. Prose issues separate from link existence.'))
    bypair={frozenset([c['text_node_id'],c['multimodal_node_id']]):c for c in cases}
    additions={}
    for condition in ['article_first_0','article_first_1','reading_first_0','reading_first_1']:
        nodes=rows(CLAD/condition/'evidence_nodes.jsonl');existing=rows(CLAD/condition/'reviewed_visual_semantic_edges.jsonl')
        linked={frozenset([e['source'],e['target']]) for e in existing};extra=[]
        for text in nodes:
            if text['source_visual_bundle_ids']:continue
            visual=next(n for n in nodes if n['source_visual_bundle_ids'] and n['article_id']==text['article_id'])
            key=frozenset([text['node_id'],visual['node_id']]);case=bypair.get(key)
            if key in linked or not case:continue
            pred=preds[case['case_id']]
            if not pred['valid'] or pred['result']['status']!='LINK' or case['label']!='LINK':continue
            result=pred['result'];anchors=[a for side in result['anchors'].values() for a in side]
            own=[a for a in anchors if a['node_id']==text['node_id']]
            source_id=text['source_atom_ids'][0];vid=visual['source_visual_bundle_ids'][0]
            support='同一具体体育场的主体关联；可用于检索和导航，不意味着图片证明了正文的容量、建成状态、人物身份、文化起源或未来用途。'
            extra.append(dict(source=visual['node_id'],target=text['node_id'],type='RELATED',direction='SYMMETRIC',
                article_id=text['article_id'],verification='ASSISTANT_REVIEWED_WITH_EXPLICIT_SCOPE',
                representation='full_evidence_node_original_crop_description_and_separate_identity_context',
                diagnostic_case_id=case['case_id'],diagnostic_job_id='80263',
                grounding=[dict(text_source_id=source_id,visual_source_id=vid,text_anchor='\n'.join(a.get('quote','') for a in own),
                    visual_anchor='同一体育场身份，由原始图像／图内标签及单独的来源标题解析。',reason=result['reason'],
                    source_review=dict(status='KEEP_AS_RELATED',reviewed_relation='RELATED',supported_correspondence=support))],
                source_anchors=result['anchors'],identity_context=result['identity_context']))
        jsonl(OUT/'clad_link_completion'/(condition+'.jsonl'),extra)
        additions[condition]=dict(existing=len(existing),new_same_subject_links=len(extra),total=len(existing)+len(extra))
    write(OUT/'clad_link_completion/summary.json',dict(conditions=additions,existing_source_files_unchanged=True,
        node_source=str(CLAD),reviewed_predictions_sha256=sha(OUT/'predictions.jsonl')))
    print(json.dumps(dict(reviewed_counts=dict(counts),link_additions=additions),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
