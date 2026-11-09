import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sample", ROOT / "scripts/sample_custom_vldocir_subset.py"
)
sample = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample)


def test_iou_and_node_matching_are_deterministic():
    assert sample.iou(
        {"relative_page_x": 0, "relative_page_y": 0,
         "relative_width": 1, "relative_height": 1},
        {"relative_page_x": 0.5, "relative_page_y": 0.5,
         "relative_width": 0.5, "relative_height": 0.5},
    ) == 0.25


def test_stable_order_and_stratified_selection():
    rows = [
        {"question_id": "a", "question_type": sample.STRUCTURES[0]},
        {"question_id": "b", "question_type": sample.STRUCTURES[0]},
        {"question_id": "c", "question_type": sample.STRUCTURES[1]},
    ]
    first = sample.stratified_select(rows, 1, 20261106)
    second = sample.stratified_select(rows, 1, 20261106)
    assert first == second
    assert len(first) == 2
    assert {row["question_type"] for row in first} == {sample.STRUCTURES[0], sample.STRUCTURES[1]}


def test_source_normalization():
    assert sample.source_of("x", {"x": {"data_source": "scientific_articles_arxiv"}}) == "arxiv"
    assert sample.source_of("x", {"x": {"data_source": "sec_proxy_reports"}}) == "sec"
