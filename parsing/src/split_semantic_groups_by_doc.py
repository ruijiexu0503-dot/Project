#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Split semantic_groups.md by document.

Input:
  data/processed_vlm_md/semantic_groups.md

Output:
  data/processed_vlm_md_by_doc/
    ├── index.md
    ├── <doc_id>/
    │   └── semantic_groups.md
    └── ...

This script:
- does NOT rerun VLM
- does NOT modify semantic group content
- only reorganizes existing semantic groups by doc_id
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from collections import defaultdict


def safe_name(name: str) -> str:
    """
    Convert doc_id to a safe folder name.
    """
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_") or "unknown_doc"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def split_semantic_group_sections(md: str) -> list[str]:
    """
    Your semantic_groups.md is written like:

      # Semantic Groups

      # doc_p0001_g0000
      ...

      ---

      # doc_p0001_g0001
      ...

      ---

    So we split by markdown horizontal separators.

    This preserves each group section exactly.
    """
    parts = re.split(r"\n\s*---\s*\n", md)

    sections = []

    for part in parts:
        part = part.strip()

        if not part:
            continue

        # Drop global title section such as "# Semantic Groups"
        lines = [x.strip() for x in part.splitlines() if x.strip()]
        if len(lines) <= 2 and lines[0].startswith("# Semantic Groups"):
            continue

        # Keep only real group sections with doc_id metadata.
        if re.search(r"(?m)^doc_id:\s*", part):
            sections.append(part)

    return sections


def extract_doc_id(section: str) -> str:
    """
    Extract:
      doc_id: climate_change_with_ml_xxxxxx
    """
    m = re.search(r"(?m)^doc_id:\s*(.+?)\s*$", section)

    if not m:
        return "unknown_doc"

    doc_id = m.group(1).strip()

    if not doc_id or doc_id.lower() in {"none", "null"}:
        return "unknown_doc"

    return doc_id


def extract_page_no(section: str) -> int:
    """
    Extract page_no for sorting.
    """
    m = re.search(r"(?m)^page_no:\s*(\d+)\s*$", section)
    if not m:
        return 10**9
    return int(m.group(1))


def extract_local_order(section: str) -> int:
    """
    Extract local_order for sorting within page.
    """
    m = re.search(r"(?m)^local_order:\s*(\d+)\s*$", section)
    if not m:
        return 10**9
    return int(m.group(1))


def extract_group_id(section: str) -> str:
    """
    Extract heading:
      # group_id
    """
    m = re.search(r"(?m)^#\s+(.+?)\s*$", section)
    if not m:
        return "unknown_group"
    return m.group(1).strip()


def group_sections_by_doc(sections: list[str]) -> dict[str, list[str]]:
    grouped = defaultdict(list)

    for sec in sections:
        doc_id = extract_doc_id(sec)
        grouped[doc_id].append(sec)

    # Sort each document by page_no, local_order, group_id.
    for doc_id in grouped:
        grouped[doc_id].sort(
            key=lambda sec: (
                extract_page_no(sec),
                extract_local_order(sec),
                extract_group_id(sec),
            )
        )

    return dict(grouped)


def write_doc_semantic_groups(
    *,
    out_path: Path,
    doc_id: str,
    sections: list[str],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Semantic Groups - {doc_id}\n\n")
        f.write(f"doc_id: {doc_id}\n")
        f.write(f"num_groups: {len(sections)}\n\n")
        f.write("---\n\n")

        for sec in sections:
            f.write(sec.strip())
            f.write("\n\n---\n\n")


def write_index(
    *,
    out_path: Path,
    grouped: dict[str, list[str]],
) -> None:
    lines = []
    lines.append("# Semantic Groups by Document")
    lines.append("")

    total_groups = sum(len(v) for v in grouped.values())

    lines.append(f"num_documents: {len(grouped)}")
    lines.append(f"num_semantic_groups: {total_groups}")
    lines.append("")
    lines.append("## Documents")
    lines.append("")

    for doc_id in sorted(grouped.keys()):
        folder = safe_name(doc_id)
        count = len(grouped[doc_id])
        lines.append(f"- [{doc_id}]({folder}/semantic_groups.md) — {count} groups")

    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed_vlm_md/semantic_groups.md"),
        help="Aggregated semantic_groups.md file.",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/processed_vlm_md_by_doc"),
        help="Output directory.",
    )

    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Input file not found: {args.input}")

    md = read_text(args.input)
    sections = split_semantic_group_sections(md)

    if not sections:
        raise RuntimeError(
            f"No semantic group sections found in {args.input}. "
            "Check whether the file contains lines like 'doc_id: ...'."
        )

    grouped = group_sections_by_doc(sections)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    for doc_id, doc_sections in sorted(grouped.items()):
        doc_folder = args.out_dir / safe_name(doc_id)

        write_doc_semantic_groups(
            out_path=doc_folder / "semantic_groups.md",
            doc_id=doc_id,
            sections=doc_sections,
        )

        print(f"[OK] {doc_id}: {len(doc_sections)} groups")

    write_index(
        out_path=args.out_dir / "index.md",
        grouped=grouped,
    )

    print()
    print(f"Input: {args.input}")
    print(f"Output directory: {args.out_dir}")
    print(f"Documents: {len(grouped)}")
    print(f"Semantic groups: {sum(len(v) for v in grouped.values())}")
    print(f"Index: {args.out_dir / 'index.md'}")


if __name__ == "__main__":
    main()