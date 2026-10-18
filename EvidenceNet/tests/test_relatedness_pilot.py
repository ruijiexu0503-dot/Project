from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_relatedness_pilot import source_spans, validate, reference, pair_key, task_id


def entry():
    return dict(task=dict(task_id='opaque', A=dict(evidence=[dict(evidence_id='A:E000')]),
                         B=dict(evidence=[dict(evidence_id='B:E000')])),
                lookups=dict(A={'A:E000': dict(member_id='m1')}, B={'B:E000': dict(member_id='m2')}))


def value():
    return dict(task_id='opaque', level=2, A_evidence_ids=['A:E000'], B_evidence_ids=['B:E000'],
                reason='Specific dataset variants.', limitation='Different populations, not comparable measurements.')


def test_owned_ids_replace_free_quotes_but_do_not_waive_endpoint_ownership():
    e = entry(); v = value()
    result = validate(v, e)
    assert result['related_score'] == 2 / 3
    assert result['anchors']['A'][0]['member_id'] == 'm1'
    v['A_evidence_ids'] = ['B:E000']
    with pytest.raises(ValueError): validate(v, e)
    v = value(); v['level'] = 0.85
    with pytest.raises(ValueError): validate(v, e)
    v = value(); v['level'] = True
    with pytest.raises(ValueError): validate(v, e)


def test_no_high_score_without_both_endpoint_evidence():
    e = entry(); v = value(); v['B_evidence_ids'] = []
    with pytest.raises(ValueError): validate(v, e)
    e['task']['B']['evidence'] = []
    with pytest.raises(ValueError): validate(value(), e)
    v.update(level=0, A_evidence_ids=[])
    assert validate(v, e)['level'] == 0


def test_native_table_rows_map_to_source_without_string_reformatting():
    table = '<table><tr><td>Dataset</td><td>N</td></tr><tr><td>EuroSAT</td><td>27,000</td></tr></table>'
    spans = source_spans(table)
    assert len(spans) == 2
    assert table[slice(*spans[1])] == '<tr><td>EuroSAT</td><td>27,000</td></tr>'
    text = 'word ' * 1000
    assert set(i for lo, hi in source_spans(text) for i in range(lo, hi)) == set(range(len(text)))


def test_new_related_reference_is_not_copied_from_old_negative():
    assert reference(dict(suite_case_id='N06'))['allowed_levels'] == [2]
    assert reference(dict(suite_case_id='N05'))['allowed_levels'] == [2]
    assert not reference(dict(suite_case_id='U01'))['cutoff_evaluable']
    assert reference(dict(suite_case_id='N14'))['allowed_levels'] == [0]
    assert task_id(pair_key('b', 'a')) == task_id(pair_key('a', 'b'))
