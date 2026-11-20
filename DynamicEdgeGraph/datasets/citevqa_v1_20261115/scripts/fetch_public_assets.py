#!/usr/bin/env python3
"""Fetch and audit CiteVQA's public annotations without fetching restricted PDFs."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from huggingface_hub import hf_hub_download


ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "opendatalab/CiteVQA"
REVISION = "main"
FILES = ("data/validation/CiteVQA.json", "data/download/pdf_source.csv")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    raw = ROOT / "raw" / "huggingface"
    manifests = ROOT / "manifests"
    raw.mkdir(parents=True, exist_ok=True); manifests.mkdir(parents=True, exist_ok=True)
    local = {}
    for name in FILES:
        path = Path(hf_hub_download(repo_id=REPO_ID, repo_type="dataset", revision=REVISION,
                                    filename=name, local_dir=str(raw)))
        local[name] = path
    samples = json.loads(local["data/validation/CiteVQA.json"].read_text(encoding="utf-8"))
    if not isinstance(samples, list) or not samples:
        raise ValueError("CiteVQA annotation is not a non-empty JSON list")
    required = {"index", "Question", "Standard_Answer", "PDF_Source", "Evidence", "dataset_type", "language"}
    absent = required - set(samples[0])
    if absent:
        raise ValueError(f"unexpected CiteVQA schema; missing {sorted(absent)}")
    evidence = [element for sample in samples for element in sample["Evidence"]]
    with local["data/download/pdf_source.csv"].open(encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    manifest = {
        "dataset": REPO_ID, "revision_requested": REVISION,
        "public_only": True,
        "restricted_pdfs_downloaded": False,
        "questions": len(samples), "referenced_pdf_paths": len({p for x in samples for p in x["PDF_Source"]}),
        "pdf_source_rows": len(source_rows),
        "dataset_type_counts": dict(sorted(Counter(x["dataset_type"] for x in samples).items())),
        "language_counts": dict(sorted(Counter(x["language"] for x in samples).items())),
        "question_type_counts": dict(sorted(Counter(x.get("Question_Type", "UNKNOWN") for x in samples).items())),
        "evidence_elements": len(evidence),
        "evidence_type_counts": dict(sorted(Counter(x.get("type", "UNKNOWN") for x in evidence).items())),
        "files": {name: {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size} for name, path in local.items()},
        "boundary": "No CiteVQA question, answer, or evidence is used for Stage 1 pruning, node embeddings, or relation labels.",
    }
    (manifests / "public_assets_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
