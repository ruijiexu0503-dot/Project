"""Select only Balanced-v1 eligible IMAGE nodes for visual-description enrichment."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from common import read_jsonl, write_json, write_jsonl
def main():
    p=argparse.ArgumentParser(); p.add_argument('--catalog',type=Path,required=True); p.add_argument('--canonical-nodes',type=Path,required=True); p.add_argument('--out',type=Path,required=True); a=p.parse_args()
    selected={r['node_id'] for r in read_jsonl(a.catalog) if r['node_type']=='IMAGE'}
    rows=[r for r in read_jsonl(a.canonical_nodes) if r['id'] in selected]
    if len(rows)!=len(selected): raise ValueError(f'catalog/canonical IMAGE mismatch: catalog={len(selected)} canonical={len(rows)}')
    if any(r.get('node_type')!='IMAGE' for r in rows): raise ValueError('non-IMAGE node selected')
    a.out.mkdir(parents=True,exist_ok=True); write_jsonl(a.out/'balanced_image_nodes.jsonl',rows)
    write_json(a.out/'selection_manifest.json',{'policy':'Balanced v1 eligible IMAGE endpoints only','selected_image_nodes':len(rows),'catalog':str(a.catalog),'canonical_nodes':str(a.canonical_nodes),'query_used':False,'stage1_thresholds_recomputed':False})
    print(len(rows))
if __name__=='__main__': main()
