"""Small, dependency-free statistics for comparing models on the same labelled items.

- Wilson score interval for rates (stays sensible near 0% and 100%, unlike the naive one).
- Exact McNemar test for paired pass/fail outcomes of two models on identical items.
- Paired bootstrap resampling whole incident clusters, so correlated articles about one
  incident are not counted as independent evidence.
"""

import math
import random
from collections import defaultdict
from collections.abc import Callable, Sequence

Z95 = 1.959963984540054


def wilson(successes: int, total: int, z: float = Z95) -> tuple[float, float, float] | None:
    """Return (rate, low, high), or None when there is nothing to measure."""
    if total <= 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("successes must lie between 0 and total")
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return p, max(0.0, centre - margin), min(1.0, centre + margin)


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact p-value; only the items where exactly one model is right count."""
    if only_a < 0 or only_b < 0:
        raise ValueError("counts must be non-negative")
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_bootstrap(
    rows: Sequence[dict],
    metric: Callable[[Sequence[dict]], float | None],
    *,
    cluster_key: str = "cluster_id",
    resamples: int = 2000,
    seed: int = 0,
) -> tuple[float, float, float] | None:
    """Clustered bootstrap of a paired metric difference.

    ``rows`` are per-item records that already hold both models' outcomes; ``metric``
    turns a list of rows into the difference (candidate minus baseline). Returns
    (observed, low, high) for a 95% interval, or None if the metric is undefined.
    """
    observed = metric(rows)
    if observed is None:
        return None
    clusters = defaultdict(list)
    for row in rows:
        clusters[row[cluster_key]].append(row)
    groups = list(clusters.values())
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [row for _ in groups for row in rng.choice(groups)]
        value = metric(sample)
        if value is not None:
            values.append(value)
    if not values:
        return None
    values.sort()
    low = values[int(0.025 * (len(values) - 1))]
    high = values[int(0.975 * (len(values) - 1))]
    return observed, low, high


def verdict(interval: tuple[float, float, float] | None, higher_is_better: bool = True) -> str:
    """Plain-language reading of a paired difference interval."""
    if interval is None:
        return "brak danych"
    _, low, high = interval
    if low > 0:
        return "lepszy (udowodnione)" if higher_is_better else "gorszy (udowodnione)"
    if high < 0:
        return "gorszy (udowodnione)" if higher_is_better else "lepszy (udowodnione)"
    return "bez udowodnionej różnicy"
