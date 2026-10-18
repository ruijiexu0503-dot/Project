import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from retrieve_vldocir import document_model_input,query_model_input


def test_document_metadata_cannot_enter_model_input():
    source={'text':'Original evidence.','context':'Source title'}
    dirty={**source,'node_id':'SECRET_ID','bbox':[1,2,3,4],'status':'DEBUG',
           'decision_file':'private/path','gold_evidence':'GOLD_LABEL'}
    assert document_model_input(dirty)=={'title_context':'Source title','content':'Original evidence.'}
    assert document_model_input(source)==document_model_input(dirty)


def test_query_answer_and_labels_cannot_enter_model_input():
    q={'question':'What happened?','answer':'Forbidden answer','question_id':'ID','gold':['page']}
    assert query_model_input(q)=='Instruct: Retrieve document pages containing evidence to answer the question.\nQuery: What happened?'


def test_invalid_content_is_not_coerced_into_prompt():
    with pytest.raises(ValueError):document_model_input({'text':{},'context':'Title'})
    with pytest.raises(ValueError):query_model_input({'question':None})
