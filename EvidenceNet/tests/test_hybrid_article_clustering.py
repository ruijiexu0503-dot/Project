import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from evidence_graph.hybrid_article_clustering import (
    validate_page, validate_membership, validate_reading, validate_continuations, stable_id,
)
from run_hybrid_article_clustering import materialize, jsonl, rows, call


def page_fixture():
    page = dict(document_mode='multi_article', nodes=[dict(label='N001', type='TEXT'),
                 dict(label='N002', type='TEXT'), dict(label='N003', type='VISUAL')],
                titles=[dict(label='T001'), dict(label='T002'), dict(label='T003')])
    result = dict(groups=[dict(id='G1', kind='article', nodes=['N001', 'N003'], title_ids=['T001'],
                               flows=[dict(kind='body', nodes=['N001'])]),
                         dict(id='G2', kind='article', nodes=['N002'], title_ids=['T002'],
                               flows=[dict(kind='body', nodes=['N002'])])],
                  page_context_title_ids=['T003'], conflicted_nodes=[])
    return page, result


def test_page_clustering_retains_titles_visuals_and_separate_stories():
    page, value = page_fixture()
    assert validate_page(value, page) == value
    for change in ('missing_title', 'duplicate_node', 'cross_article_flow', 'visual_body'):
        bad = copy.deepcopy(value)
        if change == 'missing_title': bad['page_context_title_ids'] = []
        if change == 'duplicate_node': bad['groups'][1]['nodes'].append('N001')
        if change == 'cross_article_flow': bad['groups'][0]['flows'][0]['nodes'].append('N002')
        if change == 'visual_body': bad['groups'][0]['flows'][0]['nodes'].append('N003')
        with pytest.raises(ValueError): validate_page(bad, page)


def test_metadata_and_unresolved_ownership_are_explicit_not_silent_omissions():
    page, value = page_fixture()
    value['groups'][0]['nodes'].remove('N003')
    with pytest.raises(ValueError, match='missing=.*N003'):
        validate_page(value, page)
    value['unassigned_nodes'] = ['N003']
    assert validate_page(value, page)
    value['unassigned_nodes'] = []
    value['groups'].append(dict(id='META', kind='page_context', nodes=['N003'], title_ids=[], flows=[]))
    assert validate_page(value, page)


def continuation_fixture():
    payload = dict(page_number=2, reading_adjacency_verified=True,
        current=[dict(cluster_id='c', nodes=[dict(id='n2', text='The specific article continues.')], body_heads=['n2'])],
        previous=[dict(article_id='a', nodes=[dict(id='n1', text='An unfinished specific article.')],
                       page_number=1, body_tails=['n1'])])
    value = dict(decisions=[dict(cluster_id='c', decision='SAME_ARTICLE', previous_article_id='a',
        current_node_id='n2', current_quote='specific article continues', previous_node_id='n1',
        previous_quote='unfinished specific article', reading_link=None, reason='Narrative continuation')])
    return payload, value


def test_membership_does_not_imply_next_and_cannot_bridge_same_page_clusters():
    payload, value = continuation_fixture()
    assert validate_continuations(value, payload)['decisions'][0]['reading_link'] is None
    payload['current'].append(dict(payload['current'][0], cluster_id='c2'))
    value['decisions'].append(dict(value['decisions'][0], cluster_id='c2'))
    with pytest.raises(ValueError): validate_continuations(value, payload)


def test_cross_page_quotes_and_reading_provenance_are_required():
    payload, value = continuation_fixture()
    value['decisions'][0]['current_quote'] = 'The OTHER endpoint invented fact'
    with pytest.raises(ValueError): validate_continuations(value, payload)
    payload, value = continuation_fixture()
    value['decisions'][0]['reading_link'] = dict(source='n1', target='n2')
    assert validate_continuations(value, payload)
    payload['page_number'] = 3
    with pytest.raises(ValueError): validate_continuations(value, payload)
    payload['page_number'] = 2; payload['reading_adjacency_verified'] = False
    with pytest.raises(ValueError): validate_continuations(value, payload)


