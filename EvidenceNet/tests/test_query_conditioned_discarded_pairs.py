from EvidenceNet.scripts.replay_query_conditioned_discarded_pairs import (
    ARMS, attach_scores, canonical, rank_and_select,
)


def row(source, target, pair_score, local_rank):
    return {
        "source_id": source, "target_id": target, "raw_score": pair_score,
        "rank_within_source": local_rank, "candidate_scope": "cross_document",
        "graph_context_used": False,
    }


def enriched():
    values = [row("s1", "t1", .9, 4), row("s1", "t2", .7, 1),
              row("s2", "t1", .8, 2), row("s2", "t3", .6, 1)]
    scores = {"s1": .95, "s2": .9, "t1": .3, "t2": .8, "t3": .7, "n1": .85}
    return attach_scores(values, {"s1": 1, "s2": 2}, scores, {"s1": {"n1"}, "s2": set()})


def test_arms_are_deterministic_and_target_deduplicated():
    values = enriched()
    for arm in ARMS:
        first, _ = rank_and_select(values, arm, 3)
        second, _ = rank_and_select(list(reversed(values)), arm, 3)
        assert [(x["source_id"], x["target_id"]) for x in first] == [
            (x["source_id"], x["target_id"]) for x in second]
        assert len({x["target_id"] for x in first}) == len(first) == 3


def test_query_target_arm_differs_from_query_agnostic_pair_score():
    values = enriched()
    pair, _ = rank_and_select(values, "B0_pair_score", 1)
    query, _ = rank_and_select(values, "Q0_query_target", 1)
    assert pair[0]["target_id"] == "t1"
    assert query[0]["target_id"] == "t2"


def test_no_gold_fields_enter_ranking_and_canonical_is_undirected():
    values = enriched()
    assert canonical("b", "a") == ("a", "b")
    forbidden = {"gold_id", "gold_evidence", "oracle_target", "recovered"}
    assert all(not (forbidden & set(value)) for value in values)
