from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dolphin_softwrap import render_softwrap, retrieval_spans


def test_single_newline_does_not_split_sentence_and_offsets_remain_raw():
    raw = "The model captures long-range\ntemporal dependencies efficiently. Another independent claim follows after it."
    spans = retrieval_spans(raw)
    first = next((lo, hi) for lo, hi in spans if raw[lo:hi].endswith("efficiently."))
    quote = raw[first[0]:first[1]]
    assert "\n" in quote
    assert render_softwrap(quote, True) == "The model captures long-range temporal dependencies efficiently."


def test_blank_line_is_a_hard_structural_boundary():
    raw = "First paragraph has a claim.\n\nSecond paragraph has another claim."
    assert all(not (lo < raw.index("\n\n") < hi) for lo, hi in retrieval_spans(raw))


def test_hyphen_wrap_has_safe_parallel_renderings():
    raw = "spatio-\ntemporal dependency and convolution-\nbased model"
    assert render_softwrap(raw, True) == "spatiotemporal dependency and convolutionbased model"
    assert render_softwrap(raw, False) == "spatio-temporal dependency and convolution-based model"
