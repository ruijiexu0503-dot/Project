"""CPU-only safety tests: no model download, embedding, or GPU inference."""
import copy
from contextlib import nullcontext
import fcntl
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_cached_query_reranker as reranker


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


@pytest.fixture
def inputs():
    return [{"id": "p1", "query": "压力是否降低？", "text": "Pressure did not decrease."},
            {"id": "p2", "query": "压力是否降低？", "text": "Pressure decreased in group B."}]


def scores_for(inputs):
    return [{"id": row["id"], "input_sha256": reranker.input_sha(row),
             "score": -2.5 + i, "original_tokens": 700 if i else 20, "truncated": bool(i)}
            for i, row in enumerate(inputs)]


@pytest.fixture
def model_dir(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"num_labels": 1}')
    (model / "tokenizer.json").write_text('{"version": "1.0"}')
    (model / "model.safetensors").write_bytes(b"fake weights; never loaded")
    return model


@pytest.fixture
def output_dir(tmp_path, inputs):
    out = tmp_path / "output"
    out.mkdir()
    write_rows(out / "reranker_inputs.jsonl", inputs)
    return out


def test_input_hash_canonical_and_only_inference_fields(inputs):
    row = inputs[0]
    reordered = {"text": row["text"], "query": row["query"], "id": row["id"], "gold": "ignored"}
    assert reranker.input_sha(row) == reranker.input_sha(reordered)
    for field in ("id", "query", "text"):
        changed = dict(row)
        changed[field] += " extra"
        assert reranker.input_sha(row) != reranker.input_sha(changed)


@pytest.mark.parametrize("field,value", [("id", ""), ("query", " \n "), ("text", None),
                                         ("id", 9), ("query", []), ("text", False)])
def test_load_inputs_rejects_invalid_fields(tmp_path, inputs, field, value):
    inputs[0][field] = value
    path = tmp_path / "rows.jsonl"
    write_rows(path, inputs)
    with pytest.raises(ValueError, match="nonempty string"):
        reranker.load_inputs(path)


def test_load_inputs_rejects_duplicates(tmp_path, inputs):
    path = tmp_path / "rows.jsonl"
    write_rows(path, [inputs[0], inputs[0]])
    with pytest.raises(ValueError, match="Duplicate"):
        reranker.load_inputs(path)


@pytest.mark.parametrize("content", ["\n", "[]\n", "not json\n", '{"id": "p1"}\n\n'])
def test_read_rows_rejects_corruption(tmp_path, content):
    path = tmp_path / "rows.jsonl"
    path.write_text(content)
    with pytest.raises(ValueError):
        reranker.read_rows(path)


def test_load_scores_resume_prefix_and_complete_validation(tmp_path, inputs):
    path = tmp_path / "scores.jsonl"
    assert reranker.load_scores(path, inputs) == []
    with pytest.raises(ValueError, match="Incomplete"):
        reranker.load_scores(path, inputs, require_complete=True)
    scores = scores_for(inputs)
    write_rows(path, scores[:1])
    assert reranker.load_scores(path, inputs) == scores[:1]
    with pytest.raises(ValueError, match="Incomplete"):
        reranker.load_scores(path, inputs, require_complete=True)
    write_rows(path, scores)
    assert reranker.load_scores(path, inputs, require_complete=True) == scores


@pytest.mark.parametrize("mutation", ["swapped", "duplicate", "extra", "hash", "query_changed", "id"])
def test_load_scores_rejects_wrong_binding(tmp_path, inputs, mutation):
    scores = scores_for(inputs)
    if mutation == "swapped":
        scores.reverse()
    elif mutation == "duplicate":
        scores[1] = dict(scores[0])
    elif mutation == "extra":
        scores.append(dict(scores[0]))
    elif mutation == "hash":
        scores[0]["input_sha256"] = "bad hash"
    elif mutation == "query_changed":
        inputs[0]["query"] += " changed"
    elif mutation == "id":
        scores[0]["id"] = "wrong"
    path = tmp_path / "scores.jsonl"
    write_rows(path, scores)
    with pytest.raises(ValueError):
        reranker.load_scores(path, inputs)


@pytest.mark.parametrize("field,value", [
    ("score", float("nan")), ("score", float("inf")), ("score", True), ("score", "1.0"),
    ("score", None), ("original_tokens", 0), ("original_tokens", -2), ("original_tokens", 2.5),
    ("original_tokens", True), ("truncated", 0), ("truncated", True),
])
def test_load_scores_rejects_bad_score_or_token_metadata(tmp_path, inputs, field, value):
    scores = scores_for(inputs)
    scores[0][field] = value
    path = tmp_path / "scores.jsonl"
    write_rows(path, scores)
    with pytest.raises(ValueError):
        reranker.load_scores(path, inputs)


