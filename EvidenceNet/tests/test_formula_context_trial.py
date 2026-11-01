import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_formula_context_trial as trial


def setup_trial(tmp_path, monkeypatch):
    monkeypatch.setattr(trial.routed,'verify',lambda out:None)
    trial.write(tmp_path/'summary.json',{'complete':True})
    trial.write(tmp_path/'protocol.json',{'scope':'synthetic test only'})
    cohort='fresh_reviewed_now_diagnostic'
    cases=[dict(task_id=str(i),case_id=str(i),cohort=cohort) for i in range(3)]
    refs=[dict(task_id=str(i),decision_evaluable=True,cutoff_evaluable=True,allowed_decisions=[label],
               allowed_levels=[2,3] if i<2 else [0,1]) for i,label in enumerate(('EVIDENCE_LINK','NAVIGATION_LINK','NO_LINK'))]
    predictions=[dict(task_id='0',valid=False,result=None),
                 *[dict(task_id=str(i),valid=True,result=dict(decision='EVIDENCE_LINK',discovery_level=2)) for i in (1,2)]]
    trial.jsonl(tmp_path/'case_map.jsonl',cases);trial.jsonl(tmp_path/'reference.jsonl',refs)
    for arm in trial.ARMS:trial.jsonl(tmp_path/arm/'predictions.jsonl',predictions)


def test_formula_report_keeps_invalids_and_navigation_promotion_separate(tmp_path,monkeypatch):
    setup_trial(tmp_path,monkeypatch)
    result=trial.report(tmp_path)
    stats=result['metrics']['control']['fresh_reviewed_now_diagnostic']
    assert stats['strict_scored']==3 and stats['strict_correct']==0
    assert stats['positive']==2 and stats['useful_tp']==1
    assert stats['negative']==1 and stats['accepted_fp']==1 and stats['invalid']==1


def test_incomplete_formula_trial_cannot_publish_final_metrics(tmp_path,monkeypatch):
    setup_trial(tmp_path,monkeypatch)
    trial.write(tmp_path/'summary.json',{'complete':False})
    with pytest.raises(ValueError,match='incomplete'):trial.report(tmp_path)
    assert not (tmp_path/'formula_results.json').exists()


def test_missing_pair_is_rejected_even_if_runner_claims_complete(tmp_path,monkeypatch):
    setup_trial(tmp_path,monkeypatch)
    trial.jsonl(tmp_path/'control/predictions.jsonl',[])
    with pytest.raises(ValueError,match='missing or unexpected'):trial.report(tmp_path)
