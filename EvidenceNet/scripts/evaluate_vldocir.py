#!/usr/bin/env python3
"""VL-DocIR page evaluation, with explicit node-to-page score aggregation.

Scores JSONL: {question_id, document_id, page_number, score} or
{question_id, node_id, score} with --node-pages mapping JSONL:
{node_id, source_pages: [{document_id, page_number}]}.
Gold is used only for evaluation, never page ranking or node construction.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

TYPES = ('single-page_single-evidence', 'single-page_multi-evidence',
         'multi-page_connected', 'multi-page_disconnected-close',
         'multi-page_disconnected-distant', 'cross-document_same-type')


def rows(path):
    with path.open() as handle:
        for line in handle:
            if line.strip(): yield json.loads(line)


def page(row):
    return str(row['document_id']), str(row['page_number'])


def metrics(ranked, gold, k):
    top = list(dict.fromkeys(ranked))[:k]
    hits = len(set(top) & gold)
    dcg = sum(1/math.log2(i+2) for i,p in enumerate(top) if p in gold)
    ideal = sum(1/math.log2(i+2) for i in range(min(k,len(gold))))
    ndcg = dcg/ideal
    complete = float(hits == len(gold))
    return {f'Recall@{k}':hits/len(gold), f'nDCG@{k}':ndcg,
            f'RecallAll@{k}':complete, f'nDCGAll@{k}':complete*ndcg}


def evaluate(questions, evidence, scores, node_pages=None, corpus=None):
    queries = {}
    for q in questions:
        qid = str(q['question_id'])
        if qid in queries: raise ValueError('Duplicate question ID')
        if q['question_type'] not in TYPES: raise ValueError('Unknown question type')
        queries[qid] = q['question_type']
    if not queries: raise ValueError('No evaluation questions')
    gold = defaultdict(set)
    for e in evidence:
        qid = str(e['question_id'])
        if qid in queries: gold[qid].add(page(e))
    for qid in queries:
        if not gold[qid]: raise ValueError(f'Missing gold evidence for {qid}')
        if corpus is not None and not gold[qid] <= corpus:
            raise ValueError(f'Corpus missing evidence pages for {qid}')
    ranked_scores = defaultdict(dict)
    for row in scores:
        qid = str(row['question_id'])
        if qid not in queries: raise ValueError(f'Unknown scored query: {qid}')
        score = float(row['score'])
        if not math.isfinite(score): raise ValueError('Non-finite score')
        if 'node_id' in row:
            if node_pages is None or row['node_id'] not in node_pages:
                raise ValueError('Missing explicit node-to-page provenance')
            pages = node_pages[row['node_id']]
            if not pages: raise ValueError('Node has no source pages')
        else: pages = [page(row)]
        for pid in pages:
            if corpus is not None and pid not in corpus: raise ValueError('Scored page outside corpus')
            ranked_scores[qid][pid] = max(score, ranked_scores[qid].get(pid, -math.inf))
    values = {}; by_type = defaultdict(list)
    for qid, kind in queries.items():
        ranked = sorted(ranked_scores[qid], key=lambda p:(-ranked_scores[qid][p],p))
        result = {}
        for k in (3,5,10): result.update(metrics(ranked, gold[qid], k))
        values[qid] = result
        by_type[kind].append(result)
    def avg(items):
        return {key:sum(v[key] for v in items)/len(items) for key in items[0]}
    groups = {key:avg(value) for key,value in by_type.items()}
    return {'queries':len(queries), 'queries_without_results':sum(not ranked_scores[q] for q in queries),
            'micro':avg(list(values.values())), 'by_question_type':groups,
            'macro_six_types':avg(list(groups.values())) if len(groups)==6 else None,
            'macro_present_types':avg(list(groups.values())),
            'missing_question_types':sorted(set(TYPES)-set(groups)), 'per_query':values,
            'page_aggregation':'maximum_score_per_page',
            'note':'No six-type macro reported when a question type is absent.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('questions','evidence','scores','corpus','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--node-pages',type=Path)
    p.add_argument('--scope',choices=['pilot','full-corpus'],default='pilot')
    a=p.parse_args()
    mapping=None
    if a.node_pages:
        mapping={}
        for row in rows(a.node_pages):
            if row['node_id'] in mapping: raise ValueError('Duplicate node provenance')
            mapping[row['node_id']]=[page(x) for x in row['source_pages']]
    corpus={page(r) for r in rows(a.corpus)}
    result=evaluate(rows(a.questions),rows(a.evidence),rows(a.scores),mapping,corpus)
    result.update(scope=a.scope,corpus_pages=len(corpus))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='per_query'},indent=2))


if __name__=='__main__': main()
