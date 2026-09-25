import unittest
from datetime import datetime, timedelta, timezone
from detection.detectors import evaluate


def scenarios():
    """Explicit labeled fixtures, kept separate from real analytics."""
    at = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    history = [dict(window_start=at - timedelta(minutes=i), order_count=20,
                    failed_order_count=1, completed_revenue=1000) for i in range(1, 11)]
    def current(n=20, failed=1, revenue=1000):
        return dict(window_start=at, order_count=n, failed_order_count=failed, completed_revenue=revenue)
    return history, [
        ("steady", current(), set()),
        ("ordinary variation", current(failed=2, revenue=1200), set()),
        ("failure spike", current(failed=12, revenue=800), {"failure_rate_spike"}),
        ("revenue spike", current(revenue=5000), {"revenue_spike"}),
        ("both spikes", current(failed=12, revenue=5000), {"failure_rate_spike", "revenue_spike"}),
        ("pending only", current(failed=0, revenue=0), set()),
    ]


class DetectorTests(unittest.TestCase):
    def test_labeled_scenarios(self):
        history, cases = scenarios()
        for label, row, expected in cases:
            with self.subTest(label=label):
                detected = {r["detector"] for r in evaluate(row, history) if r["status"] == "flagged"}
                self.assertEqual(detected, expected)

    def test_sparse_history_and_small_samples_abstain(self):
        history, cases = scenarios()
        for row, baseline in [(cases[2][1], history[:4]), (dict(cases[2][1], order_count=5, failed_order_count=5), history),
                              (cases[2][1], [dict(r, order_count=5) for r in history])]:
            self.assertTrue(all(r["status"] == "insufficient_data" for r in evaluate(row, baseline)))

    def test_no_future_current_or_old_history_leakage(self):
        history, cases = scenarios()
        row = cases[2][1]
        misleading = [dict(row, window_start=row["window_start"] + timedelta(minutes=i),
                           completed_revenue=100000) for i in (0, 1, -61)]
        self.assertEqual(evaluate(row, history), evaluate(row, history + misleading))

    def test_zero_revenue_baseline_abstains(self):
        history, cases = scenarios()
        result = evaluate(cases[3][1], [dict(r, completed_revenue=0) for r in history])
        self.assertEqual(result[1]["status"], "insufficient_data")

    def test_threshold_boundary_is_not_flagged(self):
        history, cases = scenarios()
        row = cases[0][1]
        result = evaluate(dict(row, completed_revenue=1500), history)
        self.assertEqual(result[1]["status"], "normal")


if __name__ == "__main__":
    unittest.main()
