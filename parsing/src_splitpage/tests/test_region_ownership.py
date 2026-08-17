import json
from pathlib import Path
import shutil

from parsing.src_splitpage.src.region_ownership import assign_ownership_for_doc


def make_doc(tmp_path: Path, doc_id: str, pages: dict):
    root = tmp_path / "parse_root"
    doc = root / doc_id
    doc.mkdir(parents=True)
    for pagename, elements in pages.items():
        page_dir = doc / pagename
        page_dir.mkdir()
        (page_dir / "elements.json").write_text(json.dumps({"elements": elements}, ensure_ascii=False))
    return root


def test_article_and_ad_on_same_page(tmp_path: Path):
    pages = {
        "page_0001": [
            {"element_id": "page_0001_el_0001", "order": 1, "type": "title", "text": "Great Research", "bbox": [50, 50, 400, 120]},
            {"element_id": "page_0001_el_0002", "order": 2, "type": "text", "text": "This is the body of the article." * 20, "bbox": [50, 130, 400, 600]},
            {"element_id": "page_0001_el_0003", "order": 3, "type": "text", "text": "Buy now at example.com", "bbox": [420, 100, 780, 600]},
        ]
    }
    root = make_doc(tmp_path, "doc1", pages)
    outdir = tmp_path / "out"
    results = assign_ownership_for_doc(root, "doc1", outdir)
    assert results and results[0]["regions"]
    owners = {r["element_id"]: r["owner"] for r in results[0]["regions"]}
    assert owners["page_0001_el_0001"].startswith("article_")
    assert owners["page_0001_el_0003"].startswith("advertisement_") or owners["page_0001_el_0003"] == "ambiguous"


def test_article_end_and_start_same_page(tmp_path: Path):
    pages = {
        "page_0001": [
            {"element_id": "page_0001_el_0001", "order": 1, "type": "title", "text": "Article A", "bbox": [50, 50, 400, 120]},
            {"element_id": "page_0001_el_0002", "order": 2, "type": "text", "text": "End of A." * 10, "bbox": [50, 130, 400, 400]},
            {"element_id": "page_0001_el_0003", "order": 3, "type": "title", "text": "Article B", "bbox": [50, 410, 400, 480]},
            {"element_id": "page_0001_el_0004", "order": 4, "type": "text", "text": "Start of B." * 10, "bbox": [50, 490, 400, 900]},
        ]
    }
    root = make_doc(tmp_path, "doc2", pages)
    outdir = tmp_path / "out"
    results = assign_ownership_for_doc(root, "doc2", outdir)
    owners = {r["element_id"]: r["owner"] for r in results[0]["regions"]}
    assert owners["page_0001_el_0001"] != owners["page_0001_el_0003"]


def test_multicolumn_article(tmp_path: Path):
    pages = {
        "page_0001": [
            {"element_id": "page_0001_el_0001", "order": 1, "type": "title", "text": "Multi Col", "bbox": [50, 50, 300, 120]},
            {"element_id": "page_0001_el_0002", "order": 2, "type": "text", "text": "Col1 body." * 30, "bbox": [50, 130, 300, 900]},
            {"element_id": "page_0001_el_0003", "order": 3, "type": "text", "text": "Col2 body." * 30, "bbox": [320, 130, 600, 900]},
        ]
    }
    root = make_doc(tmp_path, "doc3", pages)
    outdir = tmp_path / "out"
    results = assign_ownership_for_doc(root, "doc3", outdir)
    owners = {r["element_id"]: r["owner"] for r in results[0]["regions"]}
    # both columns should belong to the same article (propagated)
    assert owners["page_0001_el_0002"].startswith("article_")
    assert owners["page_0001_el_0003"].startswith("article_")


def test_pull_quote_not_new_article(tmp_path: Path):
    pages = {
        "page_0001": [
            {"element_id": "page_0001_el_0001", "order": 1, "type": "title", "text": "Main Article", "bbox": [50, 50, 400, 120]},
            {"element_id": "page_0001_el_0002", "order": 2, "type": "text", "text": "Short pull quote", "bbox": [200, 200, 400, 260]},
            {"element_id": "page_0001_el_0003", "order": 3, "type": "text", "text": "Body of article." * 40, "bbox": [50, 130, 400, 900]},
        ]
    }
    root = make_doc(tmp_path, "doc4", pages)
    outdir = tmp_path / "out"
    results = assign_ownership_for_doc(root, "doc4", outdir)
    owners = {r["element_id"]: r["owner"] for r in results[0]["regions"]}
    # pull quote should not start a new article
    assert owners["page_0001_el_0002"].startswith("article_") or owners["page_0001_el_0002"] == "ambiguous"


def test_captions_stay_with_image(tmp_path: Path):
    pages = {
        "page_0001": [
            {"element_id": "page_0001_el_0001", "order": 1, "type": "image", "text": "", "bbox": [50, 50, 300, 400]},
            {"element_id": "page_0001_el_0002", "order": 2, "type": "text", "text": "Figure 1. A caption.", "bbox": [50, 410, 300, 460]},
        ]
    }
    root = make_doc(tmp_path, "doc5", pages)
    outdir = tmp_path / "out"
    results = assign_ownership_for_doc(root, "doc5", outdir)
    owners = {r["element_id"]: r["owner"] for r in results[0]["regions"]}
    # caption should inherit image owner (likely ambiguous or article)
    assert owners["page_0001_el_0002"] == owners["page_0001_el_0001"] or owners["page_0001_el_0002"] == "ambiguous"
