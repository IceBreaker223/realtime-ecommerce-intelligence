import unittest
from datetime import datetime, timedelta
from uuid import UUID
from producer.event_generator import generate_order


class GeneratorTests(unittest.TestCase):
    def test_consistent_amounts_and_utc_timestamps(self):
        orders = [generate_order() for _ in range(100)]
        self.assertEqual(len({o["event_id"] for o in orders}), 100)
        for order in orders:
            UUID(order["event_id"])
            self.assertEqual(order["total_amount"], order["quantity"] * order["unit_price"])
            self.assertGreater(order["quantity"], 0)
            self.assertIn(order["status"], {"completed", "pending", "failed"})
            self.assertEqual(datetime.fromisoformat(order["timestamp"]).utcoffset(), timedelta(0))
