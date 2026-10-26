from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import report_query_edge_gate as report
from test_query_edge_repair import fixture


def inputs(tmp_path):
    fixture(tmp_path)
    e=report.experiment
    entries=e.rows(tmp_path/'gate_inputs.jsonl')
    for entry in entries:
        entry['edge_id']='edge-'+entry['id']
    e.jsonl(tmp_path/'gate_inputs.jsonl',entries)
    manifest=e.read(tmp_path/'manifest.json')
    manifest['files']['gate_inputs.jsonl']=e.sha(tmp_path/'gate_inputs.jsonl')
    e.write(tmp_path/'manifest.json',manifest)
    e.write(tmp_path/'gate_execution.json',{'input_manifest':e.sha(tmp_path/'manifest.json')})


def test_reports_gate_completion_without_retrieval_claim(tmp_path):
    inputs(tmp_path)
    result=report.report(tmp_path,tmp_path/'report')
    assert result['gate_complete'] and result['processed']==6
    assert result['role_counts']=={'DIRECT':6}
    assert result['navigation_allowed']==6
    assert result['retrieval_metrics_computed'] is False
    assert (tmp_path/'report/index.html').is_file()
    with pytest.raises(ValueError,match='Fresh'):
        report.report(tmp_path,tmp_path/'report')


@pytest.mark.parametrize('mutation',['duplicate','hash','quote'])
def test_rejects_unbound_or_ungrounded_predictions(tmp_path,mutation):
    inputs(tmp_path)
    e=report.experiment; predictions=e.rows(tmp_path/'gate_predictions.jsonl')
    if mutation=='duplicate':predictions.append(predictions[0])
    elif mutation=='hash':predictions[0]['prompt_sha256']='wrong'
    else:predictions[0]['result']['target_quote']='Invented claim.'
    e.jsonl(tmp_path/'gate_predictions.jsonl',predictions)
    with pytest.raises(ValueError):
        report.report(tmp_path,tmp_path/'report')
    assert not (tmp_path/'report').exists()