def test_materialized_articles_keep_node_members_and_titles_without_cross_page_next(tmp_path):
    pages, inputs = [], []
    for number, nid, text in [(1, 'n1', 'An unfinished specific article.'), (2, 'n2', 'The specific article continues.')]:
        member = dict(id='m', kind='atom', role='para', type='text', text=text)
        node = dict(id=nid, members=[member], eligible_members=[dict(kind='atom', member_id='m', eligible=True)])
        pid = 'p' + str(number)
        page = dict(page_id=pid, document='doc', page='page_000' + str(number), page_number=number,
                    task='doc/page_' + str(number), document_mode='multi_article', nodes=[node])
        payload = dict(document='doc', page=page['page'], document_mode='multi_article',
            nodes=[dict(label='N001', id=nid, type='TEXT')],
            titles=[dict(label='T001', id='TITLE::m', text='A specific story', bbox=[0, 0, 1, 1])])
        image = tmp_path / (pid + '.png'); image.write_bytes(b'fake image; model is stubbed')
        pages.append(page); inputs.append(dict(page_id=pid, payload=payload, task=page['task'],
            prompt='PAGE:\n' + json.dumps(payload), image=str(image), excluded_node_ids=[]))
    jsonl(tmp_path / 'pages.jsonl', pages); jsonl(tmp_path / 'page_inputs.jsonl', inputs)
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(files={})))

    class Model:
        def generate_raw_with_images(self, system, prompt, images, tokens):
            if prompt.startswith('PAGE:'):
                value = dict(groups=[dict(id='G1', kind='article', nodes=['N001'], title_ids=['T001'],
                             flows=[dict(kind='body', nodes=['N001'])])], page_context_title_ids=[], conflicted_nodes=[])
            elif prompt.startswith('Build reading flows'):
                membership = json.loads(prompt.split('FIXED_MEMBERSHIP:\n')[1])
                value = dict(groups=[dict(id=g['id'], flows=[dict(kind='body', nodes=g['nodes'])])
                                     for g in membership['groups']])
            else:
                p = json.loads(prompt.split('INPUT:\n')[1])
                value = dict(decisions=[dict(cluster_id=p['current'][0]['cluster_id'], decision='SAME_ARTICLE',
                    previous_article_id=p['previous'][0]['article_id'], current_node_id='n2',
                    current_quote='specific article continues', previous_node_id='n1', previous_quote='unfinished specific article',
                    reading_link=None, reason='Same narrative')])
            return SimpleNamespace(raw=json.dumps(value))
    result = materialize(tmp_path, Model())
    assert result['complete'] and result['nodes'] == 2 and result['assigned_titles'] == 2
    assignments = rows(tmp_path / 'article_assignments.jsonl')
    assert len({r['article_id'] for r in assignments}) == 1
    assert {r['assignment_status'] for r in assignments} == {'QWEN_CROSS_PAGE_LINKED'}
    assert rows(tmp_path / 'reading_edges.jsonl') == []
    assert len({r['title_id'] for r in rows(tmp_path / 'title_assignments.jsonl')}) == 2
    for n, original in zip(rows(tmp_path / 'units.jsonl'), pages):
        assert n['members'] == original['nodes'][0]['members']


def test_integrated_document_entrypoint_runs_articles_after_all_node_batches(tmp_path, monkeypatch):
    import run_vldocir_nodes as driver
    import run_hybrid_article_clustering as articles
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(batches=[['a'], ['b']])))
    calls = []
    monkeypatch.setattr(driver.subprocess, 'run', lambda cmd, check: calls.append(cmd[2]))
    def fake_run(args):
        assert calls == ['describe', 'candidates', 'decide', 'assemble'] * 2
        assert args.nodes == tmp_path / 'nodes'
        calls.append('articles')
        return dict(complete=True)
    monkeypatch.setattr(articles, 'run', fake_run)
    monkeypatch.setattr(sys, 'argv', ['driver', 'document', '--source', str(tmp_path), '--output', str(tmp_path / 'nodes')])
    driver.main()
    assert calls[-1] == 'articles'


