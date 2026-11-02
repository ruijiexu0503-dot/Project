import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_vldocir_article_codefix import classify_error


def test_failure_taxonomy_categories_are_deterministic():
    assert classify_error('No complete JSON value in model output')=='json_parse'
    assert classify_error('group node ownership')=='node_ownership'
    assert classify_error('visual/table/caption needs a separate flow')=='visual_flow_contract'
    assert classify_error('flow kind invalid')=='flow_kind'
    assert classify_error("flow outside group G1: ['T001']")=='flow_membership'
    assert classify_error('single work must retain exactly one article group')=='single_article_group_count'
