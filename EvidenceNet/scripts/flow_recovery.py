"""Bounded source-assignment repair. Never invent or quarantine assignments."""
import copy
import json
from collections import defaultdict

POLICY_VERSION = 'bounded-v1'
PATCH_POLICY_VERSION = 'bounded-v2'
POLICIES = {POLICY_VERSION, PATCH_POLICY_VERSION}
ROLES = {'title', 'section_heading', 'dek', 'byline', 'page_furniture', 'logo'}


def duplicate_options(flow, rep):
    known = {f['fragment_id'] for a in rep['atoms'] for f in a['text_fragments']}
    known |= {v['visual_bundle_id'] for v in rep['visual_bundles']}
    found = defaultdict(list)
    for i, item in enumerate(flow['content_items']):
        for j, stream in enumerate(item['flows']):
            for k, fid in enumerate(stream['fragment_ids']):
                found[fid].append({'path': [i, 'flows', j, k], 'item': item['content_item_id'],
                                   'flow': stream['flow_id'], 'kind': stream['flow_kind']})
        for k, entry in enumerate(item['structural_fragments']):
            found[entry['fragment_id']].append({'path': [i, 'structural_fragments', k],
                'item': item['content_item_id'], 'role': entry['role']})
        for k, vid in enumerate(item['visual_panel_ids']):
            found[vid].append({'path': [i, 'visual_panel_ids', k], 'item': item['content_item_id']})
    return {fid: rows for fid, rows in found.items() if fid in known and len(rows) > 1}


def repair_prompt(flow, rep, options):
    texts = {f['fragment_id']: f['text'] for a in rep['atoms'] for f in a['text_fragments']}
    visuals = {v['visual_bundle_id']: v.get('geometry_members', []) for v in rep['visual_bundles']}
    choices = [{'id': fid, 'source_text': texts.get(fid), 'visual_geometry': visuals.get(fid),
                'options': [{'choice': n, **row} for n, row in enumerate(rows, 1)]}
               for fid, rows in options.items()]
    return ('Choose one existing occurrence for each duplicated source ID using the source page. '
            'Do not add IDs or change source text. Return exactly {"choices": {"<supplied ID>": '
            '<integer choice or "UNRESOLVED">}}. Include every listed ID. '
            'Use UNRESOLVED when the supplied occurrences do not support a reliable decision. '
            'Reading order and roles are provisional; do not assume any option is correct by position.\n'
            'OPTIONS: ' + json.dumps(choices, ensure_ascii=False) + '\n'
            'ORIGINAL FLOW: ' + json.dumps(flow, ensure_ascii=False))


def apply_choices(flow, options, answer):
    if not isinstance(answer, dict):
        raise ValueError('repair response must be an object')
    if set(answer) == {'choices'}:
        choices = answer['choices']
        form = 'wrapped'
    else:
        choices, form = answer, 'exact_flat_map'
    if not isinstance(choices, dict) or set(choices) != set(options):
        raise ValueError('repair choices must cover exactly the conflicting source IDs')
    paths = {}
    for fid, choice in choices.items():
        if choice == 'UNRESOLVED':
            raise ValueError(f'unresolved duplicate assignment: {fid}')
        if type(choice) is not int or not 1 <= choice <= len(options[fid]):
            raise ValueError(f'invalid repair choice: {fid}')
        paths[fid] = options[fid][choice - 1]['path']
    corrected = copy.deepcopy(flow)
    removed_continuations = []
    for i, item in enumerate(corrected['content_items']):
        for j, stream in enumerate(item['flows']):
            ids = [fid for k, fid in enumerate(stream['fragment_ids'])
                   if fid not in paths or paths[fid] == [i, 'flows', j, k]]
            stream['fragment_ids'] = ids
            adjacency = set(zip(ids, ids[1:]))
            kept = []
            for edge in stream['continuations']:
                if (edge['from_fragment_id'], edge['to_fragment_id']) in adjacency:
                    kept.append(edge)
                else:
                    removed_continuations.append({'flow_id': stream['flow_id'], 'edge': edge})
            stream['continuations'] = kept
        item['structural_fragments'] = [r for k, r in enumerate(item['structural_fragments'])
            if r['fragment_id'] not in paths or paths[r['fragment_id']] == [i, 'structural_fragments', k]]
        item['visual_panel_ids'] = [v for k, v in enumerate(item['visual_panel_ids'])
            if v not in paths or paths[v] == [i, 'visual_panel_ids', k]]
    return corrected, {'schema_form': form, 'choices': choices,
                       'removed_continuations': removed_continuations}


