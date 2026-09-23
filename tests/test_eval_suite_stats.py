"""Hand-checked values for the eval-suite statistics."""

import pytest

from sentinel.eval.suite.stats import mcnemar_exact, paired_bootstrap, verdict, wilson


def test_wilson_matches_reference_values():
    rate, low, high = wilson(95, 100)
    assert rate == 0.95
    assert low == pytest.approx(0.8882, abs=1e-4)
    assert high == pytest.approx(0.9785, abs=1e-4)


def test_wilson_edges_stay_inside_zero_one():
    _, low, high = wilson(0, 10)
    assert low == 0.0 and high == pytest.approx(0.2775, abs=1e-4)
    _, low, high = wilson(10, 10)
    assert high == pytest.approx(1.0) and low == pytest.approx(0.7225, abs=1e-4)
    assert wilson(0, 0) is None
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    # 1 vs 9 discordant pairs: 2 * (C(10,0) + C(10,1)) / 2^10 = 22 / 1024
    assert mcnemar_exact(1, 9) == pytest.approx(22 / 1024)
    assert mcnemar_exact(9, 1) == mcnemar_exact(1, 9)


def test_paired_bootstrap_detects_a_clear_difference_and_respects_clusters():
    rows = [{"cluster_id": f"c{i}", "a": 1, "b": 0} for i in range(30)]

    def diff(sample):
        return sum(r["a"] - r["b"] for r in sample) / len(sample)

    observed, low, high = paired_bootstrap(rows, diff, resamples=300, seed=1)
    assert observed == 1.0 and low == 1.0 and high == 1.0
    assert verdict((observed, low, high)) == "lepszy (udowodnione)"


def test_paired_bootstrap_one_big_cluster_gives_no_proof():
    # 40 items but only two incidents: one where a wins, one where b wins.
    rows = [{"cluster_id": "x", "d": 1}] * 20 + [{"cluster_id": "y", "d": -1}] * 20

    def mean(sample):
        return sum(r["d"] for r in sample) / len(sample)

    interval = paired_bootstrap(rows, mean, resamples=500, seed=2)
    assert verdict(interval) == "bez udowodnionej różnicy"


def test_verdict_lower_is_better_and_missing():
    assert verdict((0.1, 0.05, 0.2), higher_is_better=False) == "gorszy (udowodnione)"
    assert verdict(None) == "brak danych"
