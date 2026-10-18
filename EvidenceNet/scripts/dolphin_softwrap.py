#!/usr/bin/env python3
"""Source-mapped retrieval views that distinguish Dolphin wraps from structure."""

from __future__ import annotations

import re

from run_node_context_edges import tokens


WRAP_HYPHEN = re.compile(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)")
BLANK_BREAK = re.compile(r"\r?\n[ \t]*\r?\n+")
SENTENCE_END = re.compile(r"[.!?](?:[\"'’”\)\]]+)?(?=\s|$)")
ABBREVIATIONS = {"fig", "eq", "ref", "refs", "dr", "mr", "mrs", "prof", "vs", "e.g", "i.e"}


def render_softwrap(raw: str, dehyphenate: bool) -> str:
    """Create a retrieval-only rendering; the source quote remains untouched."""
    replacement = "" if dehyphenate else "-"
    value = WRAP_HYPHEN.sub(replacement, raw)
    value = re.sub(r"[ \t]*\r?\n[ \t]*", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def structural_blocks(text: str) -> list[tuple[int, int]]:
    """Blank lines are structural; a single newline is only a soft wrap."""
    spans, start = [], 0
    for match in BLANK_BREAK.finditer(text):
        span = _trim_span(text, start, match.start())
        if span:
            spans.append(span)
        start = match.end()
    span = _trim_span(text, start, len(text))
    if span:
        spans.append(span)
    return spans


def _is_abbreviation(text: str, period: int) -> bool:
    prefix = text[max(0, period - 12):period]
    match = re.search(r"([A-Za-z](?:[A-Za-z.]*)?)$", prefix)
    token = match.group(1).casefold().rstrip(".") if match else ""
    return token in ABBREVIATIONS or (len(token) == 1 and token.isalpha())


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Recover sentence windows across single newlines with exact raw offsets."""
    result = []
    for block_start, block_end in structural_blocks(text):
        start = block_start
        for match in SENTENCE_END.finditer(text, block_start, block_end):
            if text[match.start()] == "." and _is_abbreviation(text, match.start()):
                continue
            span = _trim_span(text, start, match.end())
            if span:
                result.append(span)
            start = match.end()
        tail = _trim_span(text, start, block_end)
        if tail:
            result.append(tail)

    # Tiny fragments are usually abbreviation/list artefacts, not useful claims.
    merged = []
    for span in result:
        if merged and len(tokens(text[span[0]:span[1]])) < 4:
            merged[-1] = (merged[-1][0], span[1])
        else:
            merged.append(span)
    return merged


def retrieval_spans(text: str, maximum_tokens: int = 144) -> list[tuple[int, int]]:
    """Single and adjacent recovered sentences; never split on a single newline."""
    sentences = sentence_spans(text)
    spans = list(sentences)
    for index in range(len(sentences) - 1):
        if BLANK_BREAK.search(text[sentences[index][1]:sentences[index + 1][0]]):
            continue
        combined = (sentences[index][0], sentences[index + 1][1])
        if len(tokens(render_softwrap(text[combined[0]:combined[1]], True))) <= maximum_tokens:
            spans.append(combined)
    if not sentences:
        spans.extend(structural_blocks(text))
    return sorted(set(spans))


def make_views(nodes: list[dict], policies: dict) -> tuple[list[dict], dict]:
    views, counters = [], {"soft_wraps": 0, "hyphen_wraps": 0, "blank_breaks": 0}
    for node in sorted(nodes, key=lambda item: item["id"]):
        allowed = {(m["member_id"], m["kind"]) for m in policies[node["id"]]["members"] if m["eligible"]}
        for member in node.get("members", []):
            if (member["id"], member["kind"]) not in allowed:
                continue
            text = str(member.get("text") or "")
            if not text.strip():
                continue
            counters["hyphen_wraps"] += len(WRAP_HYPHEN.findall(text))
            counters["blank_breaks"] += len(BLANK_BREAK.findall(text))
            counters["soft_wraps"] += len(re.findall(r"(?<!\n)\n(?!\n)", text))
            for lo, hi in retrieval_spans(text):
                quote = text[lo:hi]
                variants = [("dehyphenated", render_softwrap(quote, True))]
                if WRAP_HYPHEN.search(quote):
                    variants.append(("hyphen_preserved", render_softwrap(quote, False)))
                for variant, rendered in variants:
                    token_count = len(tokens(rendered))
                    if token_count < 4 or token_count > 144:
                        continue
                    views.append({
                        "view_id": f"SOFT_{len(views):06d}", "node_id": node["id"],
                        "article_id": node["article_id"], "member_id": member["id"],
                        "member_kind": member["kind"], "kind": "dolphin_softwrap_claim",
                        "char_start": lo, "char_end": hi, "quote": quote,
                        "retrieval_text": rendered, "softwrap_variant": variant,
                        "source_status": "ORIGINAL_TEXT_SOFTWRAP_VIEW" if member["kind"] == "atom"
                            else "GENERATED_DESCRIPTION_FOR_RETRIEVAL_ONLY",
                    })
    return views, counters
