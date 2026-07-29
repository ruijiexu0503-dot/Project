import json
from pathlib import Path

from evidence_graph.block_classifier import classify_block_role
from evidence_graph.config import DEFAULT_CONFIG
from evidence_graph.pipeline import build_nodes


def block(markdown, block_type="text", **kw):
    return {"markdown": markdown, "text": markdown, "block_type": block_type, **kw}


def test_classifier_expected_roles():
    assert classify_block_role(block("# Paper title", "heading")) == "document_title"
    assert classify_block_role(block("## I. INTRODUCTION", "heading")) == "section_heading"
    assert classify_block_role(block("DOI: 10.1/example")) == "identifier_metadata"
    assert classify_block_role(block("(Received 1 January 2020; published 2 February 2020)")) == "publication_metadata"
    assert classify_block_role(block("(LIGO Scientific Collaboration)")) == "author_metadata"
    assert classify_block_role(block("5°")) == "ocr_noise"


def test_pipeline_stable_ids_and_exact_markdown(tmp_path):
    aligned = tmp_path/"aligned"/"doc"; aligned.mkdir(parents=True)
    source = "Exact *Markdown* with $x$."
    page = {"doc_id":"doc", "page":"page_0001", "aligned_blocks":[
        {**block("# Title", "heading"), "block_id":"b1", "final_order":1},
        {**block("## Intro", "heading"), "block_id":"b2", "final_order":2},
        {**block(source), "block_id":"b3", "final_order":3, "bbox":[1,2,3,4]}], "layout_regions":[]}
    (aligned/"page_0001.json").write_text(json.dumps(page))
    cfg = json.loads(json.dumps(DEFAULT_CONFIG)); cfg["input"]["aligned_root"] = str(tmp_path/"aligned"); cfg["output"]["graph_root"] = str(tmp_path/"out")
    one = build_nodes("doc", cfg); two = build_nodes("doc", cfg)
    assert one["evidence"][0]["original_markdown"] == source
    assert [n["node_id"] for n in one["evidence"]] == [n["node_id"] for n in two["evidence"]]
    assert one["evidence"][0]["section_path"] == ["Intro"]
    assert one["validation"]["valid"]

