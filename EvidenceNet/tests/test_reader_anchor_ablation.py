import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_reader_anchor_ablation import pack, render, sha, verify_anchor


class CharacterTokenizer:
    def encode(self, text, add_special_tokens=False):
        return SimpleNamespace(ids=list(text))


def packet(doc, text, pid='p'):
    return {'packet_id': pid, 'page': [doc, '1'], 'text': text, 'member_sha256': sha(text)}


def test_budget_includes_labels_and_never_truncates_source():
    long = packet('a', 'x' * 1000, 'long')
    small = packet('a', 'Full sentence.', 'small')
    limit = len(render([small]))
    chosen, dropped = pack([long, small], limit, CharacterTokenizer())
    assert chosen == [small]
    assert len(render(chosen)) == limit
    assert dropped[0]['reason'] == 'complete_member_over_remaining_budget'
    assert not pack([small], limit - 1, CharacterTokenizer())[0]


def test_duplicate_scope_preserves_different_document_evidence():
    a, b = packet('a', 'Same words.', 'a'), packet('b', 'Same words.', 'b')
    chosen, dropped = pack([a, dict(a), b], 1000, CharacterTokenizer())
    assert chosen == [a, b]
    assert dropped[0]['reason'] == 'same_page_exact_duplicate'
    assert 'Document D1' in render(chosen) and 'Document D2' in render(chosen)


def test_source_anchor_integrity_rejects_changed_text_hash_or_offsets():
    text = 'An original sentence. Another sentence.'
    members = {('n', 'm'): {'text': text}}
    span = {'node_id': 'n', 'member_id': 'm', 'span_id': 's', 'char_start': 3,
            'char_end': 11, 'text': text[3:11], 'member_sha256': sha(text)}
    assert verify_anchor(span, members)['text'] == text
    for update in ({'text': 'invented'}, {'member_sha256': 'bad'}, {'char_start': -1}):
        with pytest.raises(ValueError):
            verify_anchor({**span, **update}, members)
