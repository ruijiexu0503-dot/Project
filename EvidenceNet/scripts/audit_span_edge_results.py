"""Offline audit of frozen span pilot results; no gold judgments inferred from scores."""
import json
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[2]
P=ROOT/'migration/span_results_5218190_20261030/top10_span_navigation_20261030'
Q=ROOT/'migration/span_results_5218191_20261030/query_span_selection_20261030'
OUT=ROOT/'EvidenceNet/output/span_edge_audit_20261030'
def rows(p):return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
def audit():
 tasks={t['question_id']:t for t in rows(P/'tasks.jsonl')}; findings=[]
 for c in rows(P/'navigation.jsonl'):
  qid=c['question_id'];t=tasks[qid]
  result=json.loads((P/'predictions'/f'{qid}.json').read_text())['result']
  assessments={a['id']:a for a in result['packets']}
  for nid in sorted({p['target_node'] for p in c['paths'] if p['outside_top10']}):
   packets=[{'id':pid,'text':p['text'],'assessment':assessments[pid]} for pid,p in t['packets'].items() if p['node_id']==nid]
   findings.append({'question_id':qid,'question':t['question'],'target_node':nid,
    'paths':[p for p in c['paths'] if p['target_node']==nid and p['outside_top10']],
    'requirements':result['requirements'],'packets':packets,
    'covers_any_requirement':any(p['assessment']['covers'] for p in packets)})
 scores=Counter(p['assessment']['score'] for f in findings for p in f['packets'])
 selected=rows(Q/'selected.jsonl');groups={}
 for r in selected:groups.setdefault((r['question_id'],r['budget']),{})[r['arm']]=r
 changes=sum(g['Q1_query_coverage']['evidence_text']!=g['Q2_query_coverage_edge_gate']['evidence_text'] for g in groups.values())
 summary={'new_query_node_pairs':len(findings),'queries_with_new_nodes':len({f['question_id'] for f in findings}),
  'new_packet_score_counts':dict(scores),'new_nodes_with_coverage':sum(f['covers_any_requirement'] for f in findings),
  'fixed_pool_complete_queries':len({q for q,b in groups}),'fixed_pool_query_budget_comparisons':len(groups),
  'fixed_pool_edge_changes':changes,'scores_and_coverage_are_model_estimates':True}
 OUT.mkdir(exist_ok=True)
 (OUT/'audit.json').write_text(json.dumps({'summary':summary,'cases':findings},ensure_ascii=False,indent=2))
 print(json.dumps(summary,indent=2))
if __name__=='__main__':audit()
