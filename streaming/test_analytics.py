"""Run with spark-submit inside Docker; no Kafka required."""
import json
import unittest
from pyspark.sql import SparkSession
from spark_kafka_stream import metrics, parse_orders


class AnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]")
                     .config("spark.sql.session.timeZone", "UTC").getOrCreate())

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_invalid_events_and_revenue(self):
        base = dict(event_id="12345678-1234-1234-1234-123456789abc",
                    timestamp="2026-09-25T12:00:00+00:00", product="Mouse",
                    category="Electronics", quantity=2, unit_price=100,
                    total_amount=200, status="completed")
        events = [base, dict(base, status="failed"), dict(base, status="pending"),
                  dict(base, total_amount=201), dict(base, timestamp="bad"),
                  dict(base, status="unknown")]
        raw = [(json.dumps(e),) for e in events] + [("not-json",)]
        parsed = parse_orders(self.spark.createDataFrame(raw, ["value"]))
        self.assertEqual(parsed.filter("not is_valid").count(), 4)
        result = metrics(parsed.filter("is_valid")).first()
        self.assertEqual(result.order_count, 3)
        self.assertEqual(result.completed_order_count, 1)
        self.assertEqual(result.completed_revenue, 200)
        self.assertEqual(result.average_order_value, 200)
        self.assertAlmostEqual(result.failed_order_rate, 1 / 3)


if __name__ == "__main__":
    unittest.main()
