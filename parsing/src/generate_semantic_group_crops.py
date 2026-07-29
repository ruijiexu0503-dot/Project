#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate semantic-group-level crops and insert them back into markdown.

Input:
  data/processed_vlm_md_by_doc/<doc_id>/semantic_groups.md

Outputs:
  data/processed_vlm_md_by_doc/<doc_id>/
    ├── semantic_groups_with_crops.md
    ├── group_crops_manifest.jsonl
    └── assets/
        └── group_crops/
            ├── <group_id>_p0001.jpg
            └── ...

Important design:
- A semantic group can have multiple evidence regions.
- Each evidence region is page-local.
- Cross-page groups are represented as multiple crops, not stitched into one image.
- The crop image is embedded directly into semantic_groups_with_crops.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from PIL import Image


# ---------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------

def safe_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_") or "unknown"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rel_to_base(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except Exception:
        return str(path)


def clean_path_string(s: str) -> str:
    s = s.strip().strip("`").strip()
    s = s.strip('"').strip("'")
    return s


def resolve_path(
    path_str: str | None,
    *,
    md_path: Path,
    project_root: Path,
) -> Path | None:
    if not path_str:
        return None

    path_str = clean_path_string(path_str)
    p = Path(path_str)

    candidates: list[Path] = []

    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(project_root / p)
        candidates.append(md_path.parent / p)

    for c in candidates:
        if c.exists():
            return c.resolve()

    if p.is_absolute():
        return p

    return (project_root / p).resolve()


# ---------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------

