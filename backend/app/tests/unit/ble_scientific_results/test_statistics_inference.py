"""Known-value regression tests for statistics/inference.py."""
from __future__ import annotations

import pytest

from app.modules.ble_scientific_results.statistics.inference import (
    _normal_quantile,
    _t_quantile,
    exact_randomization_test,
    exact_two_sample_permutation_test,
    hierarchical_cluster_bootstrap,
    holm_correction,
    independent_domain_bootstrap_delta_ci,
    matched_stratified_bootstrap_delta_ci,
    non_inferiority_test,
    paired_contrast,
    paired_cluster_bootstrap_delta_ci,
    risk_coverage_curve,
    stratified_crossover_permutation_test,
    stratified_hierarchical_cluster_bootstrap,
)


def test_paired_contrast_hand_computed():
    result = paired_contrast([0.8, 0.9, 0.7], [0.6, 0.7, 0.5])
    assert result.n_pairs == 3
    assert result.mean_difference == pytest.approx(0.2)
    assert result.differences == pytest.approx((0.2, 0.2, 0.2))


def test_exact_randomization_two_sided_p_value_hand_computed():
    # n=3, all differences identical and positive: only the all-plus and
    # all-minus sign patterns reach the observed magnitude -> p = 2/8.
    result = exact_randomization_test([1.0, 1.0, 1.0])
    assert result.exact is True
    assert result.n_permutations == 8
    assert result.p_value == pytest.approx(0.25)


def test_exact_randomization_single_pair_can_never_reject():
    result = exact_randomization_test([5.0])
    assert result.n_permutations == 2
    assert result.p_value == pytest.approx(1.0)


def test_exact_randomization_zero_effect_gives_large_p_value():
    result = exact_randomization_test([1.0, -1.0, 1.0, -1.0])
    assert result.observed_statistic == pytest.approx(0.0)
    assert result.p_value == pytest.approx(1.0)  # every sign pattern is at least as extreme as 0


def test_hierarchical_bootstrap_point_estimate_is_the_pooled_mean():
    clusters = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    result = hierarchical_cluster_bootstrap(clusters, n_resamples=500, rng=None)
    assert result.point_estimate == pytest.approx(3.5)
    assert result.ci_low <= result.point_estimate <= result.ci_high
    assert result.n_resamples == 500


def test_hierarchical_bootstrap_is_reproducible_with_a_fixed_seed():
    import numpy as np
    clusters = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [10.0, 12.0]]
    result_a = hierarchical_cluster_bootstrap(clusters, n_resamples=300, rng=np.random.default_rng(7))
    result_b = hierarchical_cluster_bootstrap(clusters, n_resamples=300, rng=np.random.default_rng(7))
    assert result_a.ci_low == pytest.approx(result_b.ci_low)
    assert result_a.ci_high == pytest.approx(result_b.ci_high)


def test_hierarchical_bootstrap_ignores_within_cluster_ordering_only_resamples_clusters():
    # A single-cluster degenerate case: every resample is identical to the
    # full sample (resampling "3 clusters with replacement" from 1 cluster
    # always yields that same cluster three times over) -> zero-width CI.
    clusters = [[1.0, 2.0, 3.0]]
    result = hierarchical_cluster_bootstrap(clusters, n_resamples=200)
    assert result.ci_low == pytest.approx(result.ci_high)
    assert result.ci_low == pytest.approx(2.0)


def test_hierarchical_bootstrap_return_samples_gives_the_real_raw_resample_array():
    import numpy as np
    clusters = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    result, samples = hierarchical_cluster_bootstrap(clusters, n_resamples=400, rng=np.random.default_rng(3), return_samples=True)
    assert isinstance(samples, np.ndarray)
    assert samples.shape == (400,)
    # The returned CI must be the real percentile CI of these exact samples.
    assert result.ci_low == pytest.approx(np.quantile(samples, 0.025))
    assert result.ci_high == pytest.approx(np.quantile(samples, 0.975))


def test_hierarchical_bootstrap_default_return_is_unchanged_without_return_samples():
    clusters = [[1.0, 2.0], [3.0, 4.0]]
    result = hierarchical_cluster_bootstrap(clusters, n_resamples=100)
    assert not isinstance(result, tuple)


