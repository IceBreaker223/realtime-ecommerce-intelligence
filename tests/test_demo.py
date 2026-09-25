import unittest
from collections import defaultdict
from datetime import datetime, timezone

from detection.detectors import evaluate
from scripts.demo import demo_events


class DemoTests(unittest.TestCase):
    def test_replay_ids_are_stable_and_distinct(self):
        anchor = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        first, second = demo_events(anchor), demo_events(anchor)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 840)
        self.assertEqual(len({e["event_id"] for e in first}), 840)

    def test_expected_revenue_and_spike_labels(self):
        events = demo_events(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        groups = defaultdict(list)
        for event in events:
            self.assertEqual(event["total_amount"], event["quantity"] * event["unit_price"])
            groups[datetime.fromisoformat(event["timestamp"]).replace(second=0)].append(event)
        rows = [dict(window_start=minute, order_count=len(values),
                     failed_order_count=sum(e["status"] == "failed" for e in values),
                     completed_revenue=sum(e["total_amount"] for e in values if e["status"] == "completed"))
                for minute, values in sorted(groups.items())]
        self.assertEqual(sum(r["completed_revenue"] for r in rows), 6630400)
        self.assertEqual({r["detector"] for r in evaluate(rows[-1], rows) if r["status"] == "flagged"},
                         {"failure_rate_spike", "revenue_spike"})
