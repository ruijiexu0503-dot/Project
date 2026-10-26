import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_edge_repair_review as review


def fixture_inputs(tmp_path, routes=('reference_review', 'administrative_review', 'semantic')):
    nodes = [{'id': 'a', 'document': 'article-A', 'page': 3, 'node_type': 'TEXT'},
             {'id': 'b', 'document': 'article-B', 'page': 8, 'node_type': 'TEXT'}]
    ids = list(review.FOCUS_NOTES)[:len(routes)]
    edges, audits = [], []
    for edge_id, route in zip(ids, routes):
        edges.append({'task_id': edge_id, 'source': 'a', 'target': 'b',
                      'edge_type': 'RELATED', 'direction': 'UNDIRECTED',
                      'evidence_propagation_allowed': False,
                      'model_result': {'matched_claim': '<script>alert("claim")</script>',
                                       'shared_identity': {'canonical_name': '<bad & name>'},
                                       'reason': 'A reason', 'limitation': 'A limitation',
                                       'anchors': {
                                           'A': [{'kind': 'ORIGINAL_TEXT', 'quote': 'line one\nline two <script>bad</script>'}],
                                           'B': [{'kind': 'QWEN_VISUAL_DESCRIPTION_AND_ORIGINAL_CROP',
                                                  'quote': '<img src=x onerror=bad>'}]}}})
        audits.append({'edge_id': edge_id, 'route': route,
                       'endpoints': {'source': {'node_id': 'a', 'role': 'body', 'route': 'semantic'},
                                     'target': {'node_id': 'b', 'role': 'body', 'route': 'semantic'}}})
    edges_path, nodes_path, audit_path = (tmp_path / name for name in ('edges.jsonl', 'nodes.jsonl', 'audit.json'))
    for path, records in ((edges_path, edges), (nodes_path, nodes)):
        path.write_text(''.join(json.dumps(record) + '\n' for record in records))
    audit_path.write_text(json.dumps({'edge_audits': audits}))
    return edges_path, nodes_path, audit_path


def test_build_preserves_source_and_distinguishes_routes_anchors_and_model_claims(tmp_path):
    paths = fixture_inputs(tmp_path)
    before = {path: path.read_bytes() for path in paths}
    output = tmp_path / 'review'
    summary = review.build(*paths, output)
    rendered = (output / 'index.html').read_text()
    assert summary['routes'] == {'reference_review': 1, 'administrative_review': 1, 'semantic': 1}
    assert summary['edges'] == 3 and len(summary['focus_ids']) == 3
    assert summary['source_graph_modified'] is False
    assert summary['new_model_inference'] is False
    assert summary['html_sha256'] == hashlib.sha256((output / 'index.html').read_bytes()).hexdigest()
    assert json.loads((output / 'summary.json').read_text()) == summary
    assert before == {path: path.read_bytes() for path in paths}
    for kind, path in zip(('edges', 'nodes', 'audit'), paths):
        assert summary['inputs'][kind]['sha256'] == hashlib.sha256(before[path]).hexdigest()
    for route in review.ROUTES:
        assert f'data-route="{route}"' in rendered
    assert 'article-A' in rendered and 'article-B' in rendered
    assert 'ORIGINAL_TEXT' in rendered and 'QWEN_VISUAL_DESCRIPTION_AND_ORIGINAL_CROP' in rendered
    assert '生成描述：不等于原始文字证据' in rendered
    assert 'line one\nline two' in rendered
    assert '<script>alert' not in rendered and '<img src=x' not in rendered
    assert '&lt;script&gt;alert' in rendered and '&lt;img src=x' in rendered
    assert '&lt;bad &amp; name&gt;' in rendered
    assert 'matched_claim' in rendered and 'shared_identity' in rendered
    assert '不是自动金标' in rendered and 'RELATED ≠' in rendered
    assert 'obtained or waived' in rendered
    assert 'no competing interests' in rendered and 'no financial support was received' in rendered


def test_existing_output_is_not_overwritten(tmp_path):
    paths = fixture_inputs(tmp_path)
    output = tmp_path / 'review'
    output.mkdir()
    marker = output / 'existing.txt'
    marker.write_text('keep this')
    with pytest.raises(ValueError, match='Fresh output'):
        review.build(*paths, output)
    assert marker.read_text() == 'keep this'


@pytest.mark.parametrize('mismatch', ['id', 'endpoint', 'route', 'duplicate'])
def test_mismatched_audit_is_rejected_before_output_creation(tmp_path, mismatch):
    paths = fixture_inputs(tmp_path, ('semantic',))
    audit = json.loads(paths[2].read_text())
    if mismatch == 'id':
        audit['edge_audits'][0]['edge_id'] = 'another edge'
    elif mismatch == 'endpoint':
        audit['edge_audits'][0]['endpoints']['source']['node_id'] = 'another node'
    elif mismatch == 'route':
        audit['edge_audits'][0]['route'] = 'unknown_route'
    else:
        audit['edge_audits'].append(audit['edge_audits'][0])
    paths[2].write_text(json.dumps(audit))
    output = tmp_path / 'review'
    with pytest.raises(ValueError):
        review.build(*paths, output)
    assert not output.exists()


def test_unknown_anchor_kind_is_not_silently_presented_as_original():
    rendered = review.anchor_html({'kind': 'UNVERIFIED_TEXT', 'quote': 'a statement'})
    assert '其他 anchor' in rendered
    assert '原始文本／表格 anchor' not in rendered


def test_missing_anchors_are_not_invented_from_reason():
    edge = {'source': 'a', 'model_result': {'reason': 'Not a source quote'}}
    rendered = review.endpoint_html(edge, 'A', {'a': {'document': 'doc', 'page': 1}}, {})
    assert '未记录 anchor' in rendered
    assert 'Not a source quote' not in rendered
