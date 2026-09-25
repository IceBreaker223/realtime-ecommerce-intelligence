"""Integration tests against PostgreSQL in an isolated, temporary schema."""
import json
import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from psycopg import sql
from pyspark.sql import SparkSession

from analytics_sink import connect, persist_batch
from spark_kafka_stream import parse_orders


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]")
                     .config("spark.sql.session.timeZone", "UTC")
                     .config("spark.sql.shuffle.partitions", "2").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def setUp(self):
        self.db = connect()
        self.db.autocommit = True
        self.schema = "test_analytics_" + uuid4().hex
        self.db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))

    def tearDown(self):
        self.db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.db.close()

    def event(self, **changes):
        value = dict(event_id=str(uuid4()), timestamp="2026-09-25T12:00:30Z",
                     product="Mouse", category="Electronics", quantity=2,
                     unit_price=100, total_amount=200, status="completed")
        return dict(value, **changes)

    def batch(self, events):
        return parse_orders(self.spark.createDataFrame([(json.dumps(e),) for e in events], ["value"]))

    def totals(self):
        return self.db.execute("""
            SELECT to_char(window_start, 'HH24:MI'), order_count, completed_order_count,
                   completed_revenue, failed_order_count, average_order_value, failed_order_rate
            FROM analytics_minute WHERE dimension = 'all' ORDER BY window_start
        """).fetchall()

    def test_replay_late_events_boundaries_and_dimensions(self):
        completed = self.event(event_id=str(uuid4()).upper())
        failed = self.event(status="failed")
        pending = self.event(status="pending", timestamp="2026-09-25T12:01:00Z")
        invalid = self.event(total_amount=201)
        first = self.batch([completed, completed, failed, pending, invalid])
        self.assertEqual(persist_batch(first, self.db), 3)
        before = self.totals()
        self.assertEqual(before[0][:6], ("12:00", 2, 1, Decimal(200), 1, Decimal(200)))
        self.assertEqual(before[0][6], Decimal("0.5"))
        self.assertEqual(before[1][:6], ("12:01", 1, 0, Decimal(0), 0, None))
        self.assertEqual(persist_batch(first, self.db), 0)
        self.assertEqual(self.totals(), before)
        # A new connection models a restarted writer, independent of batch IDs.
        with connect() as restarted:
            restarted.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
            self.assertEqual(persist_batch(first, restarted), 0)
        late = self.event(timestamp="2026-09-25T17:30:59+05:30", total_amount=600, unit_price=300)
        self.assertEqual(persist_batch(self.batch([completed, late]), self.db), 1)
        self.assertEqual(self.totals()[0][:6], ("12:00", 3, 2, Decimal(800), 1, Decimal(400)))
        dimensions = self.db.execute("""
            SELECT dimension, sum(order_count), sum(completed_revenue)
            FROM analytics_minute GROUP BY dimension ORDER BY dimension
        """).fetchall()
        self.assertEqual(dimensions, [(d, Decimal(4), Decimal(800)) for d in ("all", "category", "product")])

    def test_partial_failure_rolls_back_and_retry_succeeds(self):
        baseline = self.event()
        persist_batch(self.batch([baseline]), self.db)
        before = self.totals()
        new = self.batch([self.event()])
        from analytics_sink import write_metrics

        def fail_after_write(connection, aggregates):
            write_metrics(connection, aggregates)
            raise RuntimeError("Simulated failure before commit")

        with patch("analytics_sink.write_metrics", side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                persist_batch(new, self.db)
        self.assertEqual(self.totals(), before)
        self.assertEqual(self.db.execute("SELECT count(*) FROM analytics_events").fetchone()[0], 1)
        self.assertEqual(persist_batch(new, self.db), 1)
        self.assertEqual(self.totals()[0][1], 2)

    def test_conflicting_duplicate_rolls_back(self):
        event = self.event()
        persist_batch(self.batch([event]), self.db)
        with self.assertRaises(ValueError):
            persist_batch(self.batch([dict(event, status="failed")]), self.db)
        self.assertEqual(self.totals()[0][2], 1)


if __name__ == "__main__":
    unittest.main()
