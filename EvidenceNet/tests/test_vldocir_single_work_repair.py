import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import repair_vldocir_single_work_reading as repair
from evidence_graph import hybrid_article_clustering as schema
import run_hybrid_article_clustering as article


def source_fixture(tmp_path, member_valid=False, flow_valid=False):
    root = tmp_path / 'source'; root.mkdir()
    image = root / 'page.png'; image.write_bytes(b'stubbed model image')
    member = dict(id='m1', kind='atom', role='para', type='text', text='Original substantive paragraph.')
    node = dict(id='doc_node1', members=[member], eligible_members=[dict(kind='atom', member_id='m1', eligible=True)])
    page = dict(page_id='PAGE_1', document='doc', page='page_0001', page_number=1, task='doc/page_0001',
                document_mode='single_article', nodes=[node], image='page.png')
    payload = dict(document='doc', page='page_0001', document_mode='single_article',
        nodes=[dict(label='N001', id='doc_node1', type='TEXT', members=[member])],
        titles=[dict(label='T001', id='t1', text='Section', bbox=[0, 0, 1, 1]),
                dict(label='T002', id='t2', text='Next section', bbox=[0, 1, 1, 2])])
    inp = dict(page_id='PAGE_1', task='doc/page_0001', payload=payload, image=str(image),
               prompt=schema.page_prompt(payload), excluded_node_ids=[])
    article.jsonl(root / 'pages.jsonl', [page]); article.jsonl(root / 'page_inputs.jsonl', [inp])
    article.write(root / 'protocol.json', {'test': True}); article.write(root / 'manifest.json', {'files': {}})
    value = dict(groups=[dict(id='G1', kind='article', title_ids=['T001'], nodes=['N001'], flows=[])],
                 page_context_title_ids=['T002'], unassigned_nodes=[], conflicted_nodes=[], reason='One known work.')
    record = dict(input_sha256=repair.fingerprint(inp['prompt'], [image]), valid=member_valid,
                  value=value if member_valid else None, attempts=[dict(raw='old failed output', valid=member_valid)])
    article.write(root / 'page_decisions/PAGE_1.json', record)
    if flow_valid:
        merged = copy.deepcopy(value); merged['groups'][0]['flows'] = [dict(kind='body', nodes=['N001'])]
        article.write(root / 'reading_decisions/PAGE_1.json', dict(
            input_sha256=repair.fingerprint(schema.reading_prompt(payload, value), [image]),
            valid=True, value=merged, attempts=[dict(valid=True, raw='old flow')]))
    return root, payload, value


class StubModel:
    def __init__(self, membership, omit_title_once=False):
        self.membership = membership; self.prompts = []; self.omit_title_once = omit_title_once

    def generate_raw_with_images(self, system, prompt, images, tokens):
        self.prompts.append(prompt)
        if prompt.startswith('Build reading flows'):
            value = {'groups': [{'id': 'G1', 'flows': [{'kind': 'body', 'nodes': ['N001']}]}]}
        else:
            value = copy.deepcopy(self.membership)
            if self.omit_title_once and len(self.prompts) == 1:
                value['page_context_title_ids'] = []
        return SimpleNamespace(raw=json.dumps(value))


def test_failed_source_is_preserved_repaired_with_same_nodes(tmp_path):
    source, payload, value = source_fixture(tmp_path)
    old = (source / 'page_decisions/PAGE_1.json').read_bytes()
    out = tmp_path / 'repair'
    repair.prepare(source, out, page_id='PAGE_1')
    assert not (out / 'page_decisions/PAGE_1.json').exists()
    assert (out / 'provenance/original/page_decisions/PAGE_1.json').read_bytes() == old
    prepared = article.rows(out / 'page_inputs.jsonl')[0]
    assert prepared['payload'] == payload
    assert prepared['prompt'].startswith('Assign membership on this page of ONE KNOWN WORK')
    model = StubModel(value)
    result = repair.run_with_model(out, model, max_new_calls=6)
    assert result['complete'] and result['smoke_only'] and len(model.prompts) == 2
    assert (source / 'page_decisions/PAGE_1.json').read_bytes() == old
    assert article.rows(out / 'units.jsonl')[0]['members'] == article.rows(source / 'pages.jsonl')[0]['nodes'][0]['members']


