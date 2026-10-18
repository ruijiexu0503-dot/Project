import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from replay_fact_source_matching import layout_norm
from run_fact_grounded_edges import validate_facts


def record(subject):
    return {'facts': [{'subject': subject, 'subject_kind': 'PROJECT',
                      'subject_evidence_id': 'N:T000', 'evidence_ids': ['N:T000'],
                      'predicate': 'was published', 'qualifiers': '', 'observation': ''}]}


def test_line_wrap_recovery_preserves_original_anchor():
    quote = 'Publication of the Open Sci-\nence Policy.'
    lookup = {'N:T000': {'kind': 'TEXT', 'quote': quote}}
    value = record('Open Science Policy')
    with pytest.raises(ValueError, match='subject_not_in_source'):
        validate_facts(value, lookup)
    bound = validate_facts(value, lookup, subject_normalizer=layout_norm)
    assert bound[0]['anchors'][0]['quote'] == quote
    assert lookup['N:T000']['quote'] == quote


@pytest.mark.parametrize('quote', ['Open Scientific Policy.', 'Open Sci- ence Policy.',
                                  'Open Science Framework.', 'Another project was published.'])
def test_unrelated_or_inline_hyphen_text_still_fails(quote):
    with pytest.raises(ValueError, match='subject_not_in_source'):
        validate_facts(record('Open Science Policy'), {'N:T000': {'kind': 'TEXT', 'quote': quote}},
                       subject_normalizer=layout_norm)


def test_inline_compound_and_units_are_preserved():
    assert layout_norm('U-platform 35-50 Hz') == 'u-platform 35-50 hz'
    assert layout_norm('3-\n5 Hz') == '3- 5 hz'