def split_semantic_group_sections(md: str) -> list[str]:
    """
    Split markdown by horizontal rules.

    The per-document file usually looks like:

      # Semantic Groups - doc_id
      doc_id: ...
      num_groups: ...

      ---

      # group_id_0001
      ...

      ---

      # group_id_0002
      ...

    We skip the global title section.
    """
    parts = re.split(r"\n\s*---\s*\n", md)

    sections: list[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        h1 = extract_first_h1(part)

        if h1.lower().startswith("semantic groups"):
            continue

        if not re.search(r"(?m)^#\s+", part):
            continue

        sections.append(part)

    return sections


def extract_first_h1(section: str) -> str:
    m = re.search(r"(?m)^#\s+(.+?)\s*$", section)
    if m:
        return m.group(1).strip()
    return "unknown_group"


def extract_meta_value(text: str, key: str) -> str | None:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    if not m:
        return None

    value = m.group(1).strip().strip("`").strip()

    if value.lower() in {"", "none", "null"}:
        return None

    return value


def extract_int_meta(text: str, key: str) -> int | None:
    value = extract_meta_value(text, key)
    if not value:
        return None

    m = re.search(r"\d+", value)
    if not m:
        return None

    return int(m.group(0))


def parse_json_list(s: str) -> list[float] | None:
    try:
        data = json.loads(s)
        if isinstance(data, list) and len(data) == 4:
            return [float(x) for x in data]
    except Exception:
        return None

    return None


def extract_list_meta(text: str, key: str) -> list[float] | None:
    """
    Extract:
      pixel_bbox: [1, 2, 3, 4]
      pixel_bbox: `[1, 2, 3, 4]`
    """
    m = re.search(rf"(?m)^{re.escape(key)}:\s*`?(\[[^\]]+\])`?", text)
    if not m:
        return None

    return parse_json_list(m.group(1))


def remove_existing_evidence_regions(section: str) -> str:
    """
    Remove a previously appended Evidence Regions block.

    We append Evidence Regions at the end of each group section.
    On re-run, remove it first to avoid duplication.
    """
    m = re.search(r"(?m)^## Evidence Regions\s*$", section)
    if not m:
        return section.rstrip()

    return section[:m.start()].rstrip()


def split_member_chunks(section: str) -> list[tuple[str | None, str]]:
    """
    Prefer member-level chunks.

    Typical member part:

      ## Members

      ### block_id
      type: ...
      bbox_meta: ...
      raw_markdown: ...

      ### block_id
      ...

    If no member heading exists, use the whole section.
    """
    parts = re.split(r"(?m)^###\s+", section)

    if len(parts) <= 1:
        return [(None, section)]

    chunks: list[tuple[str | None, str]] = []

    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue

        first_line, _, rest = part.partition("\n")
        block_id = first_line.strip()
        chunk_text = first_line + "\n" + rest

        # Ignore generated Evidence Regions subheadings on accidental re-run.
        if block_id.startswith("Evidence") or "_p" in block_id and "crop_path" in chunk_text:
            continue

        chunks.append((block_id, chunk_text))

    return chunks or [(None, section)]


# ---------------------------------------------------------------------
# Bbox / page image extraction
# ---------------------------------------------------------------------

BBOX_COMMENT_RE = re.compile(
    r"<!--\s*bbox:\s*(\{.*?\})\s*-->",
    re.DOTALL,
)

JSON_WITH_BBOX_RE = re.compile(
    r"\{[^{}]*(?:\"pixel_bbox\"|\"raw_bbox\"|\"bbox\")[^{}]*\}",
    re.DOTALL,
)


def extract_json_objects_with_bbox(text: str) -> list[dict[str, Any]]:
    objs: list[dict[str, Any]] = []

    # DeepSeekOCR2-style:
    # <!-- bbox: {...} -->
    for m in BBOX_COMMENT_RE.finditer(text):
        raw = m.group(1)
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                objs.append(obj)
        except Exception:
            pass

    # Other inline JSON objects containing pixel_bbox/raw_bbox.
    for m in JSON_WITH_BBOX_RE.finditer(text):
        raw = m.group(0)
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                objs.append(obj)
        except Exception:
            pass

    return objs


def extract_page_image(
    text: str,
    *,
    fallback_text: str,
    md_path: Path,
    project_root: Path,
) -> Path | None:
    candidates: list[str] = []

    # page_image: path
    for source in [text, fallback_text]:
        m = re.search(r"(?m)^page_image:\s*(.+?)\s*$", source)
        if m:
            candidates.append(m.group(1).strip())

    # "page_image": "path"
    for source in [text, fallback_text]:
        for m in re.finditer(r'"page_image"\s*:\s*"([^"]+)"', source):
            candidates.append(m.group(1).strip())

    # Direct path pattern.
    for source in [text, fallback_text]:
        for m in re.finditer(
            r"(?:\.{0,2}/)?output/render_result/[^\s\"']+/page_\d{4}/page\.png",
            source,
        ):
            candidates.append(m.group(0))

    # page_dir: path -> page_dir/page.png
    for source in [text, fallback_text]:
        m = re.search(r"(?m)^page_dir:\s*(.+?)\s*$", source)
        if m:
            page_dir = clean_path_string(m.group(1).strip())
            candidates.append(str(Path(page_dir) / "page.png"))

    for c in candidates:
        p = resolve_path(c, md_path=md_path, project_root=project_root)
        if p and p.exists():
            return p

    if candidates:
        return resolve_path(candidates[0], md_path=md_path, project_root=project_root)

    return None


def infer_page_no(
    text: str,
    fallback_text: str,
    page_id: str | None = None,
) -> int | None:
    for key in ["page_no", "page"]:
        value = extract_int_meta(text, key)
        if value is not None:
            return value

        value = extract_int_meta(fallback_text, key)
        if value is not None:
            return value

    if page_id:
        m = re.search(r"_p(\d{4})", page_id)
        if m:
            return int(m.group(1))

    for source in [text, fallback_text]:
        m = re.search(r"page_(\d{4})", source)
        if m:
            return int(m.group(1))

    return None


def bbox_to_pixel(
    *,
    pixel_bbox: list[float] | None,
    raw_bbox: list[float] | None,
    image_size: tuple[int, int] | None,
    image_width: int | None,
    image_height: int | None,
) -> list[int] | None:
    if pixel_bbox is not None:
        values = pixel_bbox

    elif raw_bbox is not None:
        width = image_width
        height = image_height

        if image_size is not None:
            width = width or image_size[0]
            height = height or image_size[1]

        if not width or not height:
            return None

        # DeepSeekOCR bbox is usually normalized to 0-999.
        values = [
            raw_bbox[0] / 999.0 * width,
            raw_bbox[1] / 999.0 * height,
            raw_bbox[2] / 999.0 * width,
            raw_bbox[3] / 999.0 * height,
        ]

    else:
        return None

    x1, y1, x2, y2 = values

    if image_size is not None:
        width, height = image_size
        x1 = max(0, min(width, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height, y1))
        y2 = max(0, min(height, y2))

    x1, x2 = sorted([int(round(x1)), int(round(x2))])
    y1, y2 = sorted([int(round(y1)), int(round(y2))])

    if x2 <= x1 or y2 <= y1:
        return None

    return [x1, y1, x2, y2]


@dataclass
class RawRegion:
    block_id: str | None
    page_id: str | None
    page_no: int | None
    page_image_abs: str
    pixel_bbox: list[int]


@dataclass
class CropRegion:
    region_id: str
    group_id: str
    doc_id: str | None
    group_type: str | None
    page_id: str | None
    page_no: int | None
    pixel_bbox: list[int]
    crop_path: str
    crop_path_abs: str
    page_image: str
    page_image_abs: str
    member_block_ids: list[str]


def extract_raw_regions_from_group(
    section: str,
    *,
    md_path: Path,
    project_root: Path,
) -> list[RawRegion]:
    section = remove_existing_evidence_regions(section)

    group_page_id = extract_meta_value(section, "page_id")
    group_page_image = extract_page_image(
        section,
        fallback_text=section,
        md_path=md_path,
        project_root=project_root,
    )

    chunks = split_member_chunks(section)

    raw_regions: list[RawRegion] = []
    seen = set()

    for block_id, chunk in chunks:
        page_id = extract_meta_value(chunk, "page_id") or group_page_id

        page_image = extract_page_image(
            chunk,
            fallback_text=section,
            md_path=md_path,
            project_root=project_root,
        ) or group_page_image

        if not page_image or not page_image.exists():
            continue

        try:
            with Image.open(page_image) as im:
                image_size = im.size
        except Exception:
            continue

        page_no = infer_page_no(chunk, section, page_id=page_id)

        json_objs = extract_json_objects_with_bbox(chunk)

        if json_objs:
            for obj in json_objs:
                pixel_bbox = obj.get("pixel_bbox")
                raw_bbox = obj.get("raw_bbox") or obj.get("bbox")

                image_width = obj.get("image_width")
                image_height = obj.get("image_height")

                px = bbox_to_pixel(
                    pixel_bbox=pixel_bbox,
                    raw_bbox=raw_bbox,
                    image_size=image_size,
                    image_width=int(image_width) if image_width else None,
                    image_height=int(image_height) if image_height else None,
                )

                if not px:
                    continue

                key = (block_id, page_id, page_no, str(page_image), tuple(px))

                if key in seen:
                    continue

                seen.add(key)

                raw_regions.append(
                    RawRegion(
                        block_id=block_id,
                        page_id=page_id,
                        page_no=page_no,
                        page_image_abs=str(page_image.resolve()),
                        pixel_bbox=px,
                    )
                )

        else:
            pixel_bbox = extract_list_meta(chunk, "pixel_bbox")
            raw_bbox = (
                extract_list_meta(chunk, "raw_bbox")
                or extract_list_meta(chunk, "bbox")
            )

            image_width = (
                extract_int_meta(chunk, "image_width")
                or extract_int_meta(section, "image_width")
            )
            image_height = (
                extract_int_meta(chunk, "image_height")
                or extract_int_meta(section, "image_height")
            )

            px = bbox_to_pixel(
                pixel_bbox=pixel_bbox,
                raw_bbox=raw_bbox,
                image_size=image_size,
                image_width=image_width,
                image_height=image_height,
            )

            if not px:
                continue

            key = (block_id, page_id, page_no, str(page_image), tuple(px))

            if key in seen:
                continue

            seen.add(key)

            raw_regions.append(
                RawRegion(
                    block_id=block_id,
                    page_id=page_id,
                    page_no=page_no,
                    page_image_abs=str(page_image.resolve()),
                    pixel_bbox=px,
                )
            )

    return raw_regions


def union_bbox(
    bboxes: list[list[int]],
    *,
    image_size: tuple[int, int],
    padding: int,
) -> list[int] | None:
    if not bboxes:
        return None

    x1 = min(b[0] for b in bboxes)
    y1 = min(b[1] for b in bboxes)
    x2 = max(b[2] for b in bboxes)
    y2 = max(b[3] for b in bboxes)

    width, height = image_size

    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(width, x2 + padding)
    y2 = min(height, y2 + padding)

    if x2 <= x1 or y2 <= y1:
        return None

    return [x1, y1, x2, y2]


# ---------------------------------------------------------------------
# Markdown insertion
# ---------------------------------------------------------------------

def append_evidence_regions(
    section: str,
    md_regions: list[dict[str, Any]],
) -> str:
    """
    Insert readable crop previews and machine-readable metadata
    into the semantic group section.
    """
    section = remove_existing_evidence_regions(section)

    if not md_regions:
        return section

    lines: list[str] = []

    lines.append(section.rstrip())
    lines.append("")
    lines.append("## Evidence Regions")
    lines.append("")

    for i, region in enumerate(md_regions, start=1):
        region_id = region.get("region_id", f"region_{i:02d}")
        crop_path = region.get("crop_path")
        page_no = region.get("page_no")
        page_id = region.get("page_id")
        pixel_bbox = region.get("pixel_bbox")
        page_image = region.get("page_image")
        member_block_ids = region.get("member_block_ids") or []

        lines.append(f"### {region_id}")
        lines.append("")

        if crop_path:
            lines.append(f"![{region_id}]({crop_path})")
            lines.append("")

        lines.append(f"- region_id: `{region_id}`")

        if page_no is not None:
            lines.append(f"- page_no: `{page_no}`")

        if page_id:
            lines.append(f"- page_id: `{page_id}`")

        if pixel_bbox:
            lines.append(f"- pixel_bbox: `{pixel_bbox}`")

        if crop_path:
            lines.append(f"- crop_path: `{crop_path}`")

        if page_image:
            lines.append(f"- page_image: `{page_image}`")

        if member_block_ids:
            joined = ", ".join(f"`{x}`" for x in member_block_ids)
            lines.append(f"- member_block_ids: {joined}")

        lines.append("")

    lines.append("<details>")
    lines.append("<summary>Evidence regions JSON</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(md_regions, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------

def process_semantic_groups_file(
    *,
    md_path: Path,
    padding: int,
    overwrite: bool,
    replace_original: bool,
    project_root: Path,
) -> None:
    doc_dir = md_path.parent

    crop_dir = doc_dir / "assets" / "group_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)

    out_md_path = doc_dir / "semantic_groups_with_crops.md"
    manifest_path = doc_dir / "group_crops_manifest.jsonl"

    md = read_text(md_path)
    sections = split_semantic_group_sections(md)

    new_sections: list[str] = []
    all_manifest_rows: list[dict[str, Any]] = []

    for section in sections:
        section = remove_existing_evidence_regions(section)

        group_id = extract_first_h1(section)
        doc_id = extract_meta_value(section, "doc_id")
        group_type = (
            extract_meta_value(section, "group_type")
            or extract_meta_value(section, "type")
        )

        raw_regions = extract_raw_regions_from_group(
            section,
            md_path=md_path,
            project_root=project_root,
        )

        # Group raw bboxes by page image + page_no + page_id.
        by_page: dict[tuple[str, int | None, str | None], list[RawRegion]] = {}

        for rr in raw_regions:
            key = (rr.page_image_abs, rr.page_no, rr.page_id)
            by_page.setdefault(key, []).append(rr)

        crop_regions: list[CropRegion] = []

        sorted_items = sorted(
            by_page.items(),
            key=lambda item: (
                item[0][1] if item[0][1] is not None else 10**9,
                item[0][2] or "",
                item[0][0],
            ),
        )

        for idx, ((page_image_abs, page_no, page_id), regions) in enumerate(sorted_items):
            page_image = Path(page_image_abs)

            if not page_image.exists():
                continue

            try:
                with Image.open(page_image) as im:
                    im = im.convert("RGB")
                    image_size = im.size

                    bbox = union_bbox(
                        [r.pixel_bbox for r in regions],
                        image_size=image_size,
                        padding=padding,
                    )

                    if not bbox:
                        continue

                    x1, y1, x2, y2 = bbox
                    crop = im.crop((x1, y1, x2, y2))

                    if page_no is not None:
                        page_label = f"p{page_no:04d}"
                    else:
                        page_label = f"part{idx:02d}"

                    crop_name = f"{safe_name(group_id)}_{page_label}.jpg"
                    crop_path = crop_dir / crop_name

                    if overwrite or not crop_path.exists():
                        crop.save(crop_path, quality=95)

            except Exception as e:
                print(f"[WARN] failed crop {group_id} from {page_image}: {e}")
                continue

            member_block_ids = sorted(
                {r.block_id for r in regions if r.block_id}
            )

            region_id = f"{group_id}_{page_label}"

            crop_region = CropRegion(
                region_id=region_id,
                group_id=group_id,
                doc_id=doc_id,
                group_type=group_type,
                page_id=page_id,
                page_no=page_no,
                pixel_bbox=bbox,
                crop_path=rel_to_base(crop_path, doc_dir),
                crop_path_abs=str(crop_path.resolve()),
                page_image=rel_to_base(page_image, doc_dir),
                page_image_abs=str(page_image.resolve()),
                member_block_ids=member_block_ids,
            )

            crop_regions.append(crop_region)

        manifest_rows = [asdict(region) for region in crop_regions]
        all_manifest_rows.extend(manifest_rows)

        md_regions: list[dict[str, Any]] = []

        for row in manifest_rows:
            md_regions.append(
                {
                    "region_id": row["region_id"],
                    "page_no": row["page_no"],
                    "page_id": row["page_id"],
                    "pixel_bbox": row["pixel_bbox"],
                    "crop_path": row["crop_path"],
                    "page_image": row["page_image"],
                    "member_block_ids": row["member_block_ids"],
                }
            )

        new_sections.append(append_evidence_regions(section, md_regions))

    out_lines: list[str] = []

    out_lines.append("# Semantic Groups with Crops")
    out_lines.append("")
    out_lines.append(f"source_file: `{md_path}`")
    out_lines.append(f"num_groups: {len(new_sections)}")
    out_lines.append(f"num_crop_regions: {len(all_manifest_rows)}")
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")
    out_lines.append("\n\n---\n\n".join(new_sections))
    out_lines.append("")

    write_text(out_md_path, "\n".join(out_lines))

    with manifest_path.open("w", encoding="utf-8") as f:
        for row in all_manifest_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if replace_original:
        backup_path = md_path.with_suffix(md_path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(md_path, backup_path)

        shutil.copy2(out_md_path, md_path)
        print(f"[REPLACE] original updated: {md_path}")
        print(f"[BACKUP]  backup: {backup_path}")

    print(f"[OK] {md_path}")
    print(f"     groups: {len(new_sections)}")
    print(f"     crop regions: {len(all_manifest_rows)}")
    print(f"     crop dir: {crop_dir}")
    print(f"     updated md: {out_md_path}")
    print(f"     manifest: {manifest_path}")


def find_semantic_group_files(root: Path) -> list[Path]:
    files: list[Path] = []

    for path in root.glob("*/semantic_groups.md"):
        if path.is_file():
            files.append(path)

    if (root / "semantic_groups.md").is_file():
        files.append(root / "semantic_groups.md")

    return sorted(set(files))


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Single semantic_groups.md file.",
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root directory containing per-document folders.",
    )

    parser.add_argument(
        "--padding",
        type=int,
        default=12,
        help="Padding around union bbox in pixels.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing crop images.",
    )

    parser.add_argument(
        "--replace-original",
        action="store_true",
        help="Replace semantic_groups.md with semantic_groups_with_crops.md. A .bak backup is created.",
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root used to resolve relative paths.",
    )

    args = parser.parse_args()

    project_root = args.project_root.resolve()

    if args.input is None and args.root is None:
        raise SystemExit("Please provide --input or --root")

    if args.input is not None:
        targets = [args.input]
    else:
        targets = find_semantic_group_files(args.root)

    if not targets:
        raise SystemExit("No semantic_groups.md files found.")

    for md_path in targets:
        if not md_path.exists():
            print(f"[WARN] missing: {md_path}")
            continue

        process_semantic_groups_file(
            md_path=md_path,
            padding=args.padding,
            overwrite=args.overwrite,
            replace_original=args.replace_original,
            project_root=project_root,
        )


if __name__ == "__main__":
    main()