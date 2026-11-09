"""Audit reviewed labels in structural-only pairs without treating unknowns as negatives."""
import argparse, json
from collections import Counter
from pathlib import Path
from .common import read_jsonl, write_jsonl

def pair(r): return tuple(sorted((str(r['source_id']),str(r['target_id']))))
def main():
    p=argparse.ArgumentParser(); p.add_argument('--source-run',required=True); p.add_argument('--output-dir',required=True); p.add_argument('--reviewed',required=True); p.add_argument('--semantic-routes',nargs='+',required=True); a=p.parse_args()
    source=Path(a.source_run); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    structural={pair(r) for r in read_jsonl(source/'route_candidates'/'structural.jsonl')}
    semantic=set()
    for route in a.semantic_routes: semantic|={pair(r) for r in read_jsonl(source/'route_candidates'/f'{route}.jsonl')}
    only=structural-semantic; labels=[]
    for row in read_jsonl(Path(a.reviewed)):
        left=row.get('A',{}).get('node_id'); right=row.get('B',{}).get('node_id')
        if left and right and tuple(sorted((str(left),str(right)))) in only:
            labels.append({'source_id':min(str(left),str(right)),'target_id':max(str(left),str(right)),'label':row.get('label'),'relation':row.get('relation'),'case_id':row.get('case_id',row.get('suite_case_id'))})
    write_jsonl(out/'structural_only_reviewed_cases.jsonl',labels)
    counts=Counter(x['label'] for x in labels)
    (out/'structural_only_review_audit.json').write_text(json.dumps({'structural_only_pair_count':len(only),'reviewed_pair_count':len(labels),'reviewed_label_counts':dict(counts),'interpretation':'This is only overlap with the existing purpose-limited reviewed panel; it is not corpus-wide semantic recall.'},indent=2,sort_keys=True))
    print(json.dumps({'structural_only_pairs':len(only),'reviewed':dict(counts)}))
if __name__=='__main__': main()
