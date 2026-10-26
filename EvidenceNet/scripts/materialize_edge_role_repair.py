"""Materialize a separate, lossless source-role split; never overwrite a graph."""
import argparse
from collections import Counter
from pathlib import Path

import edge_source_roles as roles
from run_node_context_edges import rows, read, write, jsonl, sha


def materialize(nodes_path, edges_path, prepared, audit_path, output):
    if output.exists():raise ValueError('Fresh output directory required')
    source_nodes=rows(nodes_path);edges=rows(edges_path);audit=read(audit_path)
    nodes={};reps={};source_files=[nodes_path,edges_path,audit_path]
    for node in source_nodes:
        nid=node['id']
        if nid in nodes:raise ValueError('Duplicate node ID')
        path=prepared/node['document']/f"page_{int(node['page']):04d}"/'input_representation.json'
        if path not in reps:
            reps[path]=read(path);source_files.append(path)
        nodes[nid]=roles.attach_source_roles(node,reps[path])
    expected={a['edge_id']:a for a in audit['edge_audits']}
    if len(expected)!=len(audit['edge_audits']):raise ValueError('Duplicate audit edge')
    ids=[e['task_id'] for e in edges]
    if len(set(ids))!=len(ids) or set(ids)!=set(expected):raise ValueError('Edge/audit ID mismatch')
    buckets={'semantic':[],'reference_review':[],'administrative_review':[]}
    for edge in edges:
        actual=roles.audit_edge(edge,nodes)
        if actual!=expected[edge['task_id']]:raise ValueError('Stale source-role audit')
        # This artifact cannot upgrade any model proposal into evidence support.
        if edge.get('evidence_propagation_allowed') is not False:
            raise ValueError('Only non-propagating proposal graphs are supported')
        buckets[actual['route']].append({**edge,'source_role_audit':actual})
    source_hashes={str(p.resolve()):sha(p) for p in source_files}
    jsonl(output/'nodes.jsonl',list(nodes.values()))
    outputs=['nodes.jsonl']
    for route,records in buckets.items():
        name='graph/'+('related' if route=='semantic' else route)+'.jsonl'
        jsonl(output/name,records);outputs.append(name)
    summary={'source_edges':len(edges),'routes':{r:len(v) for r,v in buckets.items()},
             'edges_deleted':0,'nodes_reembedded':0,'source_graph_modified':False,
             'note':'Source-function routing only; retained RELATED proposals are not validated semantic edges. '
                    'Review channels are not automatically citation links or false-edge labels.'}
    write(output/'summary.json',summary);outputs.append('summary.json')
    write(output/'manifest.json',{'inputs':source_hashes,
        'code':{str(p):sha(p) for p in (Path(__file__),Path(roles.__file__))},
        'outputs':{name:sha(output/name) for name in outputs}})
    print(summary)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('nodes','edges','prepared','audit','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    materialize(a.nodes,a.edges,a.prepared,a.audit,a.output)
