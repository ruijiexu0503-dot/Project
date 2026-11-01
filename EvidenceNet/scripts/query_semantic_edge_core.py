#!/usr/bin/env python3
"""Shared correctness helpers for query-conditioned semantic-edge experiments."""
from __future__ import annotations

import collections.abc
import copy
import hashlib
import json
from pathlib import Path

import edge_embedding_records as edge_records


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sequence_length(value) -> int:
    """Return the model sequence length for tensor/list token containers.

    Hugging Face may return a list, a nested batch, a numpy array, a tensor, or
    a BatchEncoding.  ``len(BatchEncoding)`` counts fields, not tokens.
    """
    shape = getattr(value, "shape", None)
    if shape is not None:
        dims = tuple(int(x) for x in shape)
        if not dims:
            return 1
        return dims[-1]
    if isinstance(value, (list, tuple)):
        if not value:
            return 0
        if isinstance(value[0], (list, tuple)) or getattr(value[0], "shape", None) is not None:
            lengths = [_sequence_length(row) for row in value]
            if len(set(lengths)) > 1:
                raise ValueError("ragged token batch must be padded before counting")
            return lengths[0]
        return len(value)
    try:
        return len(value)
    except TypeError as exc:
        raise TypeError(f"unsupported token container: {type(value).__name__}") from exc


def token_count(encoded) -> int:
    """Count input IDs, never Mapping fields or attention-mask entries."""
    if isinstance(encoded, collections.abc.Mapping):
        if "input_ids" not in encoded:
            raise ValueError("tokenized mapping has no input_ids")
        encoded = encoded["input_ids"]
    return _sequence_length(encoded)


def chat_prompt_token_count(tokenizer, messages: list[dict], **template_options) -> int:
    """Count the exact rendered text prompt used by text-only generation."""
    rendered = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **template_options)
    if callable(tokenizer):
        encoded = tokenizer([rendered], padding=True, return_tensors="pt")
    else:  # small deterministic tokenizers used by unit tests
        encoded = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, **template_options)
    return token_count(encoded)


def generate_raw_text(llm, system: str, prompt: str, max_new_tokens: int):
    """Use the same text-only render/tokenize path counted by the Broker.

    Test doubles and older providers keep their existing raw generation method.
    """
    if not all(hasattr(llm, name) for name in ("tokenizer", "model", "enable_thinking")):
        return llm.generate_raw_with_images(system, prompt, [], max_new_tokens).raw
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    rendered = llm.tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=llm.enable_thinking)
    inputs = llm.tokenizer([rendered], padding=True, return_tensors="pt")
    prompt_length = inputs["input_ids"].shape[1]
    inputs = {name: tensor.to(llm.model.device) for name, tensor in inputs.items()}
    generated = llm.model.generate(**inputs, max_new_tokens=max_new_tokens,
                                   do_sample=False, repetition_penalty=1.05)
    return llm.tokenizer.batch_decode(
        generated[:, prompt_length:], skip_special_tokens=True)[0].strip()


def load_described_edges(records_path: Path, predictions_path: Path) -> tuple[list[dict], dict]:
    """Attach legacy descriptions after strict ID/input/source validation.

    The historical legacy prediction rows did not persist a prompt hash.  We
    therefore compute and freeze the prompt hash from the immutable edge record
    and explicitly report that provenance instead of pretending it was checked
    against a field that never existed.
    """
    records = [json.loads(x) for x in records_path.read_text().splitlines() if x.strip()]
    predictions = [json.loads(x) for x in predictions_path.read_text().splitlines() if x.strip()]
    by_record = {row.get("edge_id"): row for row in records}
    by_prediction = {row.get("edge_id"): row for row in predictions}
    if None in by_record or len(by_record) != len(records):
        raise ValueError("duplicate or missing edge record ID")
    if None in by_prediction or len(by_prediction) != len(predictions):
        raise ValueError("duplicate or missing description prediction ID")
    if set(by_record) != set(by_prediction):
        missing = sorted(set(by_record) - set(by_prediction))[:5]
        extra = sorted(set(by_prediction) - set(by_record))[:5]
        raise ValueError(f"description coverage mismatch: missing={missing}, extra={extra}")

    described, insufficient, fallback = 0, 0, 0
    output = []
    for edge_id in sorted(by_record):
        record = by_record[edge_id]
        prediction = by_prediction[edge_id]
        expected_input = edge_records.digest({k: record[k] for k in (
            "edge_id", "source_node_id", "target_node_id", "graph_version", "source_route",
            "endpoints", "representation_mode")})
        if record.get("input_sha256") != expected_input:
            raise ValueError(f"edge record input hash mismatch: {edge_id}")
        if prediction.get("input_sha256") != record.get("input_sha256"):
            raise ValueError(f"stale description input: {edge_id}")
        result = prediction.get("result") if prediction.get("valid") is True else None
        if result is not None:
            result = edge_records.validate_description(result, record)
        attached = edge_records.attach_description(record, result)
        status = attached["relation_description"]["status"]
        described += status == "DESCRIBED"
        insufficient += status == "INSUFFICIENT"
        fallback += status == "FALLBACK_PAIR"
        prompt_sha = edge_records.digest(edge_records.make_description_prompt(record))
        attached["description_metadata"] = {
            "profile": "legacy_open_description_v1",
            "input_sha256": record["input_sha256"],
            "prompt_sha256": prompt_sha,
            "prompt_hash_provenance": "recomputed_from_frozen_record; historical prediction omitted this field",
            "prediction_valid": prediction.get("valid") is True,
            "semantic_truth_verified": False,
        }
        # Verify every stored span against its own immutable offsets/hash shape.
        for endpoint in attached["endpoints"].values():
            for span in endpoint["spans"]:
                if span["char_end"] - span["char_start"] != len(span["text"]):
                    raise ValueError(f"invalid source offsets: {span['span_id']}")
                if len(span.get("member_sha256", "")) != 64:
                    raise ValueError(f"invalid source hash: {span['span_id']}")
        output.append(attached)

    summary = {
        "total": len(output), "described": described, "insufficient": insufficient,
        "fallback_pair": fallback, "usable_description_ratio": described / len(output) if output else 0,
        "records_sha256": file_sha256(records_path),
        "predictions_sha256": file_sha256(predictions_path),
        "profile": "legacy_open_description_v1",
    }
    if not output or described == 0:
        raise ValueError("semantic arm requires at least one nonempty validated description")
    return output, summary


def edge_card(record: dict) -> dict:
    """Make the bounded navigation card; generated text is never answer evidence."""
    anchors = []
    for endpoint in record["endpoints"].values():
        for span in endpoint["spans"]:
            if not span["source_kind"].startswith("ORIGINAL_"):
                continue
            anchors.append({k: span[k] for k in (
                "span_id", "node_id", "member_id", "char_start", "char_end", "text",
                "member_sha256", "source_kind")})
    return {
        "edge_id": record["edge_id"],
        "source_node_id": record["source_node_id"],
        "target_node_id": record["target_node_id"],
        "relation_description": copy.deepcopy(record["relation_description"]),
        "description_metadata": copy.deepcopy(record["description_metadata"]),
        "anchors": anchors,
    }
