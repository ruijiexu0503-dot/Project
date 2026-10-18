#!/usr/bin/env python3
"""Lossless raw text plus a layout-normalized semantic view for Dolphin output."""
from __future__ import annotations

import re


BLANK_BREAK = re.compile(r"\n[ \t]*\n+")
LIST_START = re.compile(r"^(?:[-*•▪◦]|\d+[.)]|\([A-Za-z0-9]+\))\s+")
PRESERVE_LINE_LABELS = {"tab", "table", "formula", "equation"}
POLICY = "dolphin_softwrap_semantic_v1"


def normalize_dolphin_text(raw: str, layout_label: str | None = None) -> str:
    """Join physical line wraps without changing the source text or its offsets.

    Blank lines and explicit list rows remain boundaries. Tables and formulas keep
    their line layout. A wrap after a hyphen removes only surrounding whitespace,
    retaining the hyphen because it may be lexical (for example, spatio-temporal).
    """
    value = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    if str(layout_label or "").casefold() in PRESERVE_LINE_LABELS:
        return value.strip()
    paragraphs = BLANK_BREAK.split(value)
    rendered = []
    for paragraph in paragraphs:
        lines = [re.sub(r"[ \t]+", " ", line).strip()
                 for line in paragraph.split("\n") if line.strip()]
        if not lines:
            continue
        result = lines[0]
        for line in lines[1:]:
            if LIST_START.match(line):
                result += "\n" + line
            elif result.endswith("-"):
                result += line
            else:
                result += " " + line
        rendered.append(result)
    return "\n\n".join(rendered)


def semantic_fragment_text(fragment: dict) -> str:
    """Read the semantic view with backward compatibility for frozen inputs."""
    value = fragment.get("semantic_text")
    return value if isinstance(value, str) else str(fragment.get("text") or "")


def atom_text(atom: dict, semantic: bool = True) -> str:
    field = semantic_fragment_text if semantic else lambda f: str(f.get("text") or "")
    return "\n".join(field(fragment) for fragment in atom.get("text_fragments", []))
