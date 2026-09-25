"""Explainable heuristics, not a trained model or a calibrated significance test."""
from datetime import timedelta
from math import sqrt
from statistics import mean, pstdev

VERSION = "statistical-v1"
BASELINE_MINUTES = 60
MIN_BASELINE_WINDOWS = 5
MIN_BASELINE_ORDERS = 100
MIN_CURRENT_ORDERS = 10


def evaluate(current, history):
    start = current["window_start"]
    # No future data or current-minute leakage into the reference distribution.
    baseline = [r for r in history if start - timedelta(minutes=BASELINE_MINUTES)
                <= r["window_start"] < start]
    count = sum(r["order_count"] for r in baseline)
    n = current["order_count"]
    enough = len(baseline) >= MIN_BASELINE_WINDOWS and count >= MIN_BASELINE_ORDERS and n >= MIN_CURRENT_ORDERS
    failure_rate = current["failed_order_count"] / n if n else 0
    smoothed_rate = (sum(r["failed_order_count"] for r in baseline) + 1) / (count + 2)
    failure_threshold = min(1.0, smoothed_rate + max(0.15, 3 * sqrt(smoothed_rate * (1 - smoothed_rate) / max(n, 1))))
    revenues = [float(r["completed_revenue"]) for r in baseline]
    average_revenue = mean(revenues) if revenues else 0.0
    revenue_threshold = max(average_revenue * 1.5, average_revenue + 3 * pstdev(revenues)) if revenues else 0.0
    specs = [
        ("failure_rate_spike", "fraction", failure_rate, smoothed_rate, failure_threshold, enough,
         "Failure rate exceeds the smoothed historical rate plus the larger of 15 percentage points or three binomial standard errors."),
        ("revenue_spike", "INR", float(current["completed_revenue"]), average_revenue, revenue_threshold,
         enough and average_revenue > 0,
         "Completed revenue exceeds both 1.5 times the historical mean and the mean plus three population standard deviations."),
    ]
    results = []
    for detector, unit, observed, reference, threshold, eligible, explanation in specs:
        results.append(dict(
            window_start=start, detector=detector, detector_version=VERSION,
            status=("flagged" if observed > threshold else "normal") if eligible else "insufficient_data",
            unit=unit, observed_value=observed, baseline_value=reference if eligible else None,
            threshold=threshold if eligible else None, baseline_windows=len(baseline),
            baseline_orders=count, current_orders=n,
            explanation=explanation if eligible else
                "Need at least 5 active historical minutes, 100 historical orders, and 10 current orders; revenue also needs a positive historical mean.",
        ))
    return results
