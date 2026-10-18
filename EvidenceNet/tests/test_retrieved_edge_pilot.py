from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_retrieved_edge_pilot import anchor, validate, scope, confirmed_article, report, jsonl, read, source_position


@pytest.mark.parametrize('label,kind,number', [(3, 'pdf_page', 3), ('page_0006', 'pdf_page', 6),
    ('slide_0020', 'slide', 20), ('image_0001', 'image', 1)])
def test_mixed_material_source_positions(label, kind, number):
    position = source_position(dict(document='example', page=label))
    assert position['kind'] == kind and position['number'] == number


def test_legacy_pdf_mapping_remains_correct():
    assert source_position(dict(document='CERNCourier2025JanFeb-digitaledition', page='page_0017'))['number'] == 9


def test_anchor_binds_whitespace_to_exact_owned_source():
    result = anchor(dict(member_id='m', original_text='This is\na specific result.'), 'This is a specific result.')
    assert result['quote'] == 'This is\na specific result.'
    assert result['char_start'] == 0 and result['char_end'] == 26
    assert result['kind'] == 'ORIGINAL_TEXT'
    result = anchor(dict(member_id='v', qwen_visual_description='The figure shows two curves.'), 'shows two curves')
    assert result['kind'] == 'QWEN_VISUAL_DESCRIPTION'
    with pytest.raises(ValueError):
        anchor(dict(member_id='v', qwen_visual_description='The figure shows two curves.'), 'Another endpoint fact')


def fixture():
    task = dict(task_id='opaque', evidence_a=dict(node_id='a', members=[dict(member_id='ma', original_text='An original observation.')]),
                evidence_b=dict(node_id='b', members=[dict(member_id='mb', original_text='The supplied claim.')]))
    result = dict(task_id='opaque', semantic=dict(relation='SUPPORTS', source_node_id='a', target_node_id='b', confidence=0.8),
                  references=dict(exists=False, source_node_id=None, target_node_id=None, cue=None, confidence=0.9),
                  semantic_grounding=dict(source=dict(member_id='ma', quote='original observation'),
                                          target=dict(member_id='mb', quote='supplied claim'), reason='Specific observed evidence.'))
    return task, result


def test_each_endpoint_needs_its_own_grounding():
    task, result = fixture()
    assert validate(result, task)['semantic_grounding']['source']['node_id'] == 'a'
    result['semantic_grounding']['source']['member_id'] = 'mb'
    with pytest.raises(ValueError):
        validate(result, task)


def test_page_local_search_buckets_are_not_confirmed_articles():
    a = dict(document='magazine', original_article_id='page1', assignment_status='PAGE_LOCAL_ONLY')
    b = dict(document='magazine', original_article_id='page2', assignment_status='PAGE_LOCAL_ONLY')
    assert confirmed_article(a) is None
    assert scope(a, b) == 'same_pdf_article_unresolved'
    a.update(assignment_status='KNOWN_PAPER_DOCUMENT_PROFILE', original_article_id='paper')
    b.update(assignment_status='KNOWN_PAPER_DOCUMENT_PROFILE', original_article_id='paper')
    assert scope(a, b) == 'intra_article'


def test_reference_can_exist_without_semantic_edge(tmp_path):
    task, result = fixture()
    result['semantic'] = dict(relation='REJECT_UNCERTAIN', source_node_id=None, target_node_id=None, confidence=0.8)
    result['references'] = dict(exists=True, source_node_id='a', target_node_id='b', cue='original observation', confidence=0.9)
    bound = validate(result, task)
    jsonl(tmp_path / 'inputs.jsonl', [dict(task=task, scope='cross_document')])
    jsonl(tmp_path / 'nodes.jsonl', [dict(id=i, original_article_id=i, assignment_status='PAGE_LOCAL_ONLY') for i in ('a', 'b')])
    jsonl(tmp_path / 'predictions.jsonl', [dict(task_id='opaque', valid=True, result=bound)])
    summary = report(tmp_path)
    assert summary['evidence_edges'] == 1
    assert summary['article_navigation_pairs'] == 0
    assert read(tmp_path / 'summary.json')['complete']
