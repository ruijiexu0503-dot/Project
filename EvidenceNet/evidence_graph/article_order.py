"""Validation and composition rules for paired raw-block article/reading experiments."""
from collections import Counter
import re


def sentence_block(left, right):
    """Parser direction is not reading direction; guard only local sentence evidence."""
    lt = left.strip(); rt = right.strip()
    tail = re.sub(r'(?:\s|\$|\\\]|\\\)|[”’"\'])+$', '', lt)
    if not lt or not rt:
        return 'empty_endpoint'
    if tail.endswith(('.', '!', '?', ';', ':', '。', '！', '？', '：')):
        return 'closed_sentence_or_list'
    if rt.startswith(('"', '“', '«', '「', '『')):
        return 'new_quoted_paragraph'
    return None


def validate_order(value, payload, roles):
    if not isinstance(value, dict) or not isinstance(value.get('flows'), list):
        raise ValueError('flows required')
    expected = {n['label'] for n in payload['nodes'] if roles[n['label']] in {'BODY','CAPTION','TABLE','VISUAL'}}
    seen = []
    for f in value['flows']:
        if not isinstance(f, dict) or f.get('kind') not in {'body','caption','footnote','sidebar'} or not isinstance(f.get('nodes'),list) or not f['nodes']:
            raise ValueError('nonempty typed flow required')
        ids=f['nodes']
        if any(not isinstance(n,str) or n not in expected for n in ids):
            raise ValueError('flow node outside eligible raw blocks')
        allowed = {'CAPTION'} if f['kind']=='caption' else {'BODY'}
        if any(roles[n] not in allowed for n in ids):
            raise ValueError('body/caption roles cannot be mixed; standalone visuals/tables remain unsequenced')
        seen.extend(ids)
    unsequenced=value.get('unsequenced')
    if not isinstance(unsequenced,list) or any(not isinstance(n,str) or n not in expected for n in unsequenced):
        raise ValueError('unsequenced must contain owned eligible labels')
    counts=Counter(seen+unsequenced)
    if counts != Counter(expected):
        raise ValueError('reading coverage missing='+str(sorted((Counter(expected)-counts).elements()))+
                         '; duplicate/extra='+str(sorted((counts-Counter(expected)).elements())))
    return value


def owned_flows(order, member):
    """Split at foreign/unknown blocks; never shortcut around a removed block."""
    owner={n:g['id'] for g in member['groups'] if g['kind']=='article' for n in g['nodes']}
    roles=member['roles']; result=[]; cross=[]
    for flow in order['flows']:
        run=[]; gid=None
        for n in flow['nodes']:
            current=owner.get(n) if roles[n] not in {'UNRESOLVED','PAGE_CONTEXT','STRUCTURAL'} else None
            if current != gid or current is None:
                if run: result.append(dict(kind=flow['kind'],nodes=run,article_group=gid))
                run=[]
            if current is not None: run.append(n)
            gid=current
        if run: result.append(dict(kind=flow['kind'],nodes=run,article_group=gid))
        cross.extend([a,b] for a,b in zip(flow['nodes'],flow['nodes'][1:]) if owner.get(a)!=owner.get(b))
    return result,cross


def validate_paths(pairs):
    successor={}; predecessor={}
    for a,b in pairs:
        if a==b or a in successor or b in predecessor:
            raise ValueError('continuations must have one predecessor/successor; no branch or self-loop')
        successor[a]=b; predecessor[b]=a
    for start in successor:
        seen=set(); cur=start
        while cur in successor:
            if cur in seen: raise ValueError('continuation cycle')
            seen.add(cur);cur=successor[cur]
    paths=[]
    for start in successor.keys()-predecessor.keys():
        path=[start]
        while path[-1] in successor: path.append(successor[path[-1]])
        paths.append(path)
    return sorted(paths)


def jaccard(left,right):
    left,right=set(left),set(right)
    return len(left&right)/len(left|right) if left or right else None