def test_manifest_binds_input_settings_runner_and_model(output_dir, model_dir, inputs):
    manifest = reranker.prepare_manifest(output_dir, model_dir, inputs)
    assert manifest["input_count"] == 2
    assert manifest["inputs_sha256"] == reranker.sha(output_dir / "reranker_inputs.jsonl")
    assert manifest["runner_sha256"] == reranker.sha(Path(reranker.__file__))
    assert reranker.prepare_manifest(output_dir, model_dir, inputs) == manifest
    changed = copy.deepcopy(inputs)
    changed[0]["text"] += " changed"
    write_rows(output_dir / "reranker_inputs.jsonl", changed)
    with pytest.raises(ValueError, match="refusing resume"):
        reranker.prepare_manifest(output_dir, model_dir, changed)


@pytest.mark.parametrize("filename", ["reranker_scores.jsonl", "reranker_execution.json"])
def test_manifest_rejects_unbound_checkpoint(output_dir, model_dir, inputs, filename):
    (output_dir / filename).write_text("{}\n")
    with pytest.raises(ValueError, match="without manifest"):
        reranker.prepare_manifest(output_dir, model_dir, inputs)


@pytest.mark.parametrize("mutation", ["weights", "tokenizer", "inventory", "path"])
def test_model_identity_rejects_resume_changes(model_dir, tmp_path, mutation):
    identity = reranker.model_identity(model_dir)
    if mutation == "weights":
        (model_dir / "model.safetensors").write_bytes(b"different weights")
    elif mutation == "tokenizer":
        (model_dir / "tokenizer.json").write_text('{"version": "changed"}')
    elif mutation == "inventory":
        (model_dir / "added_tokens.json").write_text("{}")
    else:
        identity["path"] = str(tmp_path / "other-model")
    with pytest.raises(ValueError):
        reranker.model_identity(model_dir, identity)


def test_model_identity_cached_weights_but_rehashes_tokenizer(model_dir, monkeypatch):
    identity = reranker.model_identity(model_dir)
    actual_sha, calls = reranker.sha, []
    def track(path):
        calls.append(path.name)
        return actual_sha(path)
    monkeypatch.setattr(reranker, "sha", track)
    assert reranker.model_identity(model_dir, identity) == identity
    assert "model.safetensors" not in calls
    assert "config.json" in calls and "tokenizer.json" in calls


def test_validate_queries_is_preflight_and_deduplicates(inputs):
    calls = []
    def encode(query, **kwargs):
        calls.append((query, kwargs))
        return list(range(128))
    reranker.validate_queries(SimpleNamespace(encode=encode), inputs)
    assert calls == [(inputs[0]["query"], {"add_special_tokens": False, "truncation": False})]
    with pytest.raises(ValueError, match="query truncation is forbidden"):
        reranker.validate_queries(SimpleNamespace(encode=lambda *a, **k: list(range(129))), inputs)


class FakeEncoded(dict):
    def to(self, device):
        assert device == "cuda"
        return self


class FakeLogits:
    def __init__(self, values, shape=None):
        self.values = values
        self.shape = shape or (len(values), 1)

    def __getitem__(self, key):
        assert key == (slice(None), 0)
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.values


def batch_fakes(counts, values, shape=None):
    calls = []
    def tokenize(queries, texts, **kwargs):
        calls.append((queries, texts, kwargs))
        if not kwargs["truncation"]:
            return {"input_ids": [list(range(n)) for n in counts]}
        return FakeEncoded(input_ids=["stub"])
    model = lambda **kwargs: SimpleNamespace(logits=FakeLogits(values, shape))
    torch = SimpleNamespace(inference_mode=nullcontext)
    return tokenize, model, torch, calls


def test_infer_batch_only_truncates_passage_and_keeps_raw_logits(inputs):
    tokenize, model, torch, calls = batch_fakes([512, 513], [-6.0, 8.0])
    scores = reranker.infer_batch(model, tokenize, inputs, torch)
    assert [score["score"] for score in scores] == [-6.0, 8.0]
    assert [score["truncated"] for score in scores] == [False, True]
    assert [score["original_tokens"] for score in scores] == [512, 513]
    assert calls[1][2] == {"padding": True, "truncation": "only_second",
                           "max_length": 512, "return_tensors": "pt"}
    assert calls[0][0] == calls[1][0] == [row["query"] for row in inputs]
    assert [score["input_sha256"] for score in scores] == [reranker.input_sha(row) for row in inputs]


@pytest.mark.parametrize("counts,values,shape", [
    ([12], [1.0, 2.0], None), ([0, 12], [1.0, 2.0], None),
    ([12, 14], [1.0, float("nan")], None), ([12, 14], [1.0, 2.0], (2, 2)),
])
def test_infer_batch_rejects_malformed_outputs(inputs, counts, values, shape):
    tokenize, model, torch, _ = batch_fakes(counts, values, shape)
    with pytest.raises(ValueError):
        reranker.infer_batch(model, tokenize, inputs, torch)


