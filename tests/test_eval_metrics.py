import pytest

from eval.metrics import (
    Expected,
    citation_scores,
    first_hit_rank,
    full_coverage_rank,
    gate_sweep,
    keyword_correct,
    matches,
    mean_reciprocal_rank,
    paired_comparison,
    percentile,
    precision_at_k,
    recall_at_k,
    sign_test_p,
    wilson_interval,
)


def test_path_only_matches_any_section() -> None:
    e = Expected("a.md")
    assert matches(("a.md", None), e) and matches(("a.md", "X > Y"), e)
    assert not matches(("b.md", "X"), e)


def test_exact_section_does_not_match_children() -> None:
    e = Expected("a.md", section="Towers")
    assert matches(("a.md", "Towers"), e)
    assert not matches(("a.md", "Towers > Arrow"), e)


def test_section_prefix_matches_subtree_but_not_lookalikes() -> None:
    e = Expected("t.gd", section_prefix="Tower > upgrade")
    assert matches(("t.gd", "Tower > upgrade"), e)
    assert matches(("t.gd", "Tower > upgrade > inner"), e)
    assert not matches(("t.gd", "Tower > upgrade_cost"), e)  # different symbol, shared prefix
    assert not matches(("t.gd", None), e)


def test_first_hit_rank_is_one_based_and_any_expected_counts() -> None:
    got = [("x", None), ("a.md", "S"), ("b.md", "S")]
    assert first_hit_rank(got, [Expected("b.md"), Expected("a.md")]) == 2
    assert first_hit_rank(got, [Expected("zzz")]) is None
    assert first_hit_rank([], [Expected("a")]) is None


def test_recall_and_mrr() -> None:
    ranks = [1, 3, None, 2]
    assert recall_at_k(ranks, 1) == 0.25
    assert recall_at_k(ranks, 3) == 0.75
    assert mean_reciprocal_rank(ranks) == pytest.approx((1 + 1 / 3 + 0 + 1 / 2) / 4)


def test_paired_comparison_counts_wins_losses_ties_and_treats_missing_as_worst() -> None:
    baseline = [1, 5, None, 2, None]
    candidate = [1, 2, 4, 3, None]
    assert paired_comparison(baseline, candidate) == (2, 1, 2)


def test_precision_at_k() -> None:
    got = [("a", None), ("b", None), ("a", "S"), ("c", None)]
    assert precision_at_k(got, [Expected("a")], 4) == 0.5
    assert precision_at_k(got, [Expected("a")], 1) == 1.0
    assert precision_at_k([], [Expected("a")], 5) == 0.0


def test_keyword_correct_requires_every_group_any_alternative() -> None:
    groups = [["3", "three"], ["poison"]]
    assert keyword_correct("Poison stacks up to THREE times", groups)
    assert not keyword_correct("Poison stacks a few times", groups)
    assert not keyword_correct("Up to 3 times", groups)
    assert keyword_correct("anything", [])  # no requirement -> vacuously true


def test_citation_scores() -> None:
    exp = [Expected("a.md", section_prefix="S")]
    assert citation_scores([("a.md", "S"), ("b.md", None)], exp) == (True, 0.5)
    assert citation_scores([("b.md", None)], exp) == (False, 0.0)
    assert citation_scores([], exp) == (False, 0.0)


def test_percentile_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 50) == 20.0
    assert percentile(values, 95) == 40.0
    assert percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)


def test_gate_sweep_trades_answerable_passed_against_unanswerable_blocked() -> None:
    rows = gate_sweep([0.9, 0.6, None], [0.5, 0.3, None], [0.4, 0.7])
    assert rows[0] == (0.4, pytest.approx(2 / 3), pytest.approx(2 / 3))
    assert rows[1] == (0.7, pytest.approx(1 / 3), 1.0)