def test_membership_survives_bad_flows_but_never_missing_paragraphs():
    page, value = page_fixture()
    # Regression: a flow names a node belonging to another article. Membership is valid.
    value['groups'][0]['flows'][0]['nodes'].append('N002')
    with pytest.raises(ValueError, match='flow outside group'):
        validate_page(value, page)
    membership = validate_membership(value, page)
    assert all(g['flows'] == [] for g in membership['groups'])
    assert value['groups'][0]['flows'][0]['nodes'] == ['N001', 'N002']  # Raw proposal is retained.
    # Regression: omitting N011-like substantive content still fails, never autoassigns it.
    value['groups'][1]['nodes'] = ['N003']
    with pytest.raises(ValueError, match='missing=.*N002'):
        validate_membership(value, page)


def test_reading_cannot_reassign_nodes_or_mutate_fixed_membership():
    page, original = page_fixture()
    membership = validate_membership(original, page)
    output = dict(groups=[dict(id='G1', flows=[dict(kind='body', nodes=['N001'])]),
                          dict(id='G2', flows=[dict(kind='body', nodes=['N002'])])])
    result = validate_reading(output, page, membership)
    assert result['groups'][0]['nodes'] == ['N001', 'N003']
    assert membership['groups'][0]['flows'] == []
    bad = copy.deepcopy(output); bad['groups'][0]['flows'][0]['nodes'].append('N002')
    with pytest.raises(ValueError, match='flow outside group'):
        validate_reading(bad, page, membership)
    bad = copy.deepcopy(output); bad['groups'][0]['nodes'] = ['N002']
    with pytest.raises(ValueError, match='membership is immutable'):
        validate_reading(bad, page, membership)


def test_retry_sees_previous_response_and_exact_missing_labels(tmp_path):
    page, result = page_fixture()
    missing = copy.deepcopy(result); missing['groups'].pop()
    requests = []
    class Model:
        def generate_raw_with_images(self, system, prompt, images, tokens):
            requests.append(prompt)
            return SimpleNamespace(raw=json.dumps(missing if len(requests) == 1 else result))
    record = call(Model(), tmp_path / 'decision.json', 'Membership task', [],
                  lambda v: validate_membership(v, page), 1000)
    assert record['valid'] and len(record['attempts']) == 2
    assert json.dumps(missing) in requests[1]
    assert "missing=['N002']" in requests[1]
    assert all(g['flows'] == [] for g in record['value']['groups'])


def test_reading_failure_keeps_valid_articles_but_reports_reading_not_ready(tmp_path):
    member = dict(id='m', kind='atom', role='para', type='text', text='Substantive paragraph.')
    node = dict(id='n', members=[member], eligible_members=[dict(kind='atom', member_id='m', eligible=True)])
    page = dict(page_id='p', document='doc', page='page_0001', page_number=1,
                task='doc/page_0001', document_mode='multi_article', nodes=[node])
    payload = dict(document_mode='multi_article', nodes=[dict(label='N001', id='n', type='TEXT')], titles=[])
    image = tmp_path / 'p.png'; image.write_bytes(b'stubbed')
    jsonl(tmp_path / 'pages.jsonl', [page])
    jsonl(tmp_path / 'page_inputs.jsonl', [dict(page_id='p', payload=payload, prompt='MEMBERSHIP',
                                              image=str(image), excluded_node_ids=[])])
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(files={})))
    class Model:
        def generate_raw_with_images(self, system, prompt, images, tokens):
            if prompt.startswith('MEMBERSHIP'):
                value = dict(groups=[dict(id='G1', kind='article', nodes=['N001'], title_ids=[], flows=[])],
                             page_context_title_ids=[], conflicted_nodes=[], unassigned_nodes=[])
            else:
                value = dict(groups=[dict(id='G1', flows=[dict(kind='body', nodes=['N_OTHER'])])])
            return SimpleNamespace(raw=json.dumps(value))
    result = materialize(tmp_path, Model())
    assert result['complete'] and result['article_membership_complete']
    assert not result['reading_complete'] and result['reading_failures']
    assert rows(tmp_path / 'article_assignments.jsonl')[0]['article_id']
    assert not rows(tmp_path / 'reading_edges.jsonl')
    manifest = json.loads((tmp_path / 'article_graph_manifest.json').read_text())
    assert manifest['ready_for_downstream'] and not manifest['reading_ready']
