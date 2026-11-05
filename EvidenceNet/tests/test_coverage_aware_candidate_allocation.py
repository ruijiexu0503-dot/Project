from EvidenceNet.scripts.replay_coverage_aware_candidate_allocation import (
    allocate, canonical_pair, deduplicate,
)


def candidate(source, target, score, rank, scope="same_document"):
    return {
        "source_id": source, "target_id": target, "raw_score": score,
        "rank_within_source": rank, "candidate_scope": scope,
    }


def synthetic_pool(n=1200):
    rows = []
    for index in range(n):
        source = f"s{index:04d}"
        rows.append(candidate(source, f"t{index:04d}", 1.0 - index / 10000, 1,
                              "same_document" if index % 2 else "cross_document"))
        # Keep the second row close enough that global allocation concentrates
        # multiple seats on early sources, unlike source-local allocation.
        rows.append(candidate(source, f"u{index:04d}", .9999 - index / 10000, 2,
                              "cross_document" if index % 2 else "same_document"))
    return rows


def test_canonical_dedup_keeps_highest_score_then_lexical_orientation():
    values = [candidate("b", "a", .8, 1), candidate("a", "b", .9, 2),
              candidate("d", "c", .7, 1), candidate("c", "d", .7, 2)]
    result = deduplicate(values)
    by_pair = {canonical_pair(row): row for row in result}
    assert by_pair[("a", "b")]["source_id"] == "a"
    assert by_pair[("c", "d")]["source_id"] == "c"
    assert all(row["directed_rows_for_pair"] == 2 for row in result)


def test_equal_budget_determinism_source_coverage_and_no_gold_fields():
    pool = synthetic_pool()
    first, _ = allocate(pool)
    second, _ = allocate(list(reversed(pool)))
    for policy in first:
        assert len(first[policy]) == 1088
        assert [canonical_pair(x) for x in first[policy]] == [canonical_pair(x) for x in second[policy]]
        assert len({canonical_pair(x) for x in first[policy]}) == 1088
        assert not ({"question_id", "gold_id", "oracle_target"} & set(first[policy][0]))
    assert len({row["source_id"] for row in first["A1_source_local"]}) == 1088
    assert len({row["source_id"] for row in first["A1_source_local"]}) > len(
        {row["source_id"] for row in first["A0_global"]})


def test_lane_aware_has_fixed_explicit_lane_budget():
    policies, _ = allocate(synthetic_pool())
    selected = policies["A3_lane_aware"]
    assert sum(row["candidate_scope"] == "same_document" for row in selected) == 544
    assert sum(row["candidate_scope"] == "cross_document" for row in selected) == 544
