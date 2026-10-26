from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from edge_text_views import render_readable, source_sentence_spans


def quotes(raw, max_chars=800):
    return [raw[lo:hi] for lo, hi in source_sentence_spans(raw, max_chars)]


def assert_complete_source_coverage(raw, max_chars=800):
    spans = source_sentence_spans(raw, max_chars)
    previous = 0
    for lo, hi in spans:
        assert previous <= lo < hi <= len(raw)
        assert not raw[previous:lo].strip()
        assert raw[lo:hi] == raw[lo:hi].strip()
        previous = hi
    assert not raw[previous:].strip()


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_soft_wrap_has_exact_offsets_and_does_not_break_a_sentence(newline):
    first = f"The model captures long-range{newline}temporal dependencies efficiently."
    raw = " \t" + first + f"{newline}Another sentence is independent.  "
    spans = source_sentence_spans(raw, max_chars=1)
    assert spans[0] == (2, 2 + len(first))
    assert quotes(raw, 1) == [first, "Another sentence is independent."]
    assert render_readable(first) == "The model captures long-range temporal dependencies efficiently."
    assert_complete_source_coverage(raw, 1)


def test_hyphen_wrap_preserves_hyphen_without_guessing_spelling():
    raw = "We model spatio-\ntemporal structure with predic-\r\ntion methods."
    assert quotes(raw, 1) == [raw]
    assert render_readable(raw) == "We model spatio-temporal structure with predic-tion methods."
    assert "\n" in raw


def test_short_paragraphs_never_merge_even_when_below_packing_budget():
    raw = "First complete paragraph.\r\n \t\r\nYes.\r\n\r\nLast tiny block"
    assert quotes(raw) == ["First complete paragraph.", "Yes.", "Last tiny block"]
    assert_complete_source_coverage(raw)


def test_list_items_are_independent_and_continuations_remain_with_item():
    raw = (
        "Introduction with a claim.\n"
        "• First item spans\n  two physical lines. Still first.\n"
        "• Second.\n"
        "1. Numbered claim\nhas a continuation.\n"
        "2. Next numbered claim.\n"
        "(a) Parenthesized item.\n"
        "b) Lettered item."
    )
    assert quotes(raw) == [
        "Introduction with a claim.",
        "• First item spans\n  two physical lines. Still first.",
        "• Second.",
        "1. Numbered claim\nhas a continuation.",
        "2. Next numbered claim.",
        "(a) Parenthesized item.",
        "b) Lettered item.",
    ]
    assert_complete_source_coverage(raw, 1)


def test_adjacent_complete_sentences_pack_without_crossing_paragraph():
    raw = "One is true. Two is false. Three is unknown.\n\nFourth is separate."
    assert quotes(raw, 27) == [
        "One is true. Two is false.",
        "Three is unknown.",
        "Fourth is separate.",
    ]
    assert_complete_source_coverage(raw, 27)


def test_long_single_sentence_is_never_truncated_or_split_midword():
    raw = "Unbroken " + "longword " * 120 + "ends here. Short tail."
    result = quotes(raw)
    assert result == [raw[:raw.index(" Short tail.")], "Short tail."]
    assert len(result[0]) > 800
    assert_complete_source_coverage(raw)


@pytest.mark.parametrize("opener,closer", [
    ("$", "$"), ("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]"),
    (r"\begin{aligned}", r"\end{aligned}"),
])
def test_formula_punctuation_and_blank_lines_cannot_split_formula(opener, closer):
    formula = opener + "x = 1. y = 2.\n\n- z = 3. " + "q + " * 230 + closer
    raw = "The formula is " + formula + ". Another sentence."
    assert quotes(raw) == [raw[:raw.index(" Another sentence.")], "Another sentence."]
    assert_complete_source_coverage(raw)


def test_unclosed_math_keeps_damaged_source_instead_of_splitting_it():
    raw = r"Observe $x. Next fragment." + "\n\n- Still uncertain"
    assert quotes(raw, 1) == [raw]


@pytest.mark.parametrize("raw", ["", " \t", "\n \r\n\t\r\n"])
def test_empty_or_whitespace_returns_no_spans(raw):
    assert source_sentence_spans(raw) == []
    assert render_readable(raw) == ""


def test_abbreviations_initials_decimals_and_german_dates():
    first = "Dr. Müller, z. B. mit Prof. A. Meyer, zeigt Abb. 2 am 20. Oktober mit 3.14 Punkten."
    second = "See Fig. 3, Eq. 2, e.g. a result by Smith et al. for more detail."
    raw = first + " " + second + " Eine neue Aussage folgt."
    assert quotes(raw, 1) == [first, second, "Eine neue Aussage folgt."]
    assert_complete_source_coverage(raw, 1)


def test_german_unicode_punctuation_and_readable_structure():
    raw = "„Größere Abstände helfen!“\r\n„Ähnliche Werte auch?“\r\n\r\n• Größen-\r\nordnung bleibt."
    assert quotes(raw, 1) == ["„Größere Abstände helfen!“", "„Ähnliche Werte auch?“", "• Größen-\r\nordnung bleibt."]
    assert render_readable(raw) == "„Größere Abstände helfen!“ „Ähnliche Werte auch?“\n\n• Größen-ordnung bleibt."
    assert_complete_source_coverage(raw, 1)


@pytest.mark.parametrize("limit", [0, -1, True, 2.5])
def test_invalid_packing_budget_is_rejected(limit):
    with pytest.raises(ValueError):
        source_sentence_spans("Text.", limit)