def prepare_patch(flow, rep):
    """Remove invalid claims only, then enumerate source assignments needing review.

    Known content is never discarded: invalid roles become explicit missing-ID
    tasks. Valid assignments and source text are immutable in this patch protocol.
    """
    fixed = copy.deepcopy(flow)
    fragments = {f['fragment_id']: f for a in rep['atoms'] for f in a['text_fragments']}
    visuals = {v['visual_bundle_id']: v for v in rep['visual_bundles']}
    removed = []
    for item in fixed['content_items']:
        for stream in item['flows']:
            kept = []
            for fid in stream['fragment_ids']:
                if fid in fragments: kept.append(fid)
                else: removed.append({'kind':'unknown_or_wrong_type_fragment_id','id':fid,'flow_id':stream['flow_id']})
            stream['fragment_ids'] = kept
        kept = []
        for entry in item['structural_fragments']:
            if entry['fragment_id'] in fragments and entry['role'] in ROLES: kept.append(entry)
            else: removed.append({'kind':'invalid_structural_assignment','entry':entry,'content_item_id':item['content_item_id']})
        item['structural_fragments'] = kept
        kept = []
        for vid in item['visual_panel_ids']:
            if vid in visuals: kept.append(vid)
            else: removed.append({'kind':'unknown_or_wrong_type_visual_id','id':vid,'content_item_id':item['content_item_id']})
        item['visual_panel_ids'] = kept
    removed += prune_continuations(fixed)
    seen_f = {fid for item in fixed['content_items'] for stream in item['flows'] for fid in stream['fragment_ids']}
    seen_f |= {r['fragment_id'] for item in fixed['content_items'] for r in item['structural_fragments']}
    seen_v = {vid for item in fixed['content_items'] for vid in item['visual_panel_ids']}
    missing = {fid:'fragment' for fid in sorted(fragments.keys()-seen_f)}
    missing.update({vid:'visual' for vid in sorted(visuals.keys()-seen_v)})
    return fixed, {'removed_invalid_claims':removed, 'missing':missing,
                   'duplicate_options':duplicate_options(fixed, rep)}


def prune_continuations(flow):
    removed = []
    for item in flow['content_items']:
        for stream in item['flows']:
            adjacent = set(zip(stream['fragment_ids'], stream['fragment_ids'][1:]))
            kept=[]
            for edge in stream['continuations']:
                a,b=edge['from_fragment_id'],edge['to_fragment_id']
                if a!=b and (a,b) in adjacent and edge['kind'] in {'same_sentence','same_paragraph'}:
                    kept.append(edge)
                else:removed.append({'kind':'invalid_continuation','flow_id':stream['flow_id'],'edge':edge})
            stream['continuations']=kept
    return removed


