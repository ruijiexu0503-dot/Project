#!/usr/bin/env python3
"""Frozen visual ownership ranking pilot. Reads existing nodes; never mutates them."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
from evidence_graph.llm_client import create_llm

MANIFEST = ROOT / "EvidenceNet/output/prompt_comparison_20261006/manifest.json"
LABELS = {
    "case_00": ("T_003", "UNSUPPORTED"),
    "case_01": ("T_003", "SUPPORTED"),
    "case_02": ("T_005", "UNSUPPORTED"),
    "case_03": ("T_002", "UNSUPPORTED"),
    "case_04": ("T_003", "UNSUPPORTED"),
    "case_05": ("T_005", "UNSUPPORTED"),
    "case_06": ("T_004", "SUPPORTED"),
    "case_07": ("T_017", "SUPPORTED"),
    "case_08": ("T_002", "SUPPORTED"),
    "case_09": ("T_001", "SUPPORTED"),
    "case_10": ("T_003", "SUPPORTED"),
    "case_11": ("T_001", "SUPPORTED"),
}
SYSTEM = "Describe only the supplied cropped visual asset. It is the sole evidence; do not infer facts from a surrounding page."
PROMPT = ("Write 1-3 concise English sentences describing visible subject matter, diagram elements, "
          "labels, and layout. If a chart or table is visible, give its axes, headings, and legible values. "
          "Do not infer unstated claims, relationships to other pictures, or numerical performance. "
          "Ignore photo credits and watermarks as semantic content. State if the crop is unclear. "
          "Return plain text only.")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    return json.loads(MANIFEST.read_text())["cases"]


def describe(out: Path, model: Path):
    out.mkdir(parents=True, exist_ok=True)
    rows_path = out / "descriptions.jsonl"
    prior = {r["case_id"]: r for line in rows_path.read_text().splitlines()
             if line.strip() for r in [json.loads(line)]} if rows_path.exists() else {}
    pending = []
    for case in cases():
        image = Path(case["images"][-1]); digest = sha(image)
        if case["case_id"] not in prior or prior[case["case_id"]]["crop_sha256"] != digest:
            pending.append((case, image, digest))
    if not pending:
        print("All crop descriptions cached", flush=True)
        return
    llm = create_llm({"provider": "transformers", "model": str(model), "dtype": "bfloat16",
                      "device_map": "auto", "require_cuda": True, "enable_thinking": False,
                      "max_new_tokens": 180})
    for case, image, digest in pending:
        result = llm.generate_raw_with_images(SYSTEM, PROMPT, [str(image)], max_new_tokens=180)
        row = {"case_id": case["case_id"], "image": str(image), "crop_sha256": digest,
               "model": str(model), "timestamp": result.timestamp, "system": SYSTEM,
               "prompt": PROMPT, "description": result.raw.strip()}
        if not row["description"]:
            raise ValueError(f"Empty visual description: {case['case_id']}")
        with rows_path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(case["case_id"], row["description"].replace("\n", " ")[:180], flush=True)


def embed(texts: list[str], model_path: Path):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True,
                                               trust_remote_code=True, padding_side="left")
    model = AutoModel.from_pretrained(model_path, local_files_only=True,
                                      trust_remote_code=True, torch_dtype=torch.bfloat16).cuda().eval()
    vectors = []
    for start in range(0, len(texts), 8):
        batch = tokenizer(texts[start:start+8], padding=True, truncation=True,
                          max_length=512, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            vec = hidden[:, -1].float()
            vec = torch.nn.functional.normalize(vec, p=2, dim=1)
            vectors.extend(vec.cpu().numpy())
    return vectors


def rank(out: Path, model: Path):
    import numpy as np
    descriptions = {}
    for line in (out / "descriptions.jsonl").read_text().splitlines():
        r = json.loads(line); descriptions[r["case_id"]] = r
    items = []
    for c in cases():
        cid = c["case_id"]
        d = descriptions[cid]
        if d["crop_sha256"] != sha(Path(c["images"][-1])):
            raise ValueError(f"Stale crop description: {cid}")
        ledger = json.loads((Path(c["baseline"]) / "candidate_ledger.json").read_text())
        candidates = ledger[c["visual_id"]]["ranked"]
        label_id, label = LABELS[cid]
        if label_id not in {r["unit_id"] for r in candidates}:
            raise ValueError(f"Frozen reviewed candidate missing: {cid}/{label_id}")
        items.append((c, d, candidates, label_id, label))
    texts = []
    for _, d, candidates, _, _ in items:
        texts.append("Instruct: Find page text about the visible visual content.\nQuery: " + d["description"])
        texts.extend(r["text"] for r in candidates)
    vectors = embed(texts, model)
    reports = []; cursor = 0
    for c, d, candidates, label_id, label in items:
        q = vectors[cursor]; vs = vectors[cursor+1:cursor+1+len(candidates)]
        cursor += 1+len(candidates)
        scores = {r["unit_id"]: float(np.dot(q, v)) for r, v in zip(candidates, vs)}
        geom = sorted(candidates, key=lambda r: (r["geometry"]["score"], r["unit_id"]))
        dense = sorted(candidates, key=lambda r: (-scores[r["unit_id"]], r["unit_id"]))
        gr = {r["unit_id"]: i for i, r in enumerate(geom)}
        dr = {r["unit_id"]: i for i, r in enumerate(dense)}
        # Fixed, parameter-free rank fusion; does not tune on review labels.
        fused = sorted(candidates, key=lambda r: (gr[r["unit_id"]]+dr[r["unit_id"]],
                                                 gr[r["unit_id"]], r["unit_id"]))
        ranks = {"geometry": [r["unit_id"] for r in geom],
                 "embedding": [r["unit_id"] for r in dense],
                 "equal_rank_fusion": [r["unit_id"] for r in fused]}
        reports.append({"case_id": c["case_id"], "document_id": c["document_id"],
                        "page": c["page"], "visual_id": c["visual_id"],
                        "reviewed_candidate": label_id, "review_label": label,
                        "description": d["description"], "crop_sha256": d["crop_sha256"],
                        "candidate_count": len(candidates), "rankings": ranks,
                        "reviewed_ranks": {arm: order.index(label_id)+1 for arm, order in ranks.items()},
                        "cosine_by_candidate": {k: round(v, 5) for k, v in scores.items()}})
    summary = {}
    for arm in ("geometry", "embedding", "equal_rank_fusion"):
        pos = [r for r in reports if r["review_label"] == "SUPPORTED"]
        neg = [r for r in reports if r["review_label"] == "UNSUPPORTED"]
        summary[arm] = {"positive_top1": sum(r["reviewed_ranks"][arm] == 1 for r in pos),
                        "positive_top3": sum(r["reviewed_ranks"][arm] <= 3 for r in pos),
                        "positive_total": len(pos),
                        "known_negative_top1": sum(r["reviewed_ranks"][arm] == 1 for r in neg),
                        "known_negative_total": len(neg)}
    result = {"method": "frozen 12-case purposive visual ownership ranking; only one pre-reviewed candidate per case is labeled; other candidates not all reviewed",
              "description_model": descriptions[items[0][0]["case_id"]]["model"],
              "embedding_model": str(model), "summary": summary, "cases": reports,
              "production_modified": False}
    (out / "ranking_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


class TableCells(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.rows.append([])
        elif tag in {"td", "th"}: self.cell = []

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.rows[-1].append("".join(self.cell).strip()); self.cell = None


def tables(out: Path, model: Path):
    from PIL import Image
    from scripts.bounded_geometry import boxes, pair_hint
    import numpy as np
    frozen = [("shard_3/entropy/page_0006", "A_006", "A_005"),
              ("shard_3/entropy/page_0006", "A_011", "A_010"),
              ("shard_0/gNtSaU-1511.05999v3/page_0006", "A_006", "A_007")]
    samples = []; all_texts = []
    for rel, table_id, linked_id in frozen:
        path = ROOT / "EvidenceNet/output/latest_regression_46209" / rel
        rep = json.loads((path / "input_representation.json").read_text())
        atoms = rep["atoms"]; tab = next(a for a in atoms if a["atom_id"] == table_id)
        raw = "".join(f["text"] for f in tab["text_fragments"])
        parser = TableCells(); parser.feed(raw)
        flat = "Table cells, preserving source row order. " + " ".join(
            f"Row {i}: " + " | ".join(row) + "." for i, row in enumerate(parser.rows, 1))
        candidates = [a for a in atoms if a["atom_type"] in {"text", "caption", "heading"}
                      and a["text_preview"].strip() and boxes(a)]
        if linked_id not in {a["atom_id"] for a in candidates}: raise ValueError(linked_id)
        with Image.open(rep["source_image"]) as im: size = im.size
        geometry = {}
        for a in candidates:
            obs = [b for x in atoms if x["atom_id"] not in {table_id, a["atom_id"]}
                   for b in boxes(x)]
            geometry[a["atom_id"]] = min(pair_hint(v, t, obs, size)["score"]
                                         for v in boxes(tab) for t in boxes(a))
        samples.append((rel, table_id, linked_id, raw, flat, candidates, geometry))
        all_texts.extend(["Instruct: Find page text about this table.\nQuery: " + raw,
                          "Instruct: Find page text about this table.\nQuery: " + flat])
        all_texts.extend(a["text_preview"] for a in candidates)
    vectors = embed(all_texts, model); cursor = 0; report = []
    for rel, table_id, linked_id, raw, flat, candidates, geometry in samples:
        qr, qf = vectors[cursor:cursor+2]
        vs = vectors[cursor+2:cursor+2+len(candidates)]
        cursor += 2+len(candidates)
        scores = {"raw_html": {a["atom_id"]: float(np.dot(qr, v)) for a, v in zip(candidates, vs)},
                  "row_description": {a["atom_id"]: float(np.dot(qf, v)) for a, v in zip(candidates, vs)}}
        rankings = {"geometry": sorted(geometry, key=lambda k: (geometry[k], k))}
        for arm in scores:
            rankings[arm] = sorted(scores[arm], key=lambda k: (-scores[arm][k], k))
            gr = {k: i for i, k in enumerate(rankings["geometry"])}
            dr = {k: i for i, k in enumerate(rankings[arm])}
            rankings[arm + "_plus_geometry"] = sorted(
                geometry, key=lambda k: (gr[k]+dr[k], gr[k], k))
        report.append({"source": rel, "table_id": table_id, "linked_text_id": linked_id,
                       "raw_html_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                       "row_description": flat, "candidate_count": len(candidates),
                       "rankings": rankings,
                       "linked_ranks": {k: v.index(linked_id)+1 for k, v in rankings.items()},
                       "scores": scores})
    out.mkdir(parents=True, exist_ok=True)
    (out / "table_ranking_report.json").write_text(json.dumps({
        "method": "three preselected parsed tables; row description is deterministic cell serialization, not an LLM summary; linked text labels are source-reviewed but sample is tiny",
        "embedding_model": str(model), "production_modified": False, "cases": report},
        ensure_ascii=False, indent=2))
    print(json.dumps([{r["source"] + "/" + r["table_id"]: r["linked_ranks"]}
                      for r in report], ensure_ascii=False, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["describe", "rank", "tables"])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    a = p.parse_args()
    {"describe": describe, "rank": rank, "tables": tables}[a.stage](a.output, a.model)


if __name__ == "__main__":
    main()
