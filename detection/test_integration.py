"""Real PostgreSQL + API tests in disposable schemas; no live data injection."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import sql

from api.database import get_connection
from api.main import app
from detection.worker import connect, run_once


class DetectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = connect()
        self.db.autocommit = True
        self.schema = "test_detection_" + uuid4().hex
        self.db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        self.db.execute((Path(__file__).resolve().parents[1] / "streaming/analytics.sql").read_text())
        self.now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        self.target = self.now - timedelta(minutes=4)
        for i in range(1, 11):
            self.insert(self.target - timedelta(minutes=i), 20, 1, 1000)
        self.insert(self.target, 20, 12, 5000)
        self.insert(self.now - timedelta(minutes=1), 20, 12, 5000)
        app.dependency_overrides[get_connection] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.db.close()

    def insert(self, when, count, failed, revenue):
        self.db.execute("""
            INSERT INTO analytics_minute (window_start, dimension, dimension_value,
                order_count, completed_order_count, completed_revenue, failed_order_count)
            VALUES (%s, 'all', '', %s, %s, %s, %s)
        """, (when, count, count - failed, revenue, failed))

    def test_persistence_replay_and_late_revision(self):
        first = run_once(self.db, self.now)
        self.assertEqual(sum(r["status"] == "flagged" for r in first), 2)
        self.assertEqual(len(first), 22)  # recent incomplete minute excluded
        run_once(self.db, self.now)
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM anomaly_checks").fetchone()["n"], 22)
        # Simulate late successful orders revising the affected minute.
        self.db.execute("""
            UPDATE analytics_minute SET order_count = 200, completed_order_count = 188,
                completed_revenue = 5000 WHERE window_start = %s
        """, (self.target,))
        self.db.execute("""
            UPDATE analytics_minute SET order_count = 40, completed_order_count = 39,
                completed_revenue = 5000 WHERE window_start < %s
        """, (self.target,))
        second = run_once(self.db, self.now + timedelta(seconds=30))
        target = [r for r in second if r["window_start"] == self.target]
        self.assertTrue(all(r["status"] == "normal" for r in target))
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM anomaly_checks WHERE first_flagged_at IS NOT NULL").fetchone()["n"], 2)

    def test_alert_api_filters_pagination_and_evidence(self):
        run_once(self.db, self.now)
        period = {"start": (self.now - timedelta(hours=1)).isoformat(), "end": self.now.isoformat(), "limit": 1}
        response = self.client.get("/api/v1/anomalies", params=period)
        self.assertEqual(response.status_code, 200, response.text)
        page = response.json()
        self.assertEqual(page["flagged_count"], 2)
        self.assertEqual(page["checked_count"], 22)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["items"][0]["baseline_orders"], 200)
        self.assertGreater(page["items"][0]["observed_value"], page["items"][0]["threshold"])
        second = self.client.get("/api/v1/anomalies", params=dict(period, offset=1)).json()
        self.assertFalse(second["has_more"])
        self.assertNotEqual(second["items"][0]["detector"], page["items"][0]["detector"])
        all_checks = self.client.get("/api/v1/anomalies", params=dict(period, status="insufficient_data", limit=100)).json()
        self.assertTrue(all(r["status"] == "insufficient_data" for r in all_checks["items"]))
        self.assertEqual(self.client.get("/api/v1/anomalies", params=dict(period, status="unknown")).status_code, 422)

    def test_detector_unavailable_does_not_break_metrics(self):
        self.assertEqual(self.client.get("/api/v1/anomalies").status_code, 503)
        self.assertEqual(self.client.get("/api/v1/metrics/summary").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
