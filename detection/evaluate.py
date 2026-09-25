"""Reproducible synthetic sanity benchmark; not an estimate of real-world accuracy."""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from detection.detectors import VERSION, evaluate


def benchmark():
    rng = random.Random(20260925)
    counts = {name: dict(tp=0, fp=0, fn=0, tn=0, abstained=0) for name in ("failure_rate_spike", "revenue_spike")}
    at = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    for i in range(200):
        history = [dict(window_start=at - timedelta(minutes=m), order_count=40,
                        failed_order_count=sum(rng.random() < .05 for _ in range(40)),
                        completed_revenue=rng.randint(8000, 12000)) for m in range(1, 21)]
        failure_anomaly, revenue_anomaly = i % 4 in (1, 3), i % 4 in (2, 3)
        row = dict(window_start=at, order_count=40,
                   failed_order_count=sum(rng.random() < (.6 if failure_anomaly else .05) for _ in range(40)),
                   completed_revenue=rng.randint(35000, 50000) if revenue_anomaly else rng.randint(8000, 12000))
        for check in evaluate(row, history):
            positive = failure_anomaly if check["detector"] == "failure_rate_spike" else revenue_anomaly
            flagged = check["status"] == "flagged"
            result = counts[check["detector"]]
            result["abstained"] += check["status"] == "insufficient_data"
            result["tp" if positive and flagged else "fn" if positive else "fp" if flagged else "tn"] += 1
    for result in counts.values():
        result["precision"] = result["tp"] / (result["tp"] + result["fp"]) if result["tp"] + result["fp"] else None
        result["recall"] = result["tp"] / (result["tp"] + result["fn"]) if result["tp"] + result["fn"] else None
    return dict(detector_version=VERSION, seed=20260925, scenarios=200, results=counts,
                limitation="Easy synthetic spikes with independent histories, not production accuracy. No seasonality, drift, or measured end-to-end delay.")


if __name__ == "__main__":
    report = benchmark()
    output = Path("runtime/evaluation")
    output.mkdir(parents=True, exist_ok=True)
    (output / "anomalies.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
