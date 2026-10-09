from pathlib import Path

from PIL import Image

from evidence_graph.magazine_article_reconstruction import (
    _attach_caption_grounded_visuals,
    _continuation_constraints,
    _enforce_continuation_constraints,
    _grounded_visual_records,
    _layout_visual_records,
    _resolve_existing_path,
    _split_multiple_heading_articles,
    _validate,
)


def test_grounded_image_block_becomes_one_visual_not_text():
    payload = {
        "aligned_blocks": [{
            "block_id": "ds_img_0003", "block_type": "image", "text": "",
            "asset_path": "/tmp/image.jpg", "matched_region_id": "layout_004",
            "geometry_members": [{"member_id": "m1", "bbox": [10, 20, 300, 400]}],
        }]
    }
    records = _grounded_visual_records(payload)
    assert len(records) == 1
    assert records[0]["visual_node_id"] == "ds_img_0003"
    assert records[0]["bbox"] == [10, 20, 300, 400]
    assert records[0]["source_region_ids"] == ["layout_004"]


def test_project_relative_grounded_image_asset_is_resolved(tmp_path):
    asset = tmp_path / "parsing" / "output" / "doc" / "page_0001" / "images" / "0.jpg"
    asset.parent.mkdir(parents=True)
    Image.new("RGB", (40, 30), "white").save(asset)
    relative = "parsing/output/doc/page_0001/images/0.jpg"
    payload = {"aligned_blocks": [{
        "block_id": "ds_img_0000", "block_type": "image", "asset_path": relative,
        "geometry_members": [{"member_id": "m1", "bbox": [0, 0, 40, 30]}],
    }]}
    records = _grounded_visual_records(payload, (tmp_path,))
    assert records[0]["asset_path"] == str(asset.resolve())
    assert records[0]["stored_asset_path"] == relative
    assert _resolve_existing_path(relative, (tmp_path,)) == str(asset.resolve())


def test_layout_visuals_are_not_unioned_and_receive_nearest_captions(tmp_path):
    page_image = tmp_path / "page.png"
    Image.new("RGB", (800, 1200), "white").save(page_image)
    payload = {
        "page": "page_0017", "page_width": 800, "page_height": 1200,
        "layout_regions": [
            {"region_id": "layout_006", "label": "chart", "bbox": [240, 170, 520, 420]},
            {"region_id": "layout_016", "label": "chart", "bbox": [240, 620, 720, 890]},
        ],
        "aligned_blocks": [
            {"block_id": "caption_1", "block_type": "caption", "bbox": [240, 430, 520, 470], "text": "Fig. 1"},
            {"block_id": "caption_2", "block_type": "caption", "bbox": [240, 900, 700, 950], "text": "Fig. 2"},
        ],
    }
    records = _layout_visual_records("doc", payload, str(page_image), tmp_path)
    assert [row["bbox"] for row in records] == [[240, 170, 520, 420], [240, 620, 720, 890]]
    assert [row["caption_block_id"] for row in records] == ["caption_1", "caption_2"]
    assert all(Path(row["asset_path"]).exists() for row in records)


def test_validation_rejects_merging_independent_top_level_headings():
    parsed = {"articles": [{"article_id": "A1", "node_ids": ["h1", "b1", "h2", "b2"],
                            "reading_order": ["h1", "b1", "h2", "b2"]}], "non_article_nodes": []}
    validation = _validate(parsed, {"h1", "b1", "h2", "b2"}, {"h1", "h2"})
    assert not validation["valid"]
    assert any(error["type"] == "multiple_top_level_headings_in_one_article" for error in validation["errors"])


def test_validation_accepts_two_heading_led_articles():
    parsed = {"articles": [
        {"article_id": "A1", "node_ids": ["h1", "b1"], "reading_order": ["h1", "b1"]},
        {"article_id": "A2", "node_ids": ["h2", "b2"], "reading_order": ["h2", "b2"]},
    ], "non_article_nodes": []}
    assert _validate(parsed, {"h1", "b1", "h2", "b2"}, {"h1", "h2"})["valid"]


def test_validation_requires_content_visual_in_article_order():
    parsed = {"articles": [{"article_id": "A1", "node_ids": ["h1"], "reading_order": ["h1"]}],
              "non_article_nodes": ["visual_1"]}
    validation = _validate(parsed, {"h1", "visual_1"}, {"h1"}, {"visual_1"})
    assert not validation["valid"]
    assert any(error["type"] == "content_visual_assigned_non_article" for error in validation["errors"])


def test_caption_grounded_visual_is_inserted_before_caption():
    parsed = {"articles": [{"article_id": "A1", "node_ids": ["body", "caption"],
                            "reading_order": ["body", "caption"]}], "non_article_nodes": ["visual"]}
    repaired, repairs = _attach_caption_grounded_visuals(
        parsed, [{"visual_node_id": "visual", "caption_block_id": "caption"}])
    assert repaired["articles"][0]["reading_order"] == ["body", "visual", "caption"]
    assert repaired["non_article_nodes"] == []
    assert repairs[0]["type"] == "caption_grounded_visual_attachment"


def test_caption_cannot_interrupt_strong_text_continuation():
    rows = [
        {"node_id": "body_1", "node_type": "text", "text": "The fraction is meas"},
        {"node_id": "caption", "node_type": "caption", "text": "Fig. 1"},
        {"node_id": "body_2", "node_type": "text", "text": "ured to be very small."},
    ]
    constraints = _continuation_constraints(rows)
    assert constraints == [{"source": "body_1", "target": "body_2", "reason": "does_not_end_with_terminal_punctuation",
                            "skipped_caption_ids": ["caption"]}]
    parsed = {"articles": [{"article_id": "A1", "node_ids": ["body_1", "visual", "caption", "body_2"],
                            "reading_order": ["body_1", "visual", "caption", "body_2"]}], "non_article_nodes": []}
    repaired, repairs = _enforce_continuation_constraints(parsed, constraints)
    assert repaired["articles"][0]["reading_order"] == ["body_1", "body_2", "visual", "caption"]
    assert repairs[0]["type"] == "strong_text_continuation_adjacency"
    assert _validate(repaired, {"body_1", "body_2", "visual", "caption"}, continuation_constraints=constraints)["valid"]


def test_two_top_headings_split_article_and_move_preceding_short_label():
    rows = [
        {"node_id": "cms", "node_type": "text", "text": "CMS"},
        {"node_id": "h1", "node_type": "heading", "text": "# First article"},
        {"node_id": "b1", "node_type": "text", "text": "First body."},
        {"node_id": "alice", "node_type": "text", "text": "ALICE"},
        {"node_id": "h2", "node_type": "heading", "text": "# Second article"},
        {"node_id": "b2", "node_type": "text", "text": "Second body."},
    ]
    ids = [row["node_id"] for row in rows]
    parsed = {"articles": [{"article_id": "A1", "node_ids": ids + ["visual"],
                            "reading_order": ids + ["visual"]}], "non_article_nodes": []}
    repaired, repairs = _split_multiple_heading_articles(parsed, rows, {"h1", "h2"})
    assert repaired["articles"][0]["reading_order"] == ["cms", "h1", "b1"]
    assert repaired["articles"][1]["reading_order"] == ["alice", "h2", "b2"]
    assert repaired["non_article_nodes"] == ["visual"]
    assert repairs[0]["type"] == "split_multiple_independent_top_level_headings"