def test_paired_cluster_bootstrap_delta_ci_point_estimate_is_the_real_difference_of_pooled_means():
    # RQ1's real delta_dependence = BA_window - BA_capture over two
    # INDEPENDENT populations -- point estimate must be the exact difference
    # of the two pooled means, never re-derived some other way.
    import numpy as np
    cluster_values_a = [[0.9, 0.95], [0.85, 0.9]]  # pooled mean = 0.9
    cluster_values_b = [[0.7, 0.75], [0.65, 0.7]]  # pooled mean = 0.7
    result = paired_cluster_bootstrap_delta_ci(cluster_values_a, cluster_values_b, n_resamples=500, rng=np.random.default_rng(1))
    assert result.point_estimate == pytest.approx(0.2)
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_paired_cluster_bootstrap_delta_ci_is_never_the_same_as_subtracting_marginal_ci_bounds():
    # A real, important distinction: naively combining ci_low(a)-ci_high(b)
    # and ci_high(a)-ci_low(b) (the range subtracting the two marginal CIs'
    # bounds would imply) is WIDER than the real joint resampling
    # distribution of the difference -- this proves the joint CI is the
    # narrower, statistically correct one, not the naive combination.
    # Real between-cluster variability requires clusters with genuinely
    # different PER-CLUSTER means (not just within-cluster noise) --
    # otherwise both marginal CIs collapse to ~zero width and the
    # distinction cannot be observed at all.
    import numpy as np
    cluster_values_a = [[0.5, 0.55], [0.9, 0.95], [0.3, 0.35], [0.8, 0.85]]
    cluster_values_b = [[0.3, 0.35], [0.7, 0.75], [0.1, 0.15], [0.6, 0.65]]
    rng = np.random.default_rng(42)
    result_a = hierarchical_cluster_bootstrap(cluster_values_a, n_resamples=2000, rng=np.random.default_rng(42))
    result_b = hierarchical_cluster_bootstrap(cluster_values_b, n_resamples=2000, rng=np.random.default_rng(43))
    naive_width = (result_a.ci_high - result_b.ci_low) - (result_a.ci_low - result_b.ci_high)
    joint = paired_cluster_bootstrap_delta_ci(cluster_values_a, cluster_values_b, n_resamples=2000, rng=rng)
    joint_width = joint.ci_high - joint.ci_low
    assert joint_width < naive_width


# --- Methodological-audit fix (2026-08-22, item 3): class-preserving, stratified bootstrap ---

def test_stratified_bootstrap_point_estimate_is_the_real_pooled_mean_across_strata():
    cluster_values_by_stratum = {"A": [[1.0, 2.0], [3.0, 4.0]], "B": [[5.0, 6.0]]}  # pooled mean = 21/6 = 3.5
    result = stratified_hierarchical_cluster_bootstrap(cluster_values_by_stratum, n_resamples=500)
    assert result.point_estimate == pytest.approx(3.5)
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_stratified_bootstrap_is_reproducible_with_a_fixed_seed():
    import numpy as np
    cluster_values_by_stratum = {"A": [[1.0, 2.0], [3.0, 4.0]], "B": [[5.0, 6.0], [10.0, 12.0]]}
    result_a = stratified_hierarchical_cluster_bootstrap(cluster_values_by_stratum, n_resamples=300, rng=np.random.default_rng(7))
    result_b = stratified_hierarchical_cluster_bootstrap(cluster_values_by_stratum, n_resamples=300, rng=np.random.default_rng(7))
    assert result_a.ci_low == pytest.approx(result_b.ci_low)
    assert result_a.ci_high == pytest.approx(result_b.ci_high)


