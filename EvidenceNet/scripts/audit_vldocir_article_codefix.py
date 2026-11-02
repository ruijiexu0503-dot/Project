#!/usr/bin/env python3
"""CPU-only Milestone 0 inventory for the historical VLDocIR reading run."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT=Path(__file__).resolve().parents[2]
DEFAULT_RUN=Path('/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/vldocir-pipeline-compare-20261025')
DEFAULT_NODES=ROOT/'migration/vldocir-edge-20261022/results/nodes.jsonl'
DEFAULT_OUT=ROOT/'EvidenceNet/output/vldocir_article_reading_codefix_v1_20261102'


def read(path:Path)->dict[str,Any]:return json.loads(path.read_text(encoding='utf-8'))


def rows(path:Path)->list[dict[str,Any]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path:Path,values:Iterable[dict[str,Any]])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(v,ensure_ascii=False,sort_keys=True)+'\n' for v in values),encoding='utf-8')


def write(path:Path,value:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')


def classify_error(error:str|None)->str:
    value=(error or 'missing_error').lower()
    checks=(
        ('json_parse','json'),('single_article_group_count','single work must retain'),
        ('node_ownership','group node ownership'),('title_coverage','title ownership'),
        ('title_coverage','every title'),('node_coverage','node coverage'),
        ('flow_membership','flow outside group'),('visual_flow_contract','visual/table/caption'),
        ('flow_kind','flow kind'),('missing_groups','groups required'),
        ('group_identity','group'),('label_hallucination','unknown label'),
        ('type_schema','type'),('body_flow_contract','body'),('empty_or_missing','missing'),
    )
    for category,needle in checks:
        if needle in value:return category
    return 'other_validator_error'


def cache_record(path:Path,root:Path,page_map:dict[str,dict[str,Any]])->dict[str,Any]:
    record=read(path);attempts=record.get('attempts',[])
    errors=[a.get('error') for a in attempts if isinstance(a,dict) and a.get('error')]
    page_id=path.stem;page=page_map.get(page_id,{})
    return {'document_id':root.name,'page_id':page_id,'task':page.get('task'),'page':page.get('page'),
        'stage':'membership' if path.parent.name=='page_decisions' else 'reading',
        'path':str(path),'valid':record.get('valid'),'input_fingerprint':record.get('input_sha256'),
        'attempt_count':len(attempts),'attempt_errors':errors,'final_error':errors[-1] if errors else None,
        'error_category':classify_error(errors[-1] if errors else None),
        'value_present':record.get('value') is not None}


def run(run_root:Path,nodes_path:Path,output:Path)->dict[str,Any]:
    base=run_root/'EvidenceNet/output/vldocir_pipeline_comparison_20261025'
    articles=base/'articles';plan=read(base/'plan.json');nodes=rows(nodes_path)
    by_doc=Counter(n['document'] for n in nodes);pages_by_doc={}
    for node in nodes:pages_by_doc.setdefault(node['document'],set()).add(str(node['page']))
    assigned={doc:(int(worker),position) for worker,docs in plan['worker_documents'].items() for position,doc in enumerate(docs)}
    inventories=[];checkpoints=[]
    for document in plan['documents']:
        root=articles/document;graph=root/'article_graph_manifest.json';summary=root/'summary.json'
        graph_data=read(graph) if graph.exists() else {};summary_data=read(summary) if summary.exists() else {}
        worker,position=assigned[document]
        inventories.append({'document_id':document,'worker_index':worker,'worker_position':position,
            'pages':len(pages_by_doc[document]),'nodes':by_doc[document],
            'historically_attempted':root.exists(),'historical_output_root':str(root),
            'status':'partial' if root.exists() else 'pending',
            'membership_state':('complete' if graph_data.get('ready_for_downstream') else 'partial') if root.exists() else 'pending',
            'reading_state':('complete' if graph_data.get('reading_ready') else 'partial') if root.exists() else 'pending',
            'ready_for_downstream':graph_data.get('ready_for_downstream'),'reading_ready':graph_data.get('reading_ready'),
            'assignments':summary_data.get('nodes',0),'next_edges':summary_data.get('reading_edges',0),
            'membership_failures':len(summary_data.get('failures',[])),
            'reading_failures':len(summary_data.get('reading_failures',[])),
            'document_mode':'single_article' if root.exists() else 'configured_single_article_not_executed',
            'mode_evidence':'recorded pages.jsonl' if root.exists() else 'worker passes --single-document; no executed page artifact'})
        if root.exists():
            page_map={p['page_id']:p for p in rows(root/'pages.jsonl')}
            for directory in ('page_decisions','reading_decisions'):
                for path in sorted((root/directory).glob('*.json')):
                    checkpoints.append(cache_record(path,root,page_map))
    invalid=[r for r in checkpoints if r['valid'] is False]
    jsonl(output/'document_inventory.jsonl',inventories)
    jsonl(output/'checkpoint_inventory.jsonl',checkpoints)
    jsonl(output/'failure_taxonomy.jsonl',invalid)
    attempted=[r for r in inventories if r['historically_attempted']]
    missing=[r for r in inventories if not r['historically_attempted']]
    membership={r['page_id'] for r in invalid if r['stage']=='membership'}
    reading={r['page_id'] for r in invalid if r['stage']=='reading'}
    log_errors=Counter()
    for path in sorted((run_root/'logs').glob('pipeline-compare-build-5212510_*.err')):
        text=path.read_text(encoding='utf-8',errors='replace')
        if 'Article reconstruction incomplete' in text:log_errors['membership_runtime_error']+=1
        elif 'reading flow unresolved' in text:log_errors['reading_runtime_error']+=1
        else:log_errors['other']+=1
    summary={'documents':len(inventories),'pages':sum(r['pages'] for r in inventories),'nodes':sum(r['nodes'] for r in inventories),
        'attempted_documents':len(attempted),'attempted_pages':sum(r['pages'] for r in attempted),
        'missing_documents':len(missing),'missing_pages':sum(r['pages'] for r in missing),
        'checkpoints':len(checkpoints),'valid_checkpoints':sum(r['valid'] is True for r in checkpoints),
        'invalid_checkpoints':len(invalid),'membership_invalid':sum(r['stage']=='membership' for r in invalid),
        'reading_invalid':sum(r['stage']=='reading' for r in invalid),'failed_page_overlap':len(membership&reading),
        'error_categories':dict(Counter(r['error_category'] for r in invalid)),
        'worker_errors':dict(log_errors),'hashes':{'nodes':sha(nodes_path),'plan':sha(base/'plan.json'),
        'executed_driver':sha(run_root/'EvidenceNet/scripts/run_vldocir_pipeline_comparison.py'),
        'workers_sbatch':sha(run_root/'workers.sbatch')},
        'implementation_hashes':{
            'EvidenceNet/scripts/run_vldocir_pipeline_comparison.py':sha(ROOT/'EvidenceNet/scripts/run_vldocir_pipeline_comparison.py'),
            'EvidenceNet/scripts/audit_vldocir_article_codefix.py':sha(Path(__file__)),
            'EvidenceNet/tests/test_vldocir_pipeline_comparison.py':sha(ROOT/'EvidenceNet/tests/test_vldocir_pipeline_comparison.py'),
            'EvidenceNet/tests/test_vldocir_article_codefix_audit.py':sha(ROOT/'EvidenceNet/tests/test_vldocir_article_codefix_audit.py')}}
    write(output/'milestone0_summary.json',summary)
    (output/'execution_root_cause.md').write_text(f"""# Executed Root Cause

