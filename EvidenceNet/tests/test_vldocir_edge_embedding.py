import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_vldocir_edge_embedding as experiment


def test_global_candidates_scan_duplicates_without_degree_bonus():
    direct = [("dense", str(i)) for i in range(1, 31)]
    graph = []
    for i in range(12):
        # Highest scoring edges repeat the core; later edges must still be scanned.
        a = direct[i % 10]
        b = ("new", str(i)) if i >= 3 else direct[(i + 1) % 10]
        graph.append({"edge_id": f"e{i:02d}", "endpoints": {
            "A": {"document_id": a[0], "page_number": a[1]},
            "B": {"document_id": b[0], "page_number": b[1]},
        }})
    selected, paths = experiment._global_candidates(direct, graph, np.arange(12, 0, -1))
    assert len(selected) == len(set(selected)) == experiment.BUDGET
    assert selected[:experiment.CORE] == direct[:experiment.CORE]
    assert ("new", "3") in selected
    assert any(endpoint["decision"] == "already_selected" for p in paths for endpoint in p["endpoints"])


def test_prepare_real_frozen_graph_has_187_semantic_edges(tmp_path):
    out = tmp_path / "prepared"
    result = experiment.prepare(out, experiment.MODEL)
    assert result == {"prepared": True, "edges": 187, "queries": 24}
    edges = [json.loads(line) for line in (out / "edge_records.jsonl").read_text().splitlines()]
    assert len({e["edge_id"] for e in edges}) == 187
    assert {e["source_route"] for e in edges} == {"semantic"}
    assert all(e["endpoints"][s]["spans"] for e in edges for s in ("A", "B"))
    experiment.check_prepared(out)


def test_pair_and_relation_inputs_share_identical_endpoint_text(tmp_path):
    out = tmp_path / "prepared"
    experiment.prepare(out, experiment.MODEL, edge_limit=3)
    edges = [json.loads(line) for line in (out / "edge_records.jsonl").read_text().splitlines()]
    predictions = []
    for edge in edges:
        ids = [edge["endpoints"][s]["spans"][0]["span_id"] for s in ("A", "B")]
        result = {"description": "The endpoints state a bounded connection.",
                  "cited_span_ids": ids, "limitations": "Keep endpoint scope.",
                  "status": "DESCRIBED"}
        predictions.append({"edge_id": edge["edge_id"], "input_sha256": edge["input_sha256"],
                            "valid": True, "result": result, "attempts": []})
    experiment.jsonl(out / "description_predictions.jsonl", predictions)

    class Tokenizer:
        def encode(self, text, **unused): return text.split()
        def decode(self, ids, **unused): return " ".join(ids)

    pair, relation, endpoints = experiment._encoding_rows(out, Tokenizer())
    assert len(pair) == len(relation) == 6 and len(endpoints) == 6
    assert [r["endpoint_text_sha256"] for r in pair] == [r["endpoint_text_sha256"] for r in relation]
    assert all("[RELATION]" not in p["text"] for p in pair)
    assert all("[RELATION]" in r["text"] for r in relation)


def _bounded_fixture(tmp_path, result, *, valid=True):
    import bounded_edge_descriptions as bounded
    from test_edge_embedding_records import fixture
    import edge_embedding_records as records
    edge, nodes = fixture()
    record = records.build_record(edge, nodes, 'semantic')
    experiment.write(tmp_path / 'protocol.json', {'description': {'policy': bounded.PROFILE}})
    experiment.jsonl(tmp_path / 'edge_records.jsonl', [record])
    experiment.jsonl(tmp_path / 'description_predictions.jsonl', [{
        'edge_id': record['edge_id'], 'input_sha256': record['input_sha256'],
        'description_policy': bounded.PROFILE,
        'prompt_sha256': records.digest(bounded.make_description_prompt(record)),
        'valid': valid, 'result': result, 'attempts': []}])
    return record


class WordTokenizer:
    def encode(self, text, **unused): return text.split()
    def decode(self, ids, **unused): return ' '.join(ids)


def test_bounded_fallback_and_insufficient_are_exact_pair(tmp_path):
    for status in ('invalid', 'insufficient'):
        out = tmp_path / status
        result = None if status == 'invalid' else {
            'description': '', 'cited_span_ids': [], 'limitations': 'Different entities; identity unproven.',
            'status': 'INSUFFICIENT'}
        _bounded_fixture(out, result, valid=status != 'invalid')
        pair, relation, endpoints = experiment._encoding_rows(out, WordTokenizer())
        assert [r['text'] for r in pair] == [r['text'] for r in relation]
        assert not any(r['relation_appended'] for r in relation)
        assert len(endpoints) == 2


