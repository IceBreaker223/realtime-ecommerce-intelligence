"""Re-evaluate the last 24 hours every 30s so late data can revise alert verdicts."""
import logging
import os
import signal
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from detection.detectors import VERSION, evaluate

logger = logging.getLogger(__name__)


def connect():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "ecommerce"), user=os.getenv("POSTGRES_USER", "ecommerce_user"),
        password=os.getenv("POSTGRES_PASSWORD", "ecommerce_password"),
        connect_timeout=5, options="-c timezone=UTC -c statement_timeout=15000", row_factory=dict_row,
    )


def run_once(db, now=None):
    now = now or datetime.now(timezone.utc)
    start = now.replace(second=0, microsecond=0) - timedelta(hours=24)
    # Allow two full minutes after window end for normal ingestion delay.
    cutoff = now - timedelta(minutes=3)
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        db.execute("SELECT pg_advisory_xact_lock(72409102)")
        db.execute(Path(__file__).with_name("schema.sql").read_text())
        rows = db.execute("""
            SELECT window_start, order_count, failed_order_count, completed_revenue
            FROM analytics_minute WHERE dimension = 'all'
                AND window_start >= %s AND window_start <= %s ORDER BY window_start
        """, (start - timedelta(hours=1), cutoff)).fetchall()
        results = [result for row in rows if row["window_start"] >= start
                   for result in evaluate(row, rows)]
        with db.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO anomaly_checks (window_start, detector, detector_version, status,
                    unit, observed_value, baseline_value, threshold, baseline_windows,
                    baseline_orders, current_orders, explanation, first_flagged_at, evaluated_at)
                VALUES (%(window_start)s, %(detector)s, %(detector_version)s, %(status)s,
                    %(unit)s, %(observed_value)s, %(baseline_value)s, %(threshold)s, %(baseline_windows)s,
                    %(baseline_orders)s, %(current_orders)s, %(explanation)s,
                    CASE WHEN %(status)s = 'flagged' THEN %(now)s::timestamptz ELSE NULL END, %(now)s)
                ON CONFLICT (window_start, detector, detector_version) DO UPDATE SET
                    status = EXCLUDED.status, observed_value = EXCLUDED.observed_value,
                    baseline_value = EXCLUDED.baseline_value, threshold = EXCLUDED.threshold,
                    baseline_windows = EXCLUDED.baseline_windows, baseline_orders = EXCLUDED.baseline_orders,
                    current_orders = EXCLUDED.current_orders, explanation = EXCLUDED.explanation,
                    first_flagged_at = COALESCE(anomaly_checks.first_flagged_at, EXCLUDED.first_flagged_at),
                    evaluated_at = EXCLUDED.evaluated_at
            """, [dict(result, now=now) for result in results])
        db.execute("""
            INSERT INTO detector_status (singleton, last_successful_run, detector_version)
            VALUES (TRUE, %s, %s) ON CONFLICT (singleton) DO UPDATE SET
                last_successful_run = EXCLUDED.last_successful_run,
                detector_version = EXCLUDED.detector_version
        """, (now, VERSION))
    return results


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopped = threading.Event()
    for name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(name, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            with connect() as db:
                results = run_once(db)
            logger.info("checks=%s flagged=%s", len(results), sum(r["status"] == "flagged" for r in results))
        except psycopg.Error as error:
            logger.warning("Detection unavailable (%s); retrying in 30s", type(error).__name__)
        stopped.wait(30)


if __name__ == "__main__":
    main()