Date: 2026-11-02  
Status: CPU/read-only inspection of historical job 5212510

The executed driver SHA is `{summary['hashes']['executed_driver']}` and the worker launcher SHA is `{summary['hashes']['workers_sbatch']}`. `workers.sbatch` submitted array `0-15%2`; `plan.json` assigned two documents to every index.

The exact exception chain is `workers.sbatch -> run_vldocir_pipeline_comparison.worker() -> subprocess reading stage -> reading_run() -> run_hybrid_article_clustering.materialize()`. Fourteen first documents raised `Article reconstruction incomplete` from membership issues. Two returned from materialization with membership ready but `reading_ready=false`, after which `reading_run()` raised `reading flow unresolved`. `subprocess.run(check=True)` propagated either failure and terminated the worker loop before position 1.

Observed scope: 16 position-0 documents / {summary['attempted_pages']} pages attempted; 16 position-1 documents / {summary['missing_pages']} pages not attempted. Cache inventory contains {summary['invalid_checkpoints']} invalid records: {summary['membership_invalid']} membership and {summary['reading_invalid']} reading, with {summary['failed_page_overlap']} page-ID overlap. Existing invalid records have immutable raw attempts and are returned by the historical caller rather than retried.

`reading_order.order_blocks()` remains unverified for this exact job. Recorded parser/member order is not promoted to proof of that invocation.
""",encoding='utf-8')
    return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-root',type=Path,default=DEFAULT_RUN)
    parser.add_argument('--nodes',type=Path,default=DEFAULT_NODES);parser.add_argument('--output',type=Path,default=DEFAULT_OUT)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    print(json.dumps(run(args.run_root,args.nodes,args.output),ensure_ascii=False))


if __name__=='__main__':main()
