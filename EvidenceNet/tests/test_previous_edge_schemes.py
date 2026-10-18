from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from compare_previous_edge_schemes import (
    previous_prompt_prefix, coverage, whole_node_candidates, binary_metrics,
)


def case(key, label, a, b):
    return dict(case_id=key, suite_case_id=key, relation='METHOD_CORRESPONDENCE', label=label,
                A=dict(node_id=a), B=dict(node_id=b))


def test_prior_prompt_is_reused_without_functional_taxonomy():
    prompt = previous_prompt_prefix()
    assert 'METHOD_CORRESPONDENCE requires the same specific described mechanism' in prompt
    assert 'Generated visual descriptions are not supplied as proof' in prompt
    assert 'No causal, entails, supports, or contradicts edge is permitted' in prompt
    assert '"A_evidence_ids":[]' in prompt


def test_old_corpus_missing_endpoints_are_unavailable_not_missed():
    cases = [case('p', 'POSITIVE', 'a', 'b'), case('n', 'NEGATIVE', 'a', 'c'),
             case('new', 'POSITIVE', 'a', 'outside')]
    summary, detail = coverage(cases, [dict(source='b', target='a')], {'a', 'b', 'c'})
    assert summary['POSITIVE_total'] == summary['POSITIVE_retrieved'] == 1
    assert summary['NEGATIVE_total'] == 1 and summary['NEGATIVE_retrieved'] == 0
    assert summary['unavailable_cases'] == 1
    assert len(detail) == 2


def test_original_dense_policy_respects_degree_and_scope_limits():
    nodes = {f'a{i}': dict(document='A') for i in range(20)}
    nodes.update({f'b{i}': dict(document='B') for i in range(20)})
    vectors = np.eye(40, dtype=np.float32)
    pairs, _ = whole_node_candidates(nodes, vectors)
    assert len(pairs) == 12 + 12 + 24
    from collections import Counter
    for da, db, cap in [('A', 'A', 2), ('B', 'B', 2), ('A', 'B', 3)]:
        selected = [p for p in pairs if {nodes[p['source']]['document'], nodes[p['target']]['document']} == {da, db}]
        degree = Counter(n for p in selected for n in (p['source'], p['target']))
        assert max(degree.values()) <= cap


def test_invalid_missing_and_uncertain_are_not_silent_negatives():
    score = binary_metrics({'tp': True, 'fp': True, 'tn': False, 'uncertain': None},
                           dict(tp=True, fp=False, tn=False, uncertain=True, missing=True))
    assert score['tp'] == score['fp'] == score['tn'] == 1
    assert score['missing'] == score['invalid_or_uncertain'] == 1
    assert score['precision_valid_only'] == 0.5
    assert score['correct'] == 2
