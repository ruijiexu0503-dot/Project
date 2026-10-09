#!/usr/bin/env python3
"""Materialize the minimal SAFE_TEMPLATE + mapped block interface."""
import argparse,json
from pathlib import Path
def main():
 p=argparse.ArgumentParser(); p.add_argument('--role-audit',required=True); p.add_argument('--mapped-blocks',required=True); p.add_argument('--output',required=True); a=p.parse_args()
 audit=json.loads(Path(a.role_audit).read_text()); safe={x['cluster_id'] for x in audit['clusters'] if x['classification']=='SAFE_TEMPLATE'}
 rows=[]
 for line in Path(a.mapped_blocks).read_text().splitlines():
  if not line.strip(): continue
  r=json.loads(line)
  if r.get('cluster_id') not in safe: continue
  rows.append({'page':r.get('page_id'),'block_id':r.get('block_id'),'cluster_id':r.get('cluster_id'),'template_status':'SAFE_TEMPLATE','mapping_metrics':r.get('overlap_metrics') or {},'source':'structured_shadow_canonical','reconstruction_metadata':{'template_region_ids':r.get('template_region_ids') or [],'current_role':r.get('current_role'),'text_preview':r.get('text_preview')}})
 uniq={(r['page'],r['block_id']):r for r in rows}; rows=list(uniq.values()); rows.sort(key=lambda x:(x['page'],x['block_id']))
 out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n')
 print(json.dumps({'safe_clusters':sorted(safe),'template_keys':len(rows),'output':str(out)},indent=2))
if __name__=='__main__': main()
