from __future__ import annotations

import re

TERMINAL = re.compile(r'[.!?][\]\)\}"\'’”]*$')
TRAILING = re.compile(r"\b(?:a|an|the|and|or|but|of|to|in|on|at|for|from|with|by|as|that|which|is|are|was|were)$", re.I)


def completeness(text: str):
    stripped = text.rstrip()
    if not stripped: return False, True, "empty_text"
    if re.search(r"\w-$", stripped): return False, True, "ends_with_hyphenated_word"
    if TRAILING.search(stripped): return False, True, "ends_with_unfinished_phrase"
    if not TERMINAL.search(stripped): return False, True, "does_not_end_with_terminal_punctuation"
    return True, False, None


def continuation_confidence(left: dict, right: dict):
    if not left.get("possible_continuation"): return None
    text = right.get("plain_text", "").lstrip()
    if not text or not text[0].islower(): return None
    cross = left.get("page_ids") != right.get("page_ids")
    reason = "unfinished_sentence_followed_by_lowercase_continuation"
    return (0.93 if cross else 0.90), reason

