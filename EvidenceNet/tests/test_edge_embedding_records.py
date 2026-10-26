import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import edge_embedding_records as records


def fixture():
    nodes = {
        "n1": {"id": "n1", "document": "d1", "page": 1, "node_type": "TEXT",
               "source_image_path": "/missing/a.png",
               "members": [{"id": "m1", "text": "Alpha is higher in 2024.", "type": "text"}]},
        "n2": {"id": "n2", "document": "d2", "page": 2, "node_type": "TABLE",
               "source_image_path": "/missing/b.png",
               "members": [{"id": "m2", "text": "Beta remained lower in 2023.", "type": "table"}]},
    }
    edge = {"task_id": "e1", "source": "n1", "target": "n2", "model_result": {"anchors": {
        "A": [{"member_id": "m1", "char_start": 0, "char_end": 24,
               "quote": "Alpha is higher in 2024.", "kind": "ORIGINAL_TEXT"}],
        "B": [{"member_id": "m2", "char_start": 0, "char_end": 28,
               "quote": "Beta remained lower in 2023.", "kind": "ORIGINAL_TABLE_ROW"}],
    }}}
    return edge, nodes


def test_grounded_record_and_open_description_contract():
    edge, nodes = fixture()
    record = records.build_record(edge, nodes, "semantic")
    assert record["endpoints"]["A"]["spans"][0]["text"] == nodes["n1"]["members"][0]["text"]
    assert "e1:A:S000" in records.endpoint_text(record, "A")
    value = {"description": "A reports a 2024 increase while B reports a lower 2023 value.",
             "cited_span_ids": ["e1:A:S000", "e1:B:S000"],
             "limitations": "Different subjects and years.", "status": "DESCRIBED"}
    assert records.validate_description(value, record) == value
    attached = records.attach_description(record, value)
    assert attached["relation_description"]["text"] == value["description"]


def test_offsets_and_cross_endpoint_citations_are_strict():
    edge, nodes = fixture()
    bad = copy.deepcopy(edge); bad["model_result"]["anchors"]["A"][0]["char_end"] -= 1
    with pytest.raises(ValueError, match="does not match"):
        records.build_record(bad, nodes, "semantic")
    record = records.build_record(edge, nodes, "semantic")
    with pytest.raises(ValueError, match="both endpoints"):
        records.validate_description({"description": "Only A", "cited_span_ids": ["e1:A:S000"],
            "limitations": "", "status": "DESCRIBED"}, record)
    with pytest.raises(ValueError, match="must not cite"):
        records.validate_description({"description": "", "cited_span_ids": ["e1:A:S000"],
            "limitations": "Insufficient", "status": "INSUFFICIENT"}, record)


def test_failed_description_falls_back_without_dropping_edge():
    edge, nodes = fixture(); record = records.build_record(edge, nodes, "semantic")
    fallback = records.attach_description(record, None)
    assert fallback["edge_id"] == record["edge_id"]
    assert fallback["relation_description"]["status"] == "FALLBACK_PAIR"
    assert fallback["relation_description"]["text"] == ""
