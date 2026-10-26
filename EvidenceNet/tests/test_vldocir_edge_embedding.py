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