def test_stratified_bootstrap_never_drops_a_stratum_even_with_a_single_cluster_stratum():
    # The real failure mode this fix removes: a plain pooled bootstrap over
    # 12 sessions (RQ1's real capture-disjoint VALIDATION domain) drops at
    # least one of the 4 physical classes from ~26% of its resamples
    # (verified empirically against the real predictions this audit is
    # fixing). Here, stratum "B" has only ONE cluster -- the exact small-
    # stratum shape that makes dropping likely under pooled resampling.
    # Every value carries its own stratum tag so the statistic can verify,
    # for every single resample, that all 3 strata are represented.
    cluster_values_by_stratum = {
        "A": [[("A", 1.0)], [("A", 1.0)]],
        "B": [[("B", 1.0)]],
        "C": [[("C", 1.0)], [("C", 1.0)], [("C", 1.0)]],
    }
    observed_stratum_counts = []

    def statistic(values):
        observed_stratum_counts.append(len({label for label, _ in values}))
        return 0.0

    stratified_hierarchical_cluster_bootstrap(cluster_values_by_stratum, statistic=statistic, n_resamples=500)
    # 501 calls total: 1 for the real point estimate over the full pooled
    # data, plus 500 resamples -- every single one must see all 3 strata.
    assert len(observed_stratum_counts) == 501
    assert all(count == 3 for count in observed_stratum_counts)  # NEVER dropped, unlike the pooled bootstrap


def test_stratified_bootstrap_requires_at_least_one_stratum():
    with pytest.raises(ValueError):
        stratified_hierarchical_cluster_bootstrap({}, n_resamples=10)


def test_stratified_bootstrap_rejects_a_stratum_with_no_clusters():
    with pytest.raises(ValueError):
        stratified_hierarchical_cluster_bootstrap({"A": [[1.0]], "B": []}, n_resamples=10)


def test_independent_domain_bootstrap_delta_ci_point_estimate_is_the_real_difference_of_pooled_means():
    import numpy as np
    cluster_values_by_stratum_a = {"A": [[0.9, 0.95]], "B": [[0.85, 0.9]]}  # pooled mean = 0.9
    cluster_values_by_stratum_b = {"A": [[0.7, 0.75]], "B": [[0.65, 0.7]]}  # pooled mean = 0.7
    result = independent_domain_bootstrap_delta_ci(cluster_values_by_stratum_a, cluster_values_by_stratum_b, n_resamples=500, rng=np.random.default_rng(1))
    assert result.point_estimate == pytest.approx(0.2)
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_independent_domain_bootstrap_delta_ci_never_drops_a_stratum_on_either_side():
    observed_min_strata = []

    def statistic(values):
        observed_min_strata.append(len({label for label, _ in values}))
        return sum(v for _, v in values) / len(values)

    cluster_values_by_stratum_a = {"A": [[("A", 1.0)]], "B": [[("B", 1.0)], [("B", 1.0)]]}
    cluster_values_by_stratum_b = {"A": [[("A", 0.5)]], "B": [[("B", 0.5)], [("B", 0.5)], [("B", 0.5)]]}
    independent_domain_bootstrap_delta_ci(cluster_values_by_stratum_a, cluster_values_by_stratum_b, statistic=statistic, n_resamples=300)
    assert all(count == 2 for count in observed_min_strata)  # both A and B, every single resample, both domains


def test_exact_two_sample_permutation_hand_computed():
    # Values 0,0,0 in group1 vs 10,10 in group0: the observed partition is
    # the UNIQUE most-extreme split among C(5,3)=10 possible relabelings
    # (any other combo mixes at least one 0 into group0 or one 10 into
    # group1), so p = 1/10 exactly.
    values = [0.0, 0.0, 0.0, 10.0, 10.0]
    group_labels = [True, True, True, False, False]
    result = exact_two_sample_permutation_test(values, group_labels)
    assert result.exact is True
    assert result.n_permutations == 10
    assert result.observed_statistic == pytest.approx(-10.0)
    assert result.p_value == pytest.approx(0.1)


def test_exact_two_sample_permutation_identical_values_gives_p_one():
    values = [5.0, 5.0, 5.0, 5.0]
    group_labels = [True, True, False, False]
    result = exact_two_sample_permutation_test(values, group_labels)
    assert result.observed_statistic == pytest.approx(0.0)
    assert result.p_value == pytest.approx(1.0)


def test_exact_two_sample_permutation_requires_both_groups_nonempty():
    with pytest.raises(ValueError):
        exact_two_sample_permutation_test([1.0, 2.0], [True, True])


