import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_vldocir_ap import average_precision


def test_full_ap_rewards_each_relevant_rank_and_removes_duplicates():
    assert average_precision(['x','a','a','y','b'],{'a','b'})==pytest.approx((1/2+2/4)/2)


def test_truncated_ap_uses_all_gold_and_exposes_alternate_denominator():
    assert average_precision(['a','b','c','d'],{'a','b','c','d'},2)==.5
    assert average_precision(['a','b','c','d'],{'a','b','c','d'},2,True)==1.


def test_missed_relevance_and_empty_gold_are_not_silent_success():
    assert average_precision(['x','y'],{'a'})==0
    with pytest.raises(ValueError):average_precision(['x'],set())