def test_bounded_retains_complete_limits_and_rejects_overflow(tmp_path):
    import pytest
    result = {'description': 'A: Alpha increases.\nB: Beta is lower.\nConnection: Both report a value.',
              'cited_span_ids': ['e1:A:S000', 'e1:B:S000'],
              'limitations': 'Different entities and years; no shared study identity is established.',
              'status': 'DESCRIBED'}
    _bounded_fixture(tmp_path, result)
    pair, relation, endpoints = experiment._encoding_rows(tmp_path, WordTokenizer())
    assert all(result['limitations'] in r['text'] for r in relation)
    assert all(result['description'] in r['text'] for r in relation)
    assert [r['endpoint_text_sha256'] for r in pair] == [r['endpoint_text_sha256'] for r in relation]
    assert not any(r['relation_token_meta']['truncated'] for r in relation)
    # A tokenizer whose tokens are finer than words simulates a compact but oversized output.
    result['limitations'] = 'Scope remains different.'
    class FineTokenizer(WordTokenizer):
        def encode(self, text, **unused): return list(text)
        def decode(self, ids, **unused): return ''.join(ids)
    result['description'] = 'A: ' + 'x' * 240 + '.\nB: ' + 'y' * 240 + '.\nConnection: Shared method.'
    _bounded_fixture(tmp_path, result)
    with pytest.raises(ValueError, match='(?i)(budget|token|512)'):
        experiment._encoding_rows(tmp_path, FineTokenizer())


def test_bounded_rejects_legacy_checkpoint(tmp_path):
    import pytest
    _bounded_fixture(tmp_path, None, valid=False)
    path = tmp_path / 'description_predictions.jsonl'
    prediction = experiment.rows(path)[0]
    prediction.pop('description_policy')
    experiment.jsonl(path, [prediction])
    with pytest.raises(ValueError, match='stale description'):
        experiment._encoding_rows(tmp_path, WordTokenizer())


def test_bounded_prepare_freezes_contract_and_code(tmp_path):
    import bounded_edge_descriptions as bounded
    out = tmp_path / 'bounded'
    experiment.prepare(out, experiment.MODEL, edge_limit=1, description_policy=bounded.PROFILE)
    protocol = experiment.read(out / 'protocol.json')
    assert protocol['description']['policy'] == bounded.PROFILE
    assert 'bounded_edge_descriptions.py' in experiment.read(out / 'manifest.json')['code']
    assert protocol['embedding']['max_length'] == 512
    assert protocol['embedding']['endpoint_tokens'] == 192
    assert protocol['candidate_policy'] == {'dense_core': 10, 'page_budget': 20, 'max_edges_scanned': 100}
    experiment.check_prepared(out)


def test_bounded_rejects_duplicate_or_stale_predictions(tmp_path):
    import pytest
    _bounded_fixture(tmp_path, None, valid=False)
    path = tmp_path / 'description_predictions.jsonl'
    row = experiment.rows(path)[0]
    experiment.jsonl(path, [row, row])
    with pytest.raises(ValueError, match='duplicate description'):
        experiment._encoding_rows(tmp_path, WordTokenizer())
    row['input_sha256'] = 'wrong'
    experiment.jsonl(path, [row])
    with pytest.raises(ValueError, match='stale description input'):
        experiment._encoding_rows(tmp_path, WordTokenizer())


def test_bounded_checks_model_metadata_and_model_choice(tmp_path):
    import pytest
    import shutil
    import bounded_edge_descriptions as bounded
    model = tmp_path / 'model'
    model.mkdir()
    for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json'):
        if (experiment.MODEL / name).is_file():
            shutil.copyfile(experiment.MODEL / name, model / name)
    out = tmp_path / 'prepared'
    experiment.prepare(out, model, edge_limit=1, description_policy=bounded.PROFILE)
    with pytest.raises(ValueError, match='differs from frozen'):
        experiment.embed(out, tmp_path / 'wrong-model', 'cpu')
    with (model / 'config.json').open('a') as handle:
        handle.write('\n')
    with pytest.raises(ValueError, match='changed embedding model metadata'):
        experiment.check_prepared(out)


def test_embedding_manifest_rejects_rewritten_description(tmp_path):
    import pytest
    experiment.jsonl(tmp_path / 'description_predictions.jsonl', [{'valid': False}])
    experiment.write(tmp_path / 'embedding_manifest.json', {'description_predictions_sha256': 'wrong'})
    with pytest.raises(ValueError, match='changed description predictions'):
        experiment.check_embeddings(tmp_path)