def test_confusion_matrix_counts_and_zero_fills() -> None:
    from eval.metrics import confusion_matrix

    labels = ["a", "b", "c"]
    m = confusion_matrix([("a", "a"), ("a", "b"), ("a", "b"), ("c", "c")], labels)
    assert m[("a", "a")] == 1 and m[("a", "b")] == 2 and m[("c", "c")] == 1
    assert m[("b", "b")] == 0 and len(m) == 9  # every combination present, unseen ones are 0


def test_wilson_interval_is_wide_for_small_samples_and_inside_0_1() -> None:
    low, high = wilson_interval(34, 36)
    assert 0.80 < low < 0.82 and 0.97 < high < 0.99
    assert wilson_interval(0, 10)[0] == 0.0 and wilson_interval(10, 10)[1] == 1.0
    # More data at the same rate means a tighter interval.
    small, large = wilson_interval(9, 10), wilson_interval(90, 100)
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_wilson_interval_rejects_an_empty_sample() -> None:
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_sign_test_matches_known_values() -> None:
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(5, 5) == 1.0
    assert sign_test_p(4, 0) == pytest.approx(0.125)  # a clean sweep of 4 is not significant
    assert sign_test_p(10, 0) == pytest.approx(2 / 1024)
    assert sign_test_p(1, 0) == 1.0
    assert sign_test_p(3, 9) == sign_test_p(9, 3)  # symmetric


def test_full_coverage_rank_is_the_rank_by_which_every_source_has_appeared() -> None:
    got = [("a.md", "X"), ("z.md", None), ("b.md", "Y"), ("c.md", None)]
    both = [Expected("a.md"), Expected("b.md")]
    assert first_hit_rank(got, both) == 1  # any-source credit
    assert full_coverage_rank(got, both) == 3  # needs b.md too
    assert full_coverage_rank(got, [Expected("a.md"), Expected("missing.md")]) is None
    assert full_coverage_rank(got, [Expected("a.md")]) == 1


def test_compare_pools_pairs_and_counts_gains_and_losses() -> None:
    from eval.compare import compare, paired_outcomes

    def rec(i, kind="answerable", correct=True, cited=True, refused=False, error=None):
        return {
            "id": i,
            "kind": kind,
            "correct": correct,
            "citation_any": cited,
            "refused": refused,
            "error": error,
            "latency_ms": 1000.0,
        }

    base = [rec("a"), rec("b", correct=False), rec("c"), rec("d", error="boom")]
    other = [rec("a", correct=False), rec("b"), rec("c"), rec("d")]
    outcome = paired_outcomes(
        base, other, lambda r: r["kind"] == "answerable", lambda r: bool(r["correct"])
    )
    # d errored in one run, so it is excluded; a was lost, b was gained, c is unchanged
    assert (outcome.n, outcome.base_ok, outcome.other_ok) == (3, 2, 2)
    assert (outcome.gained, outcome.lost) == (1, 1)
    report = compare([(base, other), (base, base)])
    assert "Pooled over 2 question set(s)" in report and "sign-test p" in report


def test_hash_alternatives_match_whole_numbers_only() -> None:
    assert keyword_correct("It deals 18 damage.", [["#18"]])
    assert keyword_correct("It deals 18.", [["#18"]])
    assert not keyword_correct("It deals 180 damage.", [["#18"]])
    assert not keyword_correct("It deals 1.18 damage.", [["#18"]])
    assert not keyword_correct("It deals 14.4 damage.", [["#14"]])
    assert keyword_correct("It deals 14.4 damage.", [["#14.4"]])
    assert keyword_correct("That is 1,250 gold.", [["#1250"]])
    assert keyword_correct("Total: 570 gold", [["#570", "570 gold"]])
    assert keyword_correct("Costs 0 gold left", [["#0"]])
    assert not keyword_correct("Ratio is 0.75", [["#0"]])
    # plain alternatives keep their old substring behaviour
    assert keyword_correct("Costs 180 gold", [["180"]])
