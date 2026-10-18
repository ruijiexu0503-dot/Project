"""Content coreference and overlapping-caption checks for verifier v4."""
import re
from verify_node_context_v3 import validate_v3


def normalized(text):
    return re.sub(r'\s+',' ',text).strip().casefold()


def validate_v4(value,pair,nodes,policies):
    errors=validate_v3(value,pair,nodes,policies)
    if errors or value.get('status')!='ACCEPT' or value['relation_basis']!='SAME_NAMED_ENTITY':return errors
    entity=value.get('shared_entity','')
    if not isinstance(entity,str) or len(entity.strip())<3:return ['shared_entity_missing']
    if value.get('entity_type') not in {'EVENT','PROJECT','PERSON','OBJECT','ORGANIZATION'}:return ['entity_type_invalid']
    if normalized(entity) in {'object detection','object localization','image classification','object classification',
                              'semantic segmentation','computer vision','machine learning','research','science'}:
        return ['generic_topic_is_not_entity']
    for label in ['a','b']:
        anchor=value['anchor_'+label]
        text=anchor.get('quote','') if anchor['kind']=='TEXT' else anchor['observation']
        # Names must be in the selected original anchor, not another node/member.
        if not re.search(r'(?<!\w)'+re.escape(normalized(entity))+r'(?!\w)',normalized(text)):
            return ['shared_entity_not_in_both_anchors']
        fact=value.get('entity_fact_'+label)
        if not isinstance(fact,str) or len(fact.strip())<12 or normalized(fact)==normalized(entity):
            return ['entity_fact_missing']
    return []


def duplicate_caption(a,b,policies):
    """Only overlapping caption extractions on the same page; not real panels."""
    if (a['document'],a['page'])!=(b['document'],b['page']):return False
    def members(node):
        allowed={m['member_id'] for m in policies[node['id']]['members'] if m['eligible'] and m['kind']=='atom'}
        return [m for m in node['members'] if m['kind']=='atom' and m['id'] in allowed and
                re.match(r'^\s*(?:fig(?:ure)?\.?|table)\s*(?:\d+|[IVX]+)\b',m['text'],re.I)]
    def signature(m):
        words=re.findall(r'\w+',normalized(m['text']))[:14]
        return {w.rstrip('s') for w in words}
    def overlap(x,y):
        intersection=max(0,min(x[2],y[2])-max(x[0],y[0]))*max(0,min(x[3],y[3])-max(x[1],y[1]))
        area=min(max(0,x[2]-x[0])*max(0,x[3]-x[1]),max(0,y[2]-y[0])*max(0,y[3]-y[1]))
        return intersection/max(area,1)
    for x in members(a):
        for y in members(b):
            sx,sy=signature(x),signature(y)
            lx=re.match(r'^\s*(fig(?:ure)?\.?|table)\s*(\d+|[IVX]+)\b',x['text'],re.I)
            ly=re.match(r'^\s*(fig(?:ure)?\.?|table)\s*(\d+|[IVX]+)\b',y['text'],re.I)
            if lx[2].upper()!=ly[2].upper() or lx[1].lower().startswith('table')!=ly[1].lower().startswith('table'):continue
            if len(sx&sy)/max(min(len(sx),len(sy)),1)<0.7:continue
            if any(overlap(bx,by)>=0.4 for bx in x.get('boxes',[]) for by in y.get('boxes',[])):return True
    return False


CORE_RULE=('SAME_NAMED_ENTITY is content coreference: both endpoints refer to ONE identical concrete event, '
           'project, person, object or organization and each gives a substantive fact about it. '
           'The facts MAY be complementary, concern different aspects, use different measurements or units, '
           'or describe a project outcome versus its participants. Do NOT require identical claims, numerical '
           'agreement, a causal explanation, a direct comparison, or two distinct entities for this basis. '
           'A specific event described as a compact-binary observation in one paragraph and characterized '
           'through parameter inference in another is a valid connection. A named project demonstration '
           'and its leadership/partners also correspond. Bare name lists, logos, generic task names, and '
           'unresolved identity remain invalid. ACCEPT with this basis additionally requires shared_entity '
           '(one identical name/acronym literally present in BOTH selected anchors), entity_type '
           '(EVENT|PROJECT|PERSON|OBJECT|ORGANIZATION), entity_fact_a and entity_fact_b '
           '(one substantive fact sentence grounded in each selected original span/crop). '
           'Mathematical formula variants should use FORMULA_SPECIALIZATION rather than SAME_NAMED_ENTITY '
           'when no literal shared proper entity name is present. '
           'These are symmetric contextual links, not agreement or entailment. ')


CRITIC_RULE=('For SAME_NAMED_ENTITY, confirm when the same concrete entity is anchored at both endpoints '
             'and each has a substantive fact. Complementary event descriptions, parameters, outcomes '
             'and project organization are sufficient. Do not reject because the statements differ or '
             'because there is no comparison, equal measurement, causal explanation or distinct entity pair. '
             'Reject only unresolved identity, bare names without facts, generic topics, duplicate '
             'extractions, furniture or facts not supported by the selected sources. ')
