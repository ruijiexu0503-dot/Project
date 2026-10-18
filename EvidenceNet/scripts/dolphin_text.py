#!/usr/bin/env python3
"""Lossless raw text plus a layout-normalized semantic view for Dolphin output."""
from __future__ import annotations

import re


BLANK_BREAK = re.compile(r"\n[ \t]*\n+")
NEWLINE = re.compile(r"\r\n|\r|\n")
LIST_START = re.compile(r"^(?:[-*•▪◦]|\d+[.)]|\([A-Za-z0-9]+\))\s+")
PRESERVE_LINE_LABELS = {"tab", "table", "formula", "equation"}
POLICY = "dolphin_softwrap_semantic_v2"

JOIN_SPACE = "JOIN_SPACE"
JOIN_HYPHEN = "JOIN_HYPHEN"
KEEP_LIST = "KEEP_LIST"
KEEP_LAYOUT = "KEEP_LAYOUT"
KEEP_PARAGRAPH = "KEEP_PARAGRAPH"


def _line_around(value: str, match: re.Match) -> tuple[str, str]:
    left_start = max(value.rfind("\n", 0, match.start()), value.rfind("\r", 0, match.start())) + 1
    right_ends = [position for position in (value.find("\n", match.end()),
                                             value.find("\r", match.end())) if position >= 0]
    right_end = min(right_ends) if right_ends else len(value)
    return value[left_start:match.start()], value[match.end():right_end]


def classify_line_break(left: str, right: str, layout_label: str | None = None) -> str:
    """Classify a Dolphin physical line break without consulting model output."""
    if str(layout_label or "").casefold() in PRESERVE_LINE_LABELS:
        return KEEP_LAYOUT
    if not left.strip() or not right.strip():
        return KEEP_PARAGRAPH
    if LIST_START.match(right.strip()):
        return KEEP_LIST
    if left.rstrip().endswith("-"):
        return JOIN_HYPHEN
    return JOIN_SPACE


def line_break_decisions(raw: str, layout_label: str | None = None) -> list[dict]:
    """Return exact source offsets and an auditable decision for every newline."""
    value = str(raw or "")
    decisions = []
    for index, match in enumerate(NEWLINE.finditer(value)):
        left, right = _line_around(value, match)
        decisions.append({
            "break_index": index,
            "char_start": match.start(),
            "char_end": match.end(),
            "decision": classify_line_break(left, right, layout_label),
        })
    return decisions


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


def normalize_dolphin_text_with_decisions(
        raw: str, layout_label: str | None = None) -> tuple[str, list[dict]]:
    """Build the semantic view and retain the decision for every source break."""
    return normalize_dolphin_text(raw, layout_label), line_break_decisions(raw, layout_label)


def semantic_fragment_text(fragment: dict) -> str:
    """Read the semantic view with backward compatibility for frozen inputs."""
    value = fragment.get("semantic_text")
    return value if isinstance(value, str) else str(fragment.get("text") or "")


def atom_text(atom: dict, semantic: bool = True) -> str:
    field = semantic_fragment_text if semantic else lambda f: str(f.get("text") or "")
    return "\n".join(field(fragment) for fragment in atom.get("text_fragments", []))