def test_stratified_crossover_hand_computed_single_device():
    # Hand-enumerated: 4 days, 2 RESET/2 CONTROL, values [10,10,0,0].
    # Of the C(4,2)=6 label patterns, only the observed one and its exact
    # mirror reach |effect|=10; the other 4 give effect=0. p = 2/6 = 1/3.
    result = stratified_crossover_permutation_test({"D1": [10.0, 10.0, 0.0, 0.0]}, {"D1": [True, True, False, False]})
    assert result.exact is True
    assert result.n_permutations == 6
    assert result.observed_statistic == pytest.approx(10.0)
    assert result.p_value == pytest.approx(1 / 3)


def test_stratified_crossover_multi_device_averages_device_effects_equally():
    # Device A: reset=[4,4], control=[0,0] -> effect 4. Device B: reset=[0],
    # control=[0] -> effect 0 (identical values, trivially zero). Average
    # across the 2 devices (equal device weight, not equal day weight) = 2.
    values = {"A": [4.0, 4.0, 0.0, 0.0], "B": [0.0, 0.0]}
    labels = {"A": [True, True, False, False], "B": [True, False]}
    result = stratified_crossover_permutation_test(values, labels)
    assert result.observed_statistic == pytest.approx(2.0)


def test_stratified_crossover_requires_both_arms_present_per_device():
    with pytest.raises(ValueError):
        stratified_crossover_permutation_test({"D1": [1.0, 2.0]}, {"D1": [True, True]})


def test_stratified_crossover_zero_effect_gives_p_value_one():
    result = stratified_crossover_permutation_test({"D1": [5.0, 5.0, 5.0, 5.0]}, {"D1": [True, True, False, False]})
    assert result.observed_statistic == pytest.approx(0.0)
    assert result.p_value == pytest.approx(1.0)


def test_holm_correction_textbook_example():
    p_values = [0.01, 0.02, 0.03, 0.20]
    result = holm_correction(p_values, alpha=0.05)
    assert result.adjusted_p_values == pytest.approx((0.04, 0.06, 0.06, 0.20))
    assert result.reject == (True, False, False, False)


def test_holm_correction_is_order_independent_modulo_permutation():
    permuted = [0.20, 0.01, 0.03, 0.02]
    result = holm_correction(permuted, alpha=0.05)
    assert result.adjusted_p_values == pytest.approx((0.20, 0.04, 0.06, 0.06))
    assert result.reject == (False, True, False, False)


def test_holm_correction_adjusted_p_values_are_monotone_in_sorted_order():
    p_values = [0.5, 0.001, 0.3, 0.02, 0.04]
    result = holm_correction(p_values)
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    adjusted_sorted = [result.adjusted_p_values[i] for i in order]
    assert adjusted_sorted == sorted(adjusted_sorted)


def test_normal_quantile_matches_known_reference_values():
    assert _normal_quantile(0.975) == pytest.approx(1.959964, abs=1e-4)
    assert _normal_quantile(0.5) == pytest.approx(0.0, abs=1e-6)
    assert _normal_quantile(0.95) == pytest.approx(1.644854, abs=1e-4)


def test_t_quantile_matches_known_table_values_at_moderate_and_large_df():
    assert _t_quantile(0.95, df=30) == pytest.approx(1.6973, abs=0.005)
    assert _t_quantile(0.95, df=10) == pytest.approx(1.8125, abs=0.005)


def test_non_inferiority_zero_variance_case():
    result = non_inferiority_test([0.0, 0.0, 0.0, 0.0, 0.0], margin=1.0)
    assert result.mean_difference == pytest.approx(0.0)
    assert result.ci_low == pytest.approx(0.0)
    assert result.non_inferior is True


def test_non_inferiority_rejects_when_ci_crosses_the_margin():
    # Large negative differences with a tight margin: cannot conclude
    # non-inferiority.
    result = non_inferiority_test([-5.0, -6.0, -4.0, -5.5, -4.5], margin=0.5)
    assert result.non_inferior is False


def test_non_inferiority_requires_positive_margin():
    with pytest.raises(ValueError):
        non_inferiority_test([0.0, 0.1], margin=-0.1)


def test_risk_coverage_curve_hand_computed():
    points = risk_coverage_curve([0.9, 0.8, 0.7, 0.6], [True, False, True, True])
    assert [round(p.coverage, 4) for p in points] == [0.25, 0.5, 0.75, 1.0]
    assert [round(p.risk, 4) for p in points] == [0.0, 0.5, 0.3333, 0.25]