def patch_prompt(flow, rep, plan):
    return ('''Repair only the listed missing or duplicated assignments using the source page.
Correct source inventory is authoritative. Do not rewrite existing valid assignments, text, or reading order.
Return {"duplicate_choices": {"<duplicated ID>": <integer option or "UNRESOLVED">},
"placements": [{"source_id":"<missing ID>","content_item_id":"<existing item ID>",
"destination":"flow|new_flow|structural|visual|UNRESOLVED","basis":"<page-grounded reason>",
... destination-specific fields ...}]}.
Each missing ID must occur exactly once in placements, in insertion/reading order.
Use destination flow with flow_id and after_fragment_id (null for beginning), both within the selected existing item.
Use new_flow with flow_kind main/sidebar/caption; the program creates/reuses one new flow of that kind in that item.
Use structural with role title/section_heading/dek/byline/page_furniture/logo only when genuinely structural.
Tables, equations, captions and ordinary prose are content: use a suitable existing flow or new_flow, NEVER furniture.
Use visual for visual IDs; visual IDs never belong in fragment lists. No other fields are permitted.
For flow insertion, after_fragment_id may refer to an earlier placement in this answer.
Use UNRESOLVED with source_id and basis when ownership is uncertain; do not force a choice to pass validation.
Do not generate continuation edges; existing invalid ones are recorded separately for review.
Duplicate options are numbered from 1 in their listed order. Include exactly the supplied duplicate IDs.
SOURCE INVENTORY: ''' + json.dumps({'atoms':rep['atoms'],'visuals':rep['visual_bundles']},ensure_ascii=False)
            + '\nCURRENT FLOW: ' + json.dumps(flow,ensure_ascii=False)
            + '\nPATCH TASKS: ' + json.dumps(plan,ensure_ascii=False))


def apply_patch_choices(flow, plan, answer):
    if not isinstance(answer,dict) or set(answer)!={'duplicate_choices','placements'}:
        raise ValueError('patch requires exactly duplicate_choices and placements')
    if not isinstance(answer['placements'],list):raise ValueError('placements must be a list')
    fixed, audit = apply_choices(flow, plan['duplicate_options'], {'choices':answer['duplicate_choices']})
    placements=answer['placements']
    if any(not isinstance(p,dict) for p in placements):raise ValueError('placement must be an object')
    ids=[p.get('source_id') for p in placements]
    if len(ids)!=len(set(ids)) or set(ids)!=set(plan['missing']):
        raise ValueError('placements must cover exactly the missing source IDs')
    items={item['content_item_id']:item for item in fixed['content_items']}
    new_flows={};used_ids={s['flow_id'] for item in fixed['content_items'] for s in item['flows']}
    for p in placements:
        fid=p['source_id'];kind=p.get('destination')
        if kind=='UNRESOLVED':raise ValueError(f'unresolved source assignment: {fid}')
        common={'source_id','content_item_id','destination','basis'}
        extra={'flow':{'flow_id','after_fragment_id'},'new_flow':{'flow_kind'},'structural':{'role'},'visual':set()}
        if kind not in extra or set(p)!=common|extra[kind]:raise ValueError('invalid destination schema')
        if not isinstance(p['basis'],str) or not p['basis'].strip():raise ValueError('page-grounded basis required')
        if p['content_item_id'] not in items:raise ValueError('unknown content item; no new ownership is invented')
        item=items[p['content_item_id']]
        if (plan['missing'][fid]=='visual') != (kind=='visual'):raise ValueError('source ID type mismatch')
        if kind=='visual':item['visual_panel_ids'].append(fid)
        elif kind=='structural':
            if p['role'] not in ROLES:raise ValueError('invalid structural role')
            item['structural_fragments'].append({'fragment_id':fid,'role':p['role']})
        elif kind=='new_flow':
            if p['flow_kind'] not in {'main','sidebar','caption'}:raise ValueError('invalid new flow kind')
            key=(p['content_item_id'],p['flow_kind'])
            if key not in new_flows:
                n=1
                while f'REPAIR_FLOW_{n}' in used_ids:n+=1
                stream={'flow_id':f'REPAIR_FLOW_{n}','flow_kind':p['flow_kind'],'fragment_ids':[],'continuations':[]}
                used_ids.add(stream['flow_id']);item['flows'].append(stream);new_flows[key]=stream
            new_flows[key]['fragment_ids'].append(fid)
        else:
            streams=[s for s in item['flows'] if s['flow_id']==p['flow_id']]
            if len(streams)!=1:raise ValueError('flow must belong to selected item')
            ids=streams[0]['fragment_ids'];after=p['after_fragment_id']
            if after is not None and after not in ids:raise ValueError('insertion anchor not in selected flow')
            ids.insert(0 if after is None else ids.index(after)+1,fid)
    audit.update(placements=placements,removed_after_insertion=prune_continuations(fixed))
    return fixed,audit