def test_reuses_only_valid_exact_membership_and_merged_flow(tmp_path):
    source, payload, value = source_fixture(tmp_path, member_valid=True, flow_valid=True)
    out = tmp_path / 'repair'; protocol = repair.prepare(source, out)
    assert len(protocol['reused']) == 2
    assert article.rows(out / 'page_inputs.jsonl')[0]['prompt'] == article.rows(source / 'page_inputs.jsonl')[0]['prompt']
    model = StubModel(value)
    assert repair.run_with_model(out, model)['complete']
    assert model.prompts == []


def test_stale_or_membership_mutating_cache_is_not_reused(tmp_path):
    source, payload, value = source_fixture(tmp_path, member_valid=True, flow_valid=True)
    path = source / 'reading_decisions/PAGE_1.json'; cached = article.read(path)
    cached['value']['reason'] = 'changed membership metadata'
    article.write(path, cached)
    with pytest.raises(ValueError, match='changed fixed membership'):
        repair.prepare(source, tmp_path / 'repair')


def test_feedback_names_missing_titles_and_retry_does_not_drop_content(tmp_path):
    source, payload, value = source_fixture(tmp_path)
    out = tmp_path / 'repair'; repair.prepare(source, out)
    model = StubModel(value, omit_title_once=True)
    assert repair.run_with_model(out, model)['complete']
    assert '"missing_titles": ["T002"]' in model.prompts[1]
    assert '"missing_nodes": []' in model.prompts[1]
    assert len(article.read(out / 'page_decisions/PAGE_1.json')['attempts']) == 2


def test_budget_retains_membership_and_resumes_only_missing_reading(tmp_path):
    source, payload, value = source_fixture(tmp_path)
    out = tmp_path / 'repair'; repair.prepare(source, out)
    first = StubModel(value)
    assert not repair.run_with_model(out, first, max_new_calls=1)['complete']
    assert article.read(out / 'page_decisions/PAGE_1.json')['valid']
    second = StubModel(value)
    assert repair.run_with_model(out, second, max_new_calls=1)['complete']
    assert len(second.prompts) == 1 and second.prompts[0].startswith('Build reading flows')


def test_retry_invalid_requires_flag_and_keeps_failure_history(tmp_path):
    source, payload, value = source_fixture(tmp_path)
    out = tmp_path / 'repair'; repair.prepare(source, out)
    bad = copy.deepcopy(value); bad['groups'][0]['kind'] = 'standalone'
    assert not repair.run_with_model(out, StubModel(bad))['complete']
    failed = (out / 'page_decisions/PAGE_1.json').read_bytes()
    unused = StubModel(value)
    assert not repair.run_with_model(out, unused)['complete'] and unused.prompts == []
    assert repair.run_with_model(out, StubModel(value), retry_invalid=True)['complete']
    archived = list((out / 'retry_history/page_decisions').glob('*.json'))
    assert len(archived) == 1 and archived[0].read_bytes() == failed


def test_repair_preserves_strict_validator_and_source_freeze(tmp_path):
    source, payload, value = source_fixture(tmp_path)
    out = tmp_path / 'repair'; repair.prepare(source, out)
    bad = copy.deepcopy(value); bad['groups'][0]['nodes'] = []
    with pytest.raises(ValueError, match='node ownership'):
        schema.validate_membership(bad, payload)
    with pytest.raises(ValueError, match='fresh'):
        repair.prepare(source, out)
    image = next((out / 'assets').iterdir()); image.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed recovery input'):
        repair.verify(out)


def test_unknown_page_and_non_single_work_are_rejected(tmp_path):
    source, payload, value = source_fixture(tmp_path)
    with pytest.raises(ValueError, match='known optional page'):
        repair.prepare(source, tmp_path / 'unknown', page_id='not-a-page')
    payload['document_mode'] = 'multi_article'
    with pytest.raises(ValueError, match='explicit single_article'):
        repair.dedicated_prompt(payload)
