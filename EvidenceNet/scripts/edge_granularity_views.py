"""Immutable source views for the fixed-pair text granularity experiment.

Only view boundaries differ across arms. Retrieval rendering, original source
anchors, and sentence-complete verification context use the same policy.
"""
from __future__ import annotations

import hashlib
import json
import re

import numpy as np

from edge_text_views import source_sentence_spans
from run_hierarchical_edge_retrieval import clean


ARMS = ("window96", "physical_line", "sentence")
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def _member(nodes: dict, node_id: str, member_id: str) -> dict:
    node = nodes[node_id]
    if node["id"] != node_id:
        raise ValueError("Node dictionary key does not match its source ID")
    matches = [member for member in node["members"] if member["id"] == member_id]
    if len(matches) != 1:
        raise ValueError("Expected one source member: " + node_id + "/" + member_id)
    member = matches[0]
    if member.get("kind") != "atom" or member.get("type") != "text":
        raise ValueError("Granularity views require original atom/text members")
    if not isinstance(member.get("text"), str):
        raise TypeError("Source member text must be a string")
    return member


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _trim(raw: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and raw[start].isspace():
        start += 1
    while start < end and raw[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _spans(raw: str, arm: str) -> list[tuple[int, int]]:
    if arm == "sentence":
        return source_sentence_spans(raw, max_chars=1)
    if arm == "physical_line":
        spans = []
        start = 0
        for newline in _LINE_BREAK.finditer(raw):
            span = _trim(raw, start, newline.start())
            if span is not None:
                spans.append(span)
            start = newline.end()
        tail = _trim(raw, start, len(raw))
        if tail is not None:
            spans.append(tail)
        return spans
    words = list(re.finditer(r"\S+", raw))
    spans = []
    for start in range(0, len(words), 72):
        window = words[start:start + 96]
        spans.append((window[0].start(), window[-1].end()))
        if start + 96 >= len(words):
            break
    return spans


def make_views(nodes: dict, member_keys: set[tuple[str, str]], arm: str) -> list[dict]:
    """Slice only explicitly selected members; never edit or drop short text.

    ``word_count`` counts the consistently rendered retrieval text. The fixed
    window boundaries are based on source whitespace tokens, as in the existing
    96-word retrieval arm, but without its minimum-four-token filter.
    """
    if arm not in ARMS:
        raise ValueError("Unknown granularity arm: " + str(arm))
    views = []
    for node_id, member_id in sorted(member_keys):
        member = _member(nodes, node_id, member_id)
        raw = member["text"]
        digest = _sha(raw)
        for start, end in _spans(raw, arm):
            quote = raw[start:end]
            rendered = clean(quote, member.get("role"))
            identity = json.dumps(
                [arm, node_id, member_id, digest, start, end],
                ensure_ascii=False, separators=(",", ":"),
            )
            views.append({
                "view_id": "GV_" + _sha(identity),
                "node_id": node_id, "member_id": member_id,
                "member_sha256": digest, "char_start": start, "char_end": end,
                "quote": quote, "retrieval_text": rendered,
                "word_count": len(rendered.split()), "arm": arm,
            })
    return views


def context_for_view(view: dict, nodes: dict) -> dict:
    """Complete all touched sentences and include one sentence on either side.

    Context may cross paragraphs but never member boundaries. Formula spans are
    protected by the shared sentence segmenter. No token/character truncation is
    performed, including for long or malformed source formulas.
    """
    member = _member(nodes, view["node_id"], view["member_id"])
    raw = member["text"]
    start, end = view["char_start"], view["char_end"]
    if (type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(raw)):
        raise ValueError("Invalid original source offsets")
    if view["member_sha256"] != _sha(raw) or view["quote"] != raw[start:end]:
        raise ValueError("View no longer matches its immutable original source")
    sentences = source_sentence_spans(raw, max_chars=1)
    touched = [i for i, (lo, hi) in enumerate(sentences) if lo < end and start < hi]
    if not touched:
        raise ValueError("View does not touch nonempty source text")
    lo = sentences[max(0, touched[0] - 1)][0]
    hi = sentences[min(len(sentences) - 1, touched[-1] + 1)][1]
    return {
        "kind": "ORIGINAL_TEXT", "node_id": view["node_id"],
        "member_id": view["member_id"], "member_sha256": view["member_sha256"],
        "char_start": lo, "char_end": hi, "quote": raw[lo:hi],
    }


def _overlapping(a: dict, b: dict) -> bool:
    if (a["node_id"], a["member_id"]) != (b["node_id"], b["member_id"]):
        return False
    overlap = max(0, min(a["char_end"], b["char_end"]) - max(a["char_start"], b["char_start"]))
    minimum = min(a["char_end"] - a["char_start"], b["char_end"] - b["char_start"])
    if minimum <= 0:
        raise ValueError("Matching requires nonempty source spans")
    return overlap / minimum >= 0.5


def _vectors(views: list[dict], vectors_by_id: dict[str, np.ndarray]) -> list[np.ndarray]:
    if len({view["view_id"] for view in views}) != len(views):
        raise ValueError("Duplicate view IDs in one endpoint")
    vectors = [np.asarray(vectors_by_id[view["view_id"]]) for view in views]
    for vector in vectors:
        if vector.ndim != 1 or not len(vector) or not np.isfinite(vector).all():
            raise ValueError("Expected finite one-dimensional embedding vectors")
        if not np.isclose(np.linalg.norm(vector), 1.0, atol=1e-3, rtol=1e-3):
            raise ValueError("Expected L2-normalized embedding vectors")
    return vectors


def top_matches(views_a: list[dict], views_b: list[dict],
                vectors_by_id: dict[str, np.ndarray], limit: int = 2) -> list[dict]:
    """Rank dot products with stable ID ties and two-sided overlap suppression.

    A new pair is redundant only when both sides overlap a previously selected
    pair by at least half of the shorter source span. One-to-many matches remain
    possible when just one side overlaps. The vectors must already be normalized.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError("Match limit must be a nonnegative integer")
    if not views_a or not views_b or limit == 0:
        return []
    vectors_a, vectors_b = _vectors(views_a, vectors_by_id), _vectors(views_b, vectors_by_id)
    if len({vector.shape for vector in vectors_a + vectors_b}) != 1:
        raise ValueError("Embedding dimensions differ")
    scored = [
        (float(np.dot(vector_a, vector_b)), a["view_id"], b["view_id"], a, b)
        for a, vector_a in zip(views_a, vectors_a)
        for b, vector_b in zip(views_b, vectors_b)
    ]
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = []
    for score, aid, bid, a, b in scored:
        if any(_overlapping(a, old_a) and _overlapping(b, old_b)
               for _, _, _, old_a, old_b in selected):
            continue
        selected.append((score, aid, bid, a, b))
        if len(selected) == limit:
            break
    return [{"A_view_id": aid, "B_view_id": bid, "score": score}
            for score, aid, bid, _, _ in selected]
