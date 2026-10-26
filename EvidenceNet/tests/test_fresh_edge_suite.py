import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from report_fresh_edge_suite import score
from build_fresh_edge_suite import SUITE, OUT, node_ids
from run_node_context_edges import rows, read, sha
import run_routed_edge_context as routed

def ref(i, expected):
    return {'task_id':i,'allowed_decisions':[expected], 'decision_evaluable':True}

def test_missing_invalid_and_overpromotion():
    rs=[ref('a','EVIDENCE_LINK'),ref('b','NAVIGATION_LINK'),ref('c','NO_LINK'),ref('d','NO_LINK')]
    ps=[{'task_id':'b','valid':True,'result':{'decision':'EVIDENCE_LINK'}}, {'task_id':'c','valid':False}]
    got=score(rs,ps)
    assert got['scored_total']==4 and got['exact_correct']==0
    assert got['missing']==2 and got['invalid']==1
    assert got['navigation_overpromotion']==1 and got['evidence_overpromotion']==1
    assert got['evidence_recall_all_expected']==0

def test_boundaries_excluded():
    got=score([{'task_id':'x','decision_evaluable':False}],[])
    assert got['boundary_excluded']==1 and got['exact_accuracy_all_scored'] is None

def test_frozen_suite_and_source_anchors():
    for path,digest in read(SUITE/'manifest.json')['files'].items():
        assert sha(SUITE/path)==digest
    cases=rows(SUITE/'cases.jsonl')
    ns={n['id']:n for n in rows(SUITE/'nodes.jsonl')}
    assert len(cases)==40
    audit=read(SUITE/'overlap_audit.json')
    assert not audit['old_endpoint_overlap']
    assert not audit['normalized_original_text_duplicates']
    for c in cases:
        assert c['A']['document'] != c['B']['document']
        for side in ['A','B']:
            for a in c[side]['original_anchors']:
                m=next(m for m in ns[a['node_id']]['members'] if m['id']==a['member_id'] and m['kind']=='atom')
                assert m['text'][a['char_start']:a['char_end']]==a['quote']

def test_inputs_label_free_and_paired():
    routed.verify(OUT,routed.gate.MODEL)
    plans={a:rows(OUT/a/'inputs.jsonl') for a in routed.ARMS}
    for idx in range(40):
        control=plans['control'][idx]
        for arm in routed.ARMS:
            e=plans[arm][idx]
            assert e['task']['task_id']==control['task']['task_id']
            assert e['images']==control['images']
            assert all(k not in e['task'] for k in ['allowed_decisions','annotation_label','suite_case_id','rationale'])
            assert e['inference_key']==routed.inference_key(e)
            assert e['image_sha256']==[sha(p) for p in e['images']]
        assert not any(control['contexts'].values())
