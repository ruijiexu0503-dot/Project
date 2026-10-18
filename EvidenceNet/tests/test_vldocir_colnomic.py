import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_vldocir_colnomic import validate_inputs,serializable_loading_info


def test_query_to_official_page_mapping_accepts_cross_document_evidence():
    q=[dict(question_id='q')];p=[dict(document_id='a',page_number=1),dict(document_id='b',page_number=2)]
    e=[dict(question_id='q',**x) for x in p]
    assert validate_inputs(q,p,e)['q']=={('a','1'),('b','2')}


def test_missing_evidence_and_duplicate_pages_stop_inference():
    q=[dict(question_id='q')];p=[dict(document_id='a',page_number=1)]
    with pytest.raises(ValueError):validate_inputs(q,p,[dict(question_id='q',document_id='b',page_number=1)])
    with pytest.raises(ValueError):validate_inputs(q,p+p,[dict(question_id='q',document_id='a',page_number=1)])


def test_transformers_set_diagnostics_are_json_serializable():
    import json
    value=serializable_loading_info({'missing_keys':set(),'unexpected_keys':{'lm_head.weight'},'error_msgs':[]})
    assert json.loads(json.dumps(value))=={'missing_keys':[],'unexpected_keys':['lm_head.weight'],'error_msgs':[]}
