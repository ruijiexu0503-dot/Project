#!/usr/bin/env python3
"""Adapt one Dolphin poster page to the hybrid member-node input contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dolphin-root", type=Path, required=True)
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    page_json = args.dolphin_root / "pages.jsonl"
    rows = [json.loads(line) for line in page_json.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1 or rows[0].get("page") != 1:
        raise ValueError(f"Expected exactly one Dolphin page 1, found {len(rows)}")
    row = rows[0]
    task = "detr_postergen_qwen35b/page_0001"
    target = args.output / task
    target.mkdir(parents=True, exist_ok=True)
    source_image = args.source_image.resolve()
    link = target / "original.png"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(source_image)

    atoms = []
    visuals = []
    for index, element in enumerate(row["elements"], 1):
        label = str(element.get("label") or "unknown")
        text = str(element.get("text") or "")
        atom_type = {
            "fig": "image",
            "tab": "table",
            "sec_0": "heading",
            "sec_1": "heading",
        }.get(label, "text")
        atom_id = f"A_{index:03d}"
        bbox = element.get("bbox")
        fragments = []
        if text:
            fragments.append({
                "fragment_id": f"{atom_id}::F001",
                "source_atom_id": atom_id,
                "char_start": 0,
                "char_end": len(text),
                "text": text,
                "oversized_unsplit": False,
            })
        atoms.append({
            "atom_id": atom_id,
            "atom_type": atom_type,
            "layout_role": label,
            "text_preview": text[:500],
            "text_length": len(text),
            "text_fragments": fragments,
            "geometry_members": [{
                "member_id": f"{atom_id}::G001",
                "bbox": bbox,
            }] if bbox else [],
            "deepseek_order": element.get("reading_order", index - 1),
            "parser_order": element.get("reading_order", index - 1),
        })
        if label == "fig" and bbox:
            visuals.append({
                "visual_bundle_id": f"V_{index:03d}",
                "bbox": bbox,
                "provenance_state": "dolphin_complete_figure",
                "layout_label": "figure",
                "geometry_members": [{
                    "member_id": f"V_{index:03d}::G001",
                    "bbox": bbox,
                    "bbox_source": "dolphin_v2_element_bbox",
                }],
                "native_components": [],
            })

    representation = {
        "document_id": row["document_id"],
        "page": "page_0001",
        "atoms": atoms,
        "visual_bundles": visuals,
        "source_parser": "dolphin_v2",
        "parser_reading_order": "dolphin_v2 reading_order",
        "production_modified": False,
    }
    (target / "input_representation.json").write_text(
        json.dumps(representation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "tasks": [task],
        "pages": [{
            "task": task,
            "source_image": str(source_image),
            "source_image_sha256": sha(source_image),
            "atoms": len(atoms),
            "visuals": len(visuals),
        }],
        "production_modified": False,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"task": task, "atoms": len(atoms), "visuals": len(visuals)}))


if __name__ == "__main__":
    main()