def test_risk_coverage_curve_groups_tied_confidence_scores():
    points = risk_coverage_curve([0.9, 0.9, 0.5], [True, False, True])
    assert len(points) == 2
    assert points[0].coverage == pytest.approx(2 / 3)
    assert points[0].risk == pytest.approx(0.5)
    assert points[1].coverage == pytest.approx(1.0)
    assert points[1].risk == pytest.approx(1 / 3)


# --- RQ4 exploratory fix (2026-08-22): genuinely matched/joint stratified bootstrap ---

def test_matched_stratified_bootstrap_delta_ci_point_estimate_is_the_real_difference():
    cluster_values_by_stratum_a = {"A": [[0.9, 0.95]], "B": [[0.85, 0.9]]}  # pooled mean = 0.9
    cluster_values_by_stratum_b = {"A": [[0.7, 0.75]], "B": [[0.65, 0.7]]}  # pooled mean = 0.7
    result = matched_stratified_bootstrap_delta_ci(cluster_values_by_stratum_a, cluster_values_by_stratum_b, n_resamples=500)
    assert result.point_estimate == pytest.approx(0.2)
    assert result.ci_low <= result.point_estimate <= result.ci_high


def test_matched_stratified_bootstrap_delta_ci_uses_the_same_draw_on_both_sides():
    # The defining property: resample i's chosen cluster indices are
    # IDENTICAL for A and B (never two independent draws). Proven here by
    # tagging each cluster with its own index and confirming, for every
    # replicate, that the set of indices selected for A equals the set
    # selected for B.
    cluster_values_by_stratum_a = {"X": [[("c0", 1.0)], [("c1", 2.0)], [("c2", 3.0)]]}
    cluster_values_by_stratum_b = {"X": [[("c0", 10.0)], [("c1", 20.0)], [("c2", 30.0)]]}
    # The delta computation calls statistic(pooled_a) then statistic(pooled_b)
    # per replicate, so alternating entries in a single sink give us that
    # pairing directly.
    combined_sink = []

    def combined_statistic(values):
        combined_sink.append(frozenset(tag for tag, _ in values))
        return sum(v for _, v in values) / len(values)

    matched_stratified_bootstrap_delta_ci(
        cluster_values_by_stratum_a, cluster_values_by_stratum_b, statistic=combined_statistic, n_resamples=200,
    )
    # First 2 entries are the real point-estimate calls (statistic(flat_a), statistic(flat_b)); skip them.
    resample_entries = combined_sink[2:]
    assert len(resample_entries) == 400  # 200 replicates * (A call + B call)
    for i in range(0, len(resample_entries), 2):
        assert resample_entries[i] == resample_entries[i + 1]  # A's cluster tags == B's cluster tags, every replicate


def test_matched_stratified_bootstrap_delta_ci_raises_on_strata_mismatch():
    with pytest.raises(ValueError, match="STRATA_MISMATCH"):
        matched_stratified_bootstrap_delta_ci({"A": [[1.0]]}, {"B": [[1.0]]}, n_resamples=10)


def test_matched_stratified_bootstrap_delta_ci_raises_on_cluster_count_mismatch():
    with pytest.raises(ValueError, match="CLUSTER_COUNT_MISMATCH"):
        matched_stratified_bootstrap_delta_ci({"A": [[1.0], [2.0]]}, {"A": [[1.0]]}, n_resamples=10)


def test_matched_stratified_bootstrap_delta_ci_never_drops_a_stratum():
    observed_min_strata = []

    def statistic(values):
        observed_min_strata.append(len({label for label, _ in values}))
        return sum(v for _, v in values) / len(values)

    cluster_values_by_stratum_a = {"A": [[("A", 1.0)]], "B": [[("B", 1.0)], [("B", 1.0)]]}
    cluster_values_by_stratum_b = {"A": [[("A", 0.5)]], "B": [[("B", 0.5)], [("B", 0.5)]]}
    matched_stratified_bootstrap_delta_ci(cluster_values_by_stratum_a, cluster_values_by_stratum_b, statistic=statistic, n_resamples=300)
    assert all(count == 2 for count in observed_min_strata)
