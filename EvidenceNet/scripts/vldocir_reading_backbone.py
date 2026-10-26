"""Import audited current Qwen article-flow outputs on immutable hybrid nodes."""
from collections import Counter, defaultdict, deque
from pathlib import Path
from run_node_context_edges import rows, read, write, jsonl, sha


def validate_edges(nodes, edges, assignments):
    seen=set(); degrees=Counter(); adj=defaultdict(list); indegree=Counter()
    for e in edges:
        a,b=e['source'],e['target']
        if e.get('type',e.get('edge_type'))!='NEXT' or a==b or a not in nodes or b not in nodes:
            raise ValueError('invalid NEXT endpoint/type')
        if (a,b) in seen: raise ValueError('duplicate NEXT')
        seen.add((a,b))
        if nodes[a]['document']!=nodes[b]['document']:
            raise ValueError('NEXT crosses document')
        aa,bb=assignments[a].get('article_id'),assignments[b].get('article_id')
        if not aa or aa!=bb or e.get('article_id')!=aa:
            raise ValueError('NEXT crosses unresolved/article boundary')
        degrees[a]+=1;degrees[b]+=1;adj[a].append(b);indegree[b]+=1
    queue=deque(n for n in nodes if not indegree[n]); visited=0
    while queue:
        n=queue.popleft();visited+=1
        for nxt in adj[n]:
            indegree[nxt]-=1
            if not indegree[nxt]: queue.append(nxt)
    if visited!=len(nodes): raise ValueError('reading cycle')
    return {'next_edges':len(edges),'nodes_with_next':len(degrees),'nodes_without_next':sorted(set(nodes)-set(degrees)),
        'cross_page_next':sum(int(nodes[e['source']]['page'])!=int(nodes[e['target']]['page']) for e in edges)}


def build(nodes_path: Path, article_roots: list[Path], output: Path):
    nodes={n['id']:n for n in rows(nodes_path)}; edges=[]; assignments={}; sources={str(nodes_path.resolve()):sha(nodes_path)}
    for root in article_roots:
        manifest=read(root/'article_graph_manifest.json')
        if not manifest.get('ready_for_downstream') or not manifest.get('reading_ready'):
            raise ValueError('incomplete current reading stage: '+str(root))
        for name,h in manifest['files'].items():
            if sha(root/name)!=h: raise ValueError('changed article artifact '+name)
        for a in rows(root/'article_assignments.jsonl'):
            if a['node_id'] in assignments: raise ValueError('duplicate article node')
            assignments[a['node_id']]=a
        edges+=rows(root/'reading_edges.jsonl')
        for name in ('article_graph_manifest.json','article_assignments.jsonl','reading_edges.jsonl'):
            sources[str((root/name).resolve())]=sha(root/name)
    if set(assignments)!=set(nodes): raise ValueError('article/node coverage mismatch')
    result=validate_edges(nodes,edges,assignments)
    directed=[]
    for e in edges:
        common=dict(e,edge_type='NEXT',edge_layer='reading_order',evidence_propagation_allowed=False)
        directed.append(common)
        directed.append(dict(common,source=e['target'],target=e['source'],type='PREVIOUS',edge_type='PREVIOUS',inverse_of=[e['source'],e['target']]))
    jsonl(output/'reading_edges.jsonl',directed)
    result.update(nodes=len(nodes),previous_edges=len(edges),method='current_Qwen_membership_and_reading_flows',
        assignment_statuses=dict(Counter(a.get('assignment_status') for a in assignments.values())),
        limitation='Current single-document profile only emits page-local flows; no synthetic cross-page or singleton links.')
    write(output/'reading_summary.json',result)
    write(output/'reading_manifest.json',{'sources':sources,'files':{n:sha(output/n) for n in ('reading_edges.jsonl','reading_summary.json')},'code_sha256':sha(Path(__file__))})
    return result