def test_completed_checkpoint_exits_without_loading_torch(output_dir, model_dir, inputs, monkeypatch):
    reranker.prepare_manifest(output_dir, model_dir, inputs)
    write_rows(output_dir / "reranker_scores.jsonl", scores_for(inputs))
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "transformers", None)
    result = reranker.run(output_dir, model_dir)
    assert result["status"] == "already_complete" and result["complete"]
    assert result["scored"] == result["total"] == result["resumed_scores"] == 2
    assert result["scores_sha256"] == reranker.sha(output_dir / "reranker_scores.jsonl")
    assert result["document_embeddings_generated"] is False and result["edges_generated"] is False


def install_fake_runtime(monkeypatch, *, cuda=True, query_tokens=20):
    loads = []
    tokenizer = SimpleNamespace(encode=lambda *a, **k: list(range(query_tokens)))
    model = SimpleNamespace()
    model.to = lambda device: model
    model.eval = lambda: model
    def load_tokenizer(*args, **kwargs):
        loads.append("tokenizer")
        assert kwargs == {"local_files_only": True}
        return tokenizer
    def load_model(*args, **kwargs):
        loads.append("model")
        assert kwargs == {"local_files_only": True, "torch_dtype": "float16"}
        return model
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        __version__="cpu-test-stub", float16="float16",
        cuda=SimpleNamespace(is_available=lambda: cuda, get_device_name=lambda device: "fake GPU")))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=load_tokenizer),
        AutoModelForSequenceClassification=SimpleNamespace(from_pretrained=load_model)))
    return loads


def test_run_resumes_only_remaining_prefix_and_writes_complete_execution(
        output_dir, model_dir, inputs, monkeypatch):
    reranker.prepare_manifest(output_dir, model_dir, inputs)
    existing = scores_for(inputs)[:1]
    write_rows(output_dir / "reranker_scores.jsonl", existing)
    loads = install_fake_runtime(monkeypatch)
    batches = []
    def infer(model, tokenizer, batch, torch):
        batches.append(batch)
        return scores_for(batch)
    monkeypatch.setattr(reranker, "infer_batch", infer)
    result = reranker.run(output_dir, model_dir)
    assert batches == [inputs[1:]]
    assert loads == ["tokenizer", "model"]
    assert result["status"] == "complete" and result["complete"]
    assert result["resumed_scores"] == 1 and result["scored"] == 2
    scores = reranker.load_scores(output_dir / "reranker_scores.jsonl", inputs, require_complete=True)
    assert scores[0] == existing[0]
    assert json.loads((output_dir / "reranker_execution.json").read_text()) == result


def test_run_no_cuda_refuses_fallback_and_records_error(output_dir, model_dir, monkeypatch):
    loads = install_fake_runtime(monkeypatch, cuda=False)
    with pytest.raises(RuntimeError, match="CPU fallback is disabled"):
        reranker.run(output_dir, model_dir)
    assert loads == []
    result = json.loads((output_dir / "reranker_execution.json").read_text())
    assert result["status"] == "error" and result["scored"] == 0 and not result["complete"]
    assert not (output_dir / "reranker_scores.jsonl").exists()


def test_run_invalid_query_preflight_does_not_load_model_or_score(
        output_dir, model_dir, monkeypatch):
    loads = install_fake_runtime(monkeypatch, query_tokens=129)
    with pytest.raises(ValueError, match="query truncation is forbidden"):
        reranker.run(output_dir, model_dir)
    assert loads == ["tokenizer"]
    assert not (output_dir / "reranker_scores.jsonl").exists()


def test_run_inference_failure_preserves_previous_atomic_prefix(
        output_dir, model_dir, inputs, monkeypatch):
    reranker.prepare_manifest(output_dir, model_dir, inputs)
    original = scores_for(inputs)[:1]
    write_rows(output_dir / "reranker_scores.jsonl", original)
    install_fake_runtime(monkeypatch)
    def fail(*args):
        raise RuntimeError("simulated inference failure")
    monkeypatch.setattr(reranker, "infer_batch", fail)
    with pytest.raises(RuntimeError, match="simulated inference failure"):
        reranker.run(output_dir, model_dir)
    assert reranker.load_scores(output_dir / "reranker_scores.jsonl", inputs) == original
    result = json.loads((output_dir / "reranker_execution.json").read_text())
    assert result["status"] == "error" and result["scored"] == 1 and not result["complete"]


def test_concurrent_writer_refused(output_dir, model_dir):
    with (output_dir / ".reranker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="already writing"):
            reranker.run(output_dir, model_dir)


@pytest.mark.parametrize("minutes", [0, -1, float("nan"), float("inf")])
def test_invalid_time_budget_refused(output_dir, model_dir, minutes):
    with pytest.raises(ValueError, match="positive and finite"):
        reranker.run(output_dir, model_dir, minutes)


def test_failed_atomic_replace_keeps_existing_checkpoint(tmp_path, monkeypatch):
    path = tmp_path / "scores.jsonl"
    path.write_text("original\n")
    def fail_replace(*args):
        raise OSError("simulated failure")
    monkeypatch.setattr(reranker.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated failure"):
        reranker.atomic_write(path, "replacement\n")
    assert path.read_text() == "original\n"
    assert list(tmp_path.iterdir()) == [path]
