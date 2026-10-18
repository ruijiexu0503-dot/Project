import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_split_modality_comparison import (
    MODES, asset_key, node_representation, pair_prompt, semantic_matches, compare,
    jsonl,
)


def fixture_node():
    return dict(id='n', source_collection='test', document='doc', original_pdf_page=1,
                members=[dict(id='p', kind='atom', type='text', text='Ordinary paragraph'),
                         dict(id='c', kind='atom', type='text', role='cap', text='Figure caption'),
                         dict(id='v', kind='visual', text='Existing visual description'),
                         dict(id='t', kind='atom', type='table', role='tab', text='<table>SECRET HTML</table>'),
                         dict(id='f', kind='atom', type='text', text='Excluded footer')],
                eligible_members=[dict(kind=k, member_id=i, eligible=i != 'f')
                                  for k, i in [('atom', 'p'), ('atom', 'c'), ('visual', 'v'),
                                               ('atom', 't'), ('atom', 'f')]])


def test_three_modes_change_only_nontext_representations():
    n = fixture_node()
    assets, desc = {}, {}
    for m in n['members'][2:4]:
        key = asset_key(n, m)
        assets[key] = dict(crop=m['id'] + '.png', modality='visual' if m['kind'] == 'visual' else 'table')
        desc[key] = dict(description='Qwen ' + m['id'])
    outputs, image_lists = {}, {}
    for mode in MODES:
        images = []
        outputs[mode] = node_representation(n, mode, assets, desc, images)
        image_lists[mode] = images
        members = outputs[mode]['members']
        assert [m['original_text'] for m in members[:2]] == ['Ordinary paragraph', 'Figure caption']
        assert len(members) == 4
        assert 'SECRET HTML' not in json.dumps(outputs[mode])
        assert 'Excluded footer' not in json.dumps(outputs[mode])
    assert image_lists == dict(description=[], raw=['v.png', 't.png'], mixed=['v.png', 't.png'])
    assert all('image_number' not in m and 'qwen_visual_description' in m
               for m in outputs['description']['members'][2:])
    assert all('qwen_visual_description' not in m and 'image_number' in m
               for m in outputs['raw']['members'][2:])
    assert outputs['mixed']['members'][2:] == [
        dict(member_id='v', kind='visual', qwen_visual_description='Qwen v', image_number=1),
        dict(member_id='t', kind='table', qwen_visual_description='Qwen t', image_number=2)]
    # Image numbering continues across both endpoints and cannot be assigned to the wrong node.
    images = []
    node_representation(n, 'mixed', assets, desc, images)
    second = node_representation(n, 'mixed', assets, desc, images)
    assert [m['image_number'] for m in second['members'][2:]] == [3, 4]
    assert 'known to be related' not in pair_prompt(dict(task_id='opaque'))


def prediction(relation, valid=True):
    return dict(task_id='opaque', valid=valid,
                semantic=dict(relation=relation, source_node_id=None, target_node_id=None),
                references=dict(exists=False, source_node_id=None, target_node_id=None))


def reference():
    return dict(task_id='opaque', suite_case_id='N01', semantic_status='PROVISIONAL_RESOLVED',
                allowed_semantic_readings=[dict(relation='REJECT_UNCERTAIN', source_node_id=None, target_node_id=None)],
                references=dict(exists=False, source_node_id=None, target_node_id=None))


def test_paired_report_excludes_missing_invalid_and_unresolved(tmp_path):
    ref = reference()
    jsonl(tmp_path / 'evaluation/reference.jsonl', [ref])
    for mode in MODES:
        jsonl(tmp_path / mode / 'evaluation/reference.jsonl', [ref])
    jsonl(tmp_path / 'description/predictions.jsonl', [prediction('REJECT_UNCERTAIN')])
    jsonl(tmp_path / 'raw/predictions.jsonl', [prediction('SUPPORTS', valid=False)])
    result = compare(tmp_path)
    assert not result['complete']
    assert result['metrics']['raw']['invalid'] == 1
    assert result['paired']['description_vs_raw'].get('joint_valid_resolved', 0) == 0
    jsonl(tmp_path / 'raw/predictions.jsonl', [prediction('SUPPORTS')])
    jsonl(tmp_path / 'mixed/predictions.jsonl', [prediction('REJECT_UNCERTAIN')])
    result = compare(tmp_path)
    assert result['complete']
    assert result['paired']['description_vs_raw']['only_description'] == 1
    assert result['paired']['description_vs_mixed']['both_correct'] == 1
    ref['semantic_status'] = 'UNRESOLVED'
    assert semantic_matches(prediction('SUPPORTS'), ref) is None
