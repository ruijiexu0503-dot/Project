"""Canonical candidate-edge distribution analysis; candidates are not verified edges."""
from __future__ import annotations
import argparse, csv, json, math
from collections import Counter
from pathlib import Path
import numpy as np
from .common import load_config, node_record, read_jsonl, repo_path, run_dir

def pair(row): return tuple(sorted((str(row['source_id']), str(row['target_id']))))
def pct(v, q): return float(np.quantile(v, q)) if len(v) else None

def canonical_metadata(config):
    # Corpus records, unlike retrieval views, carry canonical modality/document/page.
    corpus = repo_path(config.get('canonical_node_path', 'EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/corpus_nodes.jsonl'))
    meta = {}
    for i, row in enumerate(read_jsonl(corpus)):
        value = node_record(row, i); meta[value['node_id']] = value
    for i, row in enumerate(read_jsonl(repo_path(config['node_path']))):
        value = node_record(row, i); meta.setdefault(value['node_id'], value)
    return meta

def describe(pairs, meta, total_nodes):
    nodes = {n for p in pairs for n in p}; degree = Counter(n for p in pairs for n in p)
    cross_doc = sum(meta.get(a, {}).get('document_id') != meta.get(b, {}).get('document_id') for a,b in pairs)
    cross_mod = sum(meta.get(a, {}).get('modality') != meta.get(b, {}).get('modality') for a,b in pairs)
    ds = list(degree.values())
    return {'unique_candidate_pairs': len(pairs), 'possible_node_pairs': total_nodes*(total_nodes-1)//2,
            'candidate_pair_fraction': len(pairs)/max(total_nodes*(total_nodes-1)//2,1),
            'covered_nodes': len(nodes), 'isolated_nodes': total_nodes-len(nodes),
            'mean_candidate_degree_all_nodes': 2*len(pairs)/max(total_nodes,1),
            'mean_candidate_degree_covered_nodes': 2*len(pairs)/max(len(nodes),1),
            'degree_p50_covered': pct(ds,.5), 'degree_p90_covered': pct(ds,.9), 'degree_max': max(ds, default=0),
            'cross_document_pairs': cross_doc, 'cross_modality_pairs': cross_mod}

def route_rows(path):
    rows = list(read_jsonl(path)); return rows, {pair(r) for r in rows}

def line_svg(path, points, title, x_label):
    """Dependency-free SVG line chart for reproducible count curves."""
    width,height,left,bottom=760,360,70,55
    xs=[float(x) for x,_ in points]; ys=[float(y) for _,y in points]
    xmin,xmax=min(xs),max(xs); ymin,ymax=0,max(ys) or 1
    coords=[(left+(x-xmin)/(xmax-xmin or 1)*(width-left-20),height-bottom-(y-ymin)/(ymax-ymin)*(height-bottom-45)) for x,y in zip(xs,ys)]
    labels=''.join(f'<text x="{x:.1f}" y="{height-22}" text-anchor="middle">{int(v)}</text>' for (x,_),v in zip(coords,xs))
    dots=''.join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4"/>' for x,y in coords)
    path.write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><style>text{{font:12px sans-serif}}path{{fill:none;stroke:#1769aa;stroke-width:3}}circle{{fill:#1769aa}}</style><text x="{left}" y="24" style="font-weight:bold">{title}</text><line x1="{left}" y1="{height-bottom}" x2="{width-20}" y2="{height-bottom}" stroke="black"/><line x1="{left}" y1="45" x2="{left}" y2="{height-bottom}" stroke="black"/><path d="M {' L '.join(f'{x:.1f} {y:.1f}' for x,y in coords)}"/>{dots}{labels}<text x="{width/2}" y="{height-4}" text-anchor="middle">{x_label}</text><text x="8" y="50">{int(ymax):,}</text><text x="20" y="{height-bottom}">0</text></svg>''',encoding='utf-8')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',required=True); ap.add_argument('--source-run'); ap.add_argument('--topk-run',action='append',default=[]); ap.add_argument('--exclude-route',action='append',default=[]); ap.add_argument('--analysis-id'); args=ap.parse_args()
    config=load_config(args.config); source=repo_path(args.source_run) if args.source_run else run_dir(config)
    out=repo_path(str(config['output_root'])) / (args.analysis_id or (str(config['run_id']) + '-distribution')); out.mkdir(parents=True,exist_ok=True)
    meta=canonical_metadata(config); total=len(meta)
    data, sets={},{}
    route_names=[r for r in config['routes'] if r not in set(args.exclude_route)]
    excluded={}
    for route in config['routes']:
        rows, pairs=route_rows(source/'route_candidates'/f'{route}.jsonl'); data[route]=rows; sets[route]=pairs
        if route not in route_names: excluded[route]=pairs
    all_union=set().union(*(sets[r] for r in route_names))
    fields=['route','unique_candidate_pairs','possible_node_pairs','candidate_pair_fraction','covered_nodes','isolated_nodes','mean_candidate_degree_all_nodes','mean_candidate_degree_covered_nodes','degree_p50_covered','degree_p90_covered','degree_max','cross_document_pairs','cross_modality_pairs','unique_to_route','incremental_union_contribution','leave_one_out_pairs_lost']
    incremental=set(); summary=[]
    for route in route_names:
        exclusive=sets[route]-set().union(*(sets[x] for x in route_names if x!=route)); before=len(incremental); incremental|=sets[route]
        row={'route':route,**describe(sets[route],meta,total),'unique_to_route':len(exclusive),'incremental_union_contribution':len(incremental)-before,'leave_one_out_pairs_lost':len(exclusive)}; summary.append(row)
    summary.append({'route':f'ALL_{len(route_names)}_OR_UNION',**describe(all_union,meta,total),'unique_to_route':None,'incremental_union_contribution':len(all_union),'leave_one_out_pairs_lost':None})
    with (out/'route_distribution.csv').open('w',newline='',encoding='utf-8') as f: w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(summary)
    overlap={}
    for i,left in enumerate(route_names):
        for right in route_names[i+1:]:
            inter=len(sets[left]&sets[right]); union=len(sets[left]|sets[right]); overlap[f'{left}__{right}']={'intersection_pairs':inter,'jaccard':inter/union if union else None,'overlap_left':inter/len(sets[left]) if sets[left] else None,'overlap_right':inter/len(sets[right]) if sets[right] else None}
    multiplicity=Counter(sum(p in s for s in sets.values()) for p in all_union)
    (out/'route_overlap.json').write_text(json.dumps({'pairwise':overlap,'union_route_multiplicity':dict(sorted(multiplicity.items()))},indent=2,sort_keys=True))
    # Keep structural construction separate; audit only its pairs absent from semantic retrieval.
    if 'structural' in excluded:
        structural_only=excluded['structural']-all_union
        (out/'structural_graph_separation.json').write_text(json.dumps({
            'semantic_routes':route_names, 'structural_route_included_in_semantic_union':False,
            'structural_pairs_at_retrieval_ceiling':len(excluded['structural']),
            'structural_semantic_overlap_pairs':len(excluded['structural']&all_union),
            'structural_only_pairs':len(structural_only),
            'note':'Structural-only pairs remain input to the separate Structural Graph, not semantic candidates.'
        },indent=2,sort_keys=True))
    # Route-specific score quantiles avoid comparing raw score scales.
    threshold_rows=[]; gates={}
    for route,rows in data.items():
        scores=np.asarray([float(r['raw_score']) for r in rows]); gates[route]={f'q{int(q*100)}':float(np.quantile(scores,q)) for q in (0,.5,.75,.9)}
        for label,t in gates[route].items():
            retained={pair(r) for r in rows if float(r['raw_score'])>=t}; threshold_rows.append({'scheme':route,'gate':label,'raw_threshold':t,**describe(retained,meta,total)})
    for label in ('q0','q50','q75','q90'):
        retained=set().union(*({pair(r) for r in data[route] if float(r['raw_score'])>=gates[route][label]} for route in route_names))
        threshold_rows.append({'scheme':'OR_UNION_independent_quantile_gates','gate':label,'raw_threshold':json.dumps({r:gates[r][label] for r in route_names},sort_keys=True),**describe(retained,meta,total)})
    with (out/'threshold_sensitivity.csv').open('w',newline='',encoding='utf-8') as f: w=csv.DictWriter(f,fieldnames=list(threshold_rows[0]));w.writeheader();w.writerows(threshold_rows)
    # Reuse separately generated ANN runs for genuine Top-K sensitivity.
    topk=[]
    for item in args.topk_run:
        k, directory=item.split('=',1); directory=repo_path(directory); per=[]
        for route in route_names:
            _, s=route_rows(directory/'route_candidates'/f'{route}.jsonl'); per.append(s)
        topk.append({'top_k':int(k),**describe(set().union(*per),meta,total)})
    if topk:
        topk.sort(key=lambda x:x['top_k'])
        with (out/'topk_sensitivity.csv').open('w',newline='',encoding='utf-8') as f: w=csv.DictWriter(f,fieldnames=list(topk[0]));w.writeheader();w.writerows(topk)
        line_svg(out/'topk_candidate_count.svg', [(x['top_k'],x['unique_candidate_pairs']) for x in topk], 'All-route union candidate count', 'Top-K per route')
    union_threshold=[x for x in threshold_rows if x['scheme']=='OR_UNION_independent_quantile_gates']
    line_svg(out/'threshold_candidate_count.svg', [(int(x['gate'][1:]),x['unique_candidate_pairs']) for x in union_threshold], 'Independent-gate OR-union candidate count', 'Route-specific score quantile')
    degrees=Counter(n for p in all_union for n in p)
    (out/'degree_distribution.json').write_text(json.dumps({'total_canonical_nodes':total,'union_degree_histogram':dict(sorted(Counter(degrees.values()).items())),'isolated_nodes':sorted(set(meta)-set(degrees))},indent=2,sort_keys=True))
    report=out/'reports'/'candidate_distribution.md';report.parent.mkdir(parents=True,exist_ok=True)
    lines=['# Semantic Candidate Distribution & Coverage Analysis','','All quantities are canonical undirected Node--Node **semantic candidates**, not verified semantic edges. Structural construction is excluded from this union and remains a separate graph input. Dense routes use bounded HNSW ANN; no all-pairs score matrix was computed.','',f'Canonical Node universe: **{total}**; possible undirected pairs: **{total*(total-1)//2:,}**.','','## Semantic route distribution','','| Route | Pairs | Covered nodes | Isolated | Avg degree | Cross-doc | Cross-modality | Unique to route |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for x in summary: lines.append(f"| {x['route']} | {x['unique_candidate_pairs']:,} | {x['covered_nodes']:,} | {x['isolated_nodes']:,} | {x['mean_candidate_degree_all_nodes']:.2f} | {x['cross_document_pairs']:,} | {x['cross_modality_pairs']:,} | {x['unique_to_route'] if x['unique_to_route'] is not None else '—'} |")
    lines += ['', '## Route multiplicity in all-route union','', '| Number of routes discovering pair | Pair count |','|---:|---:|'] + [f'| {k} | {v:,} |' for k,v in sorted(multiplicity.items())]
    if 'structural' in excluded:
        lines += ['', '## Structural graph separation','',f"Structural ceiling pairs: **{len(excluded['structural']):,}**; overlapping semantic candidates: **{len(excluded['structural']&all_union):,}**; structural-only pairs: **{len(excluded['structural']-all_union):,}**. Structural-only pairs are not discarded from the overall graph: they remain owned by the separate Structural Edge Construction Pipeline."]
    if topk: lines += ['', '## Top-K all-route union sensitivity','', '| Top-K | Pairs | Covered nodes | Isolated | Avg degree |','|---:|---:|---:|---:|---:|'] + [f"| {x['top_k']} | {x['unique_candidate_pairs']:,} | {x['covered_nodes']:,} | {x['isolated_nodes']:,} | {x['mean_candidate_degree_all_nodes']:.2f} |" for x in topk]
    lines += ['', 'Detailed CSV/JSON files contain pairwise overlaps (with intersections bounded by each input set), independent raw-score quantile gates, degree histograms, and canonical metadata accounting.']
    report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(out),'canonical_nodes':total,'union_pairs':len(all_union),'topk_runs':len(topk)}))
if __name__=='__main__': main()
