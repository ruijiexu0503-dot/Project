#!/usr/bin/env python3
"""Resume local BGE query–passage cross-encoder scoring; never embed or build edges.

Inputs: OUTPUT/reranker_inputs.jsonl, with unique {id, query, text} records.
Scores are raw single-label logits, not probabilities. Only passage text may be
truncated. Weight SHA256 is computed once; subsequent runs require unchanged
file metadata as well as unchanged small model/tokenizer files.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import tempfile
import time

MODEL = Path(__file__).resolve().parents[1] / "models/bge-reranker-v2-m3"
SETTINGS = {"max_length": 512, "max_query_tokens": 128, "batch_size": 8,
            "truncation": "only_second", "dtype": "float16", "score_type": "raw_logit"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_sha(row: dict) -> str:
    return hashlib.sha256(json.dumps(
        {key: row[key] for key in ("id", "query", "text")},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    result = []
    with path.open() as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"Blank record: {path}:{number}")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected object: {path}:{number}")
            result.append(row)
    return result


def load_inputs(path: Path) -> list[dict]:
    rows = read_rows(path)
    seen = set()
    for row in rows:
        for key in ("id", "query", "text"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Input needs nonempty string {key}: {row.get('id')}")
        if row["id"] in seen:
            raise ValueError(f"Duplicate input id: {row['id']}")
        seen.add(row["id"])
    return rows


def atomic_write(path: Path, content: str) -> None:
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def file_stamp(path: Path) -> dict:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}


def model_identity(model: Path, previous: dict | None = None) -> dict:
    """Never silently mix a changed model into an existing score checkpoint."""
    model = model.resolve(strict=True)
    files = sorted(path for path in model.iterdir() if path.is_file() and
                   path.suffix in {".json", ".model", ".safetensors", ".bin", ".txt"})
    weights = [path for path in files if path.suffix in {".safetensors", ".bin"}]
    if not (model / "config.json").is_file() or not weights:
        raise ValueError(f"Model needs config.json and local weights: {model}")
    if previous is not None:
        if previous.get("path") != str(model) or set(previous["files"]) != {p.name for p in files}:
            raise ValueError("Model path or file inventory changed; use a fresh output directory")
    records = {}
    for path in files:
        stamp = file_stamp(path)
        old = previous["files"][path.name] if previous is not None else None
        is_weight = path in weights
        if old is not None and is_weight:
            if old["stamp"] != stamp:
                raise ValueError(f"Model weight metadata changed: {path}; use a fresh output directory")
            digest = old["sha256"]
        else:
            digest = sha(path)
            if file_stamp(path) != stamp:
                raise ValueError(f"Model file changed while hashing: {path}")
            if old is not None and old["sha256"] != digest:
                raise ValueError(f"Model/tokenizer content changed: {path}")
        records[path.name] = {"sha256": digest, "stamp": stamp, "weight": is_weight}
    return {"path": str(model), "files": records}


def prepare_manifest(out: Path, model: Path, rows: list[dict]) -> dict:
    path = out / "reranker_manifest.json"
    current = {"schema_version": 1, "inputs_sha256": sha(out / "reranker_inputs.jsonl"),
               "input_count": len(rows), "settings": SETTINGS, "runner_sha256": sha(Path(__file__))}
    if path.exists():
        manifest = json.loads(path.read_text())
        if any(manifest.get(key) != value for key, value in current.items()):
            raise ValueError("Input, settings, or runner changed; refusing resume")
        model_identity(model, manifest["model"])
        return manifest
    if (out / "reranker_scores.jsonl").exists() or (out / "reranker_execution.json").exists():
        raise ValueError("Checkpoint exists without manifest; refusing unbound scores")
    current["model"] = model_identity(model)
    write_json(path, current)
    return current


def load_scores(path: Path, inputs: list[dict], *, require_complete: bool = False) -> list[dict]:
    """Validate a resumable input-prefix checkpoint, optionally requiring all rows.

    This is a CPU-only validation API for downstream reports. It deliberately
    verifies row content, not merely ID membership, so scores cannot be silently
    reused after changing a query or its passage.
    """
    rows = read_rows(path) if path.exists() else []
    if len(rows) > len(inputs):
        raise ValueError("More checkpoint scores than inputs")
    for score, row in zip(rows, inputs):
        if score.get("id") != row["id"] or score.get("input_sha256") != input_sha(row):
            raise ValueError("Checkpoint input order/content mismatch")
        value = score.get("score")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Invalid logit for {row['id']}")
        count = score.get("original_tokens")
        if type(count) is not int or count < 1 or type(score.get("truncated")) is not bool:
            raise ValueError(f"Missing/invalid token metadata for {row['id']}")
        if score["truncated"] != (count > SETTINGS["max_length"]):
            raise ValueError(f"Inconsistent truncation metadata for {row['id']}")
    if require_complete and len(rows) != len(inputs):
        raise ValueError(f"Incomplete scores: {len(rows)}/{len(inputs)}")
    return rows


def validate_queries(tokenizer, inputs: list[dict]) -> None:
    # Preflight the whole input: never checkpoint part of a known-invalid dataset.
    for query in dict.fromkeys(row["query"] for row in inputs):
        count = len(tokenizer.encode(query, add_special_tokens=False, truncation=False))
        if count > SETTINGS["max_query_tokens"]:
            raise ValueError(f"Query has {count} tokens (limit {SETTINGS['max_query_tokens']}); "
                             "query truncation is forbidden")


def infer_batch(model, tokenizer, batch: list[dict], torch) -> list[dict]:
    queries, texts = [r["query"] for r in batch], [r["text"] for r in batch]
    untruncated = tokenizer(queries, texts, add_special_tokens=True, truncation=False, padding=False)
    counts = [len(ids) for ids in untruncated["input_ids"]]
    if len(counts) != len(batch) or any(count < 1 for count in counts):
        raise ValueError("Tokenizer did not return one nonempty token sequence per pair")
    encoded = tokenizer(queries, texts, padding=True, truncation="only_second",
                        max_length=SETTINGS["max_length"], return_tensors="pt").to("cuda")
    with torch.inference_mode():
        logits = model(**encoded).logits
        if tuple(logits.shape) != (len(batch), 1):
            raise ValueError(f"Expected one raw logit per pair, got {tuple(logits.shape)}")
        values = logits[:, 0].float().cpu().tolist()
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Model returned nonfinite logits; batch not checkpointed")
    return [{"id": row["id"], "input_sha256": input_sha(row), "score": value,
             "original_tokens": count, "truncated": count > SETTINGS["max_length"]}
            for row, value, count in zip(batch, values, counts)]


def run(out: Path, model_path: Path, minutes: float = 45) -> dict:
    if not math.isfinite(minutes) or minutes <= 0:
        raise ValueError("minutes must be positive and finite")
    out = out.resolve(strict=True)
    with (out / ".reranker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another reranker is already writing this output") from exc
        return run_locked(out, model_path, minutes)


def run_locked(out: Path, model_path: Path, minutes: float) -> dict:
    started = time.monotonic()
    inputs = load_inputs(out / "reranker_inputs.jsonl")
    manifest = prepare_manifest(out, model_path, inputs)
    scores_path = out / "reranker_scores.jsonl"
    scores = load_scores(scores_path, inputs)
    execution_path = out / "reranker_execution.json"
    execution = {"started_at": datetime.now(timezone.utc).isoformat(), "hostname": socket.gethostname(),
                 "job_id": os.environ.get("SLURM_JOB_ID"), "partition": os.environ.get("SLURM_JOB_PARTITION"),
                 "manifest_sha256": sha(out / "reranker_manifest.json"), "inputs_sha256": manifest["inputs_sha256"],
                 "total": len(inputs), "resumed_scores": len(scores), "settings": SETTINGS,
                 "minutes": minutes, "score_type": "raw_logit", "document_embeddings_generated": False,
                 "edges_generated": False}

    def checkpoint(status: str, *, write_scores: bool = False) -> dict:
        if write_scores:
            atomic_write(scores_path, "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in scores))
        execution.update(status=status, complete=len(scores) == len(inputs), scored=len(scores),
                         elapsed_seconds=round(time.monotonic() - started, 3),
                         updated_at=datetime.now(timezone.utc).isoformat(),
                         scores_sha256=sha(scores_path) if scores_path.exists() else None)
        write_json(execution_path, execution)
        print(json.dumps({k: execution[k] for k in ("status", "scored", "total", "elapsed_seconds")}), flush=True)
        return execution

    if len(scores) == len(inputs):
        return checkpoint("already_complete", write_scores=not scores_path.exists())
    checkpoint("starting")
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required; CPU fallback is disabled")
        execution.update(gpu=torch.cuda.get_device_name(0), torch_version=torch.__version__)
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        validate_queries(tokenizer, inputs)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_path, local_files_only=True, torch_dtype=torch.float16,
        ).to("cuda").eval()
        for offset in range(len(scores), len(inputs), SETTINGS["batch_size"]):
            if time.monotonic() - started >= minutes * 60:
                return checkpoint("time_limit")
            batch = inputs[offset:offset + SETTINGS["batch_size"]]
            scores.extend(infer_batch(model, tokenizer, batch, torch))
            checkpoint("complete" if len(scores) == len(inputs) else "running", write_scores=True)
        return execution
    except Exception as exc:
        execution["error"] = f"{type(exc).__name__}: {exc}"
        checkpoint("error")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--minutes", type=float, default=45)
    args = parser.parse_args()
    run(args.output, args.model, args.minutes)


if __name__ == "__main__":
    main()
