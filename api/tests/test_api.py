"""API integration tests; require PostgreSQL and isolate data in a temporary schema."""
import os
import unittest
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from fastapi.testclient import TestClient

from api.database import get_connection
from api.main import app

PERIOD = {"start": "2026-09-25T12:00:00Z", "end": "2026-09-25T12:02:00Z"}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = dict(host=os.getenv("POSTGRES_HOST", "localhost"),
                          port=int(os.getenv("POSTGRES_PORT", "5432")),
                          dbname=os.getenv("POSTGRES_DB", "ecommerce"),
                          user=os.getenv("POSTGRES_USER", "ecommerce_user"),
                          password=os.getenv("POSTGRES_PASSWORD", "ecommerce_password"))
        cls.schema = "test_api_" + uuid4().hex
        with psycopg.connect(**cls.config) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
            db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(cls.schema)))
            db.execute((Path(__file__).resolve().parents[2] / "streaming/analytics.sql").read_text())
            with db.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO analytics_minute
                      (window_start, dimension, dimension_value, order_count,
                       completed_order_count, completed_revenue, failed_order_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, [
                    ("2026-09-25T12:00Z", "all", "", 4, 1, 100, 1),
                    ("2026-09-25T12:01Z", "all", "", 2, 2, 600, 0),
                    ("2026-09-25T12:02Z", "all", "", 1, 1, 999, 0),
                    ("2026-09-25T12:00Z", "product", "A", 4, 1, 100, 1),
                    ("2026-09-25T12:01Z", "product", "A", 2, 2, 600, 0),
                    ("2026-09-25T12:00Z", "product", "B'; DROP TABLE analytics_minute;--", 1, 0, 0, 1),
                    ("2026-09-25T12:00Z", "category", "Electronics", 4, 1, 100, 1),
                    ("2026-09-25T12:01Z", "category", "Electronics", 2, 2, 600, 0),
                ])

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(**cls.config) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        def isolated_connection():
            with psycopg.connect(**self.config, row_factory=dict_row) as db:
                db.execute("SET TRANSACTION READ ONLY")
                db.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema)))
                db.execute("SET LOCAL TIME ZONE 'UTC'")
                yield db

        app.dependency_overrides[get_connection] = isolated_connection
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()

    def test_summary_weighted_metrics_and_exclusive_end(self):
        response = self.client.get("/api/v1/metrics/summary", params=PERIOD)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["order_count"], 6)
        self.assertEqual(data["completed_order_count"], 3)
        self.assertEqual(data["currency"], "INR")
        self.assertIsInstance(data["completed_revenue"], str)
        self.assertEqual(Decimal(data["completed_revenue"]), 700)
        self.assertAlmostEqual(float(data["average_order_value"]), 700 / 3)
        self.assertAlmostEqual(float(data["failed_order_rate"]), 1 / 6)
        self.assertIsNotNone(data["last_updated"])

    def test_empty_summary_and_pages(self):
        period = {"start": "2020-01-01T00:00:00Z", "end": "2020-01-02T00:00:00Z"}
        data = self.client.get("/api/v1/metrics/summary", params=period).json()
        self.assertEqual(data["order_count"], 0)
        self.assertEqual(Decimal(data["completed_revenue"]), 0)
        for key in ("average_order_value", "failed_order_rate", "last_updated"):
            self.assertIsNone(data[key])
        for path in ("windows", "breakdown"):
            data = self.client.get(f"/api/v1/metrics/{path}", params=period).json()
            self.assertEqual(data["items"], [])
            self.assertFalse(data["has_more"])

    def test_windows_pagination_and_exact_filter(self):
        params = dict(PERIOD, dimension="product", dimension_value="A", limit=1)
        first = self.client.get("/api/v1/metrics/windows", params=params).json()
        second = self.client.get("/api/v1/metrics/windows", params=dict(params, offset=1)).json()
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertGreater(first["items"][0]["window_start"], second["items"][0]["window_start"])
        self.assertEqual(first["items"][0]["dimension_value"], "A")
        hostile = "B'; DROP TABLE analytics_minute;--"
        result = self.client.get("/api/v1/metrics/windows", params=dict(params, dimension_value=hostile))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["items"][0]["dimension_value"], hostile)
        self.assertEqual(self.client.get("/health/ready").status_code, 200)

    def test_breakdown_ranking_and_weighted_average(self):
        params = dict(PERIOD, dimension="product", limit=1)
        data = self.client.get("/api/v1/metrics/breakdown", params=params).json()
        self.assertTrue(data["has_more"])
        self.assertEqual(data["items"][0]["dimension_value"], "A")
        self.assertAlmostEqual(float(data["items"][0]["average_order_value"]), 700 / 3)
        second = self.client.get("/api/v1/metrics/breakdown", params=dict(params, offset=1)).json()
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["items"][0]["average_order_value"])
        categories = self.client.get("/api/v1/metrics/breakdown", params=PERIOD).json()
        self.assertEqual(categories["items"][0]["dimension_value"], "Electronics")

    def test_invalid_ranges_dimensions_and_pagination(self):
        for extra in ({"start": "2026-09-25T12:00:00"}, {"start": "2026-09-25T12:00:01Z"},
                      {"start": PERIOD["end"]}, {"start": "2020-01-01T00:00Z"},
                      {"limit": 0}, {"limit": 501}, {"offset": -1},
                      {"dimension": "unknown"}, {"dimension_value": "A"}):
            with self.subTest(extra=extra):
                response = self.client.get("/api/v1/metrics/windows", params=dict(PERIOD, **extra))
                self.assertEqual(response.status_code, 422, response.text)

    def test_timezone_equivalence_and_default_range(self):
        data = self.client.get("/api/v1/metrics/summary", params={
            "start": "2026-09-25T17:30:00+05:30", "end": "2026-09-25T17:32:00+05:30",
        }).json()
        self.assertEqual(data["order_count"], 6)
        self.assertEqual(self.client.get("/api/v1/metrics/summary").status_code, 200)

    def test_liveness_readiness_and_safe_database_failure(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").status_code, 200)

        def offline():
            raise psycopg.OperationalError("secret connection detail")

        app.dependency_overrides[get_connection] = offline
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        for route in ("/health/ready", "/api/v1/metrics/summary"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret", response.text)

    def test_missing_schema_returns_not_ready(self):
        def uninitialized():
            with psycopg.connect(**self.config, row_factory=dict_row) as db:
                db.execute("SET TRANSACTION READ ONLY")
                db.execute("SET LOCAL search_path TO pg_catalog")
                yield db

        app.dependency_overrides[get_connection] = uninitialized
        self.assertEqual(self.client.get("/health/ready").status_code, 503)
        self.assertEqual(self.client.get("/api/v1/metrics/summary").status_code, 503)
