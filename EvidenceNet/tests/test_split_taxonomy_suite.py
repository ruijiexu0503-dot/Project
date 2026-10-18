import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_split_taxonomy_suite import node_input, pair_prompt, validate_result
from split_taxonomy_suite_reference import annotate


def task():
    return dict(task_id='opaque', evidence_a=dict(node_id='a', members=[{'original_text': 'See Fig. 2.'}]),
                evidence_b=dict(node_id='b', members=[{'original_text': 'A result.'}]))


def value():
    return dict(task_id='opaque', semantic=dict(relation='SUPPORTS', source_node_id='b',
                target_node_id='a', confidence=0.9), references=dict(exists=True,
                source_node_id='a', target_node_id='b', cue='Fig. 2', confidence=0.9))


def test_independent_directions_and_owned_reference_cue():
    assert validate_result(value(), task())[1]
    v = value()
    v['references']['source_node_id'], v['references']['target_node_id'] = 'b', 'a'
    assert not validate_result(v, task())[1]
    v = value(); v['semantic']['source_node_id'] = 'third'
    assert not validate_result(v, task())[1]
    v = value(); v['semantic']['confidence'] = 1.5
    assert not validate_result(v, task())[1]
    v = value(); v['task_id'] = 'other'
    assert not validate_result(v, task())[1]


def test_negative_premise_and_blind_node_input(tmp_path, monkeypatch):
    import run_split_taxonomy_suite as runner
    monkeypatch.setattr(runner, 'SUITE', tmp_path)
    (tmp_path / 'crop.jpg').write_bytes(b'placeholder')
    n = dict(id='n', document='paper', original_pdf_page=2,
             text='generated aggregate SHOULD NOT LEAK',
             members=[dict(id='t', kind='atom', text='Original'),
                      dict(id='v', kind='visual', text='Existing Qwen description', crop='crop.jpg'),
                      dict(id='f', kind='atom', text='footer SHOULD NOT LEAK')],
             eligible_members=[dict(member_id='t', kind='atom', eligible=True),
                               dict(member_id='v', kind='visual', eligible=True),
                               dict(member_id='f', kind='atom', eligible=False)])
    out = node_input(n)
    assert out['members'] == [dict(member_id='t', kind='atom', original_text='Original'),
                              dict(member_id='v', kind='visual', qwen_visual_description='Existing Qwen description')]
    assert 'SHOULD NOT LEAK' not in json.dumps(out)
    prompt = pair_prompt(task())
    assert 'known to be related' not in prompt
    assert 'may be related or unrelated' in prompt
    assert 'existing Qwen-generated descriptions' in prompt


def test_description_does_not_create_document_reference():
    t = task()
    t['evidence_a']['members'] = [dict(qwen_visual_description='See Fig. 2.')]
    assert not validate_result(value(), t)[1]


def test_functional_reference_does_not_copy_identity_labels():
    c = dict(case_id='opaque', suite_case_id='N05', relation='METHOD_CORRESPONDENCE',
             label='NEGATIVE', A=dict(node_id='a'), B=dict(node_id='b'))
    r = annotate(c)
    assert r['allowed_semantic_readings'][0]['relation'] == 'EXPLAINS_OR_ELABORATES'
    c['suite_case_id'] = 'P26'
    assert annotate(c)['allowed_semantic_readings'][0]['source_node_id'] == 'b'
    c['suite_case_id'] = 'P23'
    assert not annotate(c)['references']['exists']  # equation points to third node
    c['suite_case_id'] = 'P13'
    assert annotate(c)['semantic_status'] == 'UNRESOLVED'
    assert not annotate(c)['allowed_semantic_readings']
