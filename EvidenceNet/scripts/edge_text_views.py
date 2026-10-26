"""Readable text views and sentence windows with exact source offsets.

Only the derived view is normalized. Source spans always index the untouched
input, and ``max_chars`` is a packing target rather than a truncation limit.
"""

from __future__ import annotations

from bisect import bisect_right
import re

from dolphin_text import LIST_START, normalize_dolphin_text


_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_SENTENCE_END = re.compile(r"""[.!?]+(?:["'’”‘“»)\]]+)?(?=\s|$)""")
_MATH_OPEN = re.compile(r"(?<!\\)(?:\$\$|\$|\\\[|\\\(|\\begin\{([A-Za-z*]+)\})")
_LETTER_LIST = re.compile(r"^[A-Za-z][.)]\s+")
_ABBREVIATIONS = {
    "fig", "figs", "eq", "eqs", "ref", "refs", "dr", "mr", "mrs", "ms",
    "prof", "vs", "e.g", "i.e", "etc", "al", "no", "nos", "vol", "pp",
    "abb", "abs", "bzw", "ca", "vgl", "nr", "tab", "ggf", "bspw",
}
_MONTHS = {
    "januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
    "september", "oktober", "november", "dezember",
}


def render_readable(raw: str) -> str:
    """Join Dolphin soft wraps while retaining lexical/wrapped hyphens."""
    return normalize_dolphin_text(raw)


def _trim(raw: str, lo: int, hi: int) -> tuple[int, int] | None:
    while lo < hi and raw[lo].isspace():
        lo += 1
    while hi > lo and raw[hi - 1].isspace():
        hi -= 1
    return (lo, hi) if lo < hi else None


def _math_spans(raw: str) -> list[tuple[int, int]]:
    """Protect common TeX delimiters, including multi-line environments.

    An unclosed delimiter conservatively protects the rest of the member:
    creating an oversized span is preferable to splitting a damaged formula.
    """
    result = []
    position = 0
    while match := _MATH_OPEN.search(raw, position):
        opener = match.group()
        if opener.startswith(r"\begin"):
            closer = r"\end{" + match.group(1) + "}"
        else:
            closer = {"$": "$", "$$": "$$", r"\[": r"\]", r"\(": r"\)"}[opener]
        pattern = r"(?<!\\)" + re.escape(closer)
        if closer == "$":
            pattern += r"(?!\$)"
        closing = re.compile(pattern).search(raw, match.end())
        end = closing.end() if closing else len(raw)
        result.append((match.start(), end))
        position = end
    return result


def _inside(position: int, spans: list[tuple[int, int]], starts: list[int]) -> bool:
    index = bisect_right(starts, position) - 1
    return index >= 0 and position < spans[index][1]


def _list_marker(text: str) -> re.Match | None:
    return LIST_START.match(text) or _LETTER_LIST.match(text)


def _blocks(raw: str, math: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Respect paragraphs/list items without treating physical wraps as claims."""
    starts = [lo for lo, _ in math]
    result = []
    block_start = 0
    line_start = 0
    for line_end, next_start in [
        *((match.start(), match.end()) for match in _LINE_BREAK.finditer(raw)),
        (len(raw), len(raw)),
    ]:
        line = raw[line_start:line_end]
        content_start = line_start + len(line) - len(line.lstrip())
        protected = _inside(line_start, math, starts) or _inside(content_start, math, starts)
        if not protected:
            if not line.strip():
                span = _trim(raw, block_start, line_start)
                if span:
                    result.append(span)
                block_start = next_start
            elif _list_marker(line.lstrip()):
                span = _trim(raw, block_start, line_start)
                if span:
                    result.append(span)
                block_start = line_start
        line_start = next_start
    tail = _trim(raw, block_start, len(raw))
    if tail:
        result.append(tail)
    return result


def _abbreviation(raw: str, period: int, block_end: int) -> bool:
    prefix = raw[:period]
    match = re.search(r"([^\W\d_]+(?:\.[^\W\d_]+)*)$", prefix, flags=re.UNICODE)
    token = match.group(1).casefold() if match else ""
    if token in _ABBREVIATIONS or len(token) == 1 or "." in token:
        return True
    # German dates use an ordinal dot; decimal dots have no following whitespace
    # and are already excluded by _SENTENCE_END.
    if period and raw[period - 1].isdigit():
        following = re.match(r"\s*([^\W\d_]+)", raw[period + 1:block_end])
        if following and following.group(1).casefold() in _MONTHS:
            return True
    return False


def source_sentence_spans(raw: str, max_chars: int = 800) -> list[tuple[int, int]]:
    """Pack complete source sentences within each paragraph/list item.

    LF, CRLF and CR are physical wraps unless they introduce a blank line or a
    list item. Spans retain raw hyphens/newlines and never cross those structural
    boundaries. A single long sentence or formula may exceed ``max_chars``.
    No non-whitespace source content is dropped.
    """
    if not isinstance(raw, str):
        raise TypeError("raw must be a string")
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    math = _math_spans(raw)
    math_starts = [lo for lo, _ in math]
    result = []
    for lo, hi in _blocks(raw, math):
        sentences = []
        sentence_start = lo
        marker = _list_marker(raw[lo:hi])
        marker_end = lo + marker.end() if marker else lo
        for match in _SENTENCE_END.finditer(raw, lo, hi):
            period = match.start()
            if period < marker_end or _inside(period, math, math_starts):
                continue
            if raw[period] == "." and (
                match.group().startswith("..") or _abbreviation(raw, period, hi)
            ):
                continue
            span = _trim(raw, sentence_start, match.end())
            if span:
                sentences.append(span)
            sentence_start = match.end()
        tail = _trim(raw, sentence_start, hi)
        if tail:
            sentences.append(tail)
        packed = None
        for sentence in sentences:
            if packed is not None and sentence[1] - packed[0] <= max_chars:
                packed = (packed[0], sentence[1])
            else:
                if packed is not None:
                    result.append(packed)
                packed = sentence
        if packed is not None:
            result.append(packed)
    return result
