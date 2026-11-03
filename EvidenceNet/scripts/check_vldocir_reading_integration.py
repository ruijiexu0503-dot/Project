#!/usr/bin/env python3
"""Bounded importer-to-navigation check over validated article roots.

The generated probes start from known edge endpoints.  They verify graph plumbing,
not natural-language retrieval quality or evidence recall.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from run_node_context_edges import rows, write, jsonl, sha
import vldocir_reading_backbone as backbone


def run(article_roots, output):
    article_roots=[Path(root).resolve() for root in article_roots];output=Path(output).resolve()
    if output.exists():raise ValueError('fresh integration output required')
    nodes={}
    for root in article_roots:
        for node in rows(root/'units.jsonl'):
            if node['id'] in nodes:raise ValueError('duplicate bounded node: '+node['id'])
            nodes[node['id']]=node
    if not nodes:raise ValueError('no bounded article nodes')
    jsonl(output/'bounded_nodes.jsonl',nodes.values())
    imported=backbone.build(output/'bounded_nodes.jsonl',article_roots,output/'graph')
    directed=rows(output/'graph/reading_edges.jsonl')
    seeds=sorted({edge['source'] for edge in directed})
    paths=backbone.navigate(nodes,directed,seeds)
    expected={(edge['source'],edge['target'],edge['edge_type']) for edge in directed}
    observed={(path['seed_node'],path['target_node'],path['edge_type']) for path in paths}
    if observed!=expected:raise ValueError('imported reading edges not fully navigable')
    jsonl(output/'navigation_paths.jsonl',paths)
    report={'complete':True,'scope':'bounded validated article roots','nodes':len(nodes),
        'article_roots':[str(root) for root in article_roots],'imported':imported,
        'directed_edges':len(directed),'probe_seeds':len(seeds),'navigated_paths':len(paths),
        'next_paths':sum(path['edge_type']=='NEXT' for path in paths),
        'previous_paths':sum(path['edge_type']=='PREVIOUS' for path in paths),
        'cross_page_paths':sum(path['cross_page'] for path in paths),
        'natural_language_query_run':False,'retrieval_quality_measured':False,
        'limitation':'Endpoint-seeded probes validate importer/navigation plumbing only.'}
    write(output/'integration_report.json',report)
    write(output/'integration_manifest.json',{'sources':{str(root/'article_graph_manifest.json'):
        sha(root/'article_graph_manifest.json') for root in article_roots},'files':{
        name:sha(output/name) for name in ('bounded_nodes.jsonl','navigation_paths.jsonl','integration_report.json')}})
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--article-root',action='append',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.article_root,args.output),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
