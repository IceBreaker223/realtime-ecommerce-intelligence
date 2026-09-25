"""Live analytics/restart test. Retains four synthetic orders; restarts Spark."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import psycopg
from kafka import KafkaProducer


def main():
    product = "analytics-smoke-" + uuid4().hex
    minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    def event(status, amount=200):
        return dict(event_id=str(uuid4()), order_id="TEST-" + uuid4().hex[:12],
                    customer_id="TEST", customer_name="Synthetic smoke test", city="Test",
                    product=product, category="Smoke tests", quantity=2,
                    unit_price=amount // 2, total_amount=amount, status=status,
                    payment_method="UPI", timestamp=minute.isoformat())

    events = [event("completed"), event("failed"), event("pending")]

    def send(values):
        producer = KafkaProducer(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            acks="all", value_serializer=lambda v: json.dumps(v).encode(),
        )
        try:
            for value in values:
                producer.send(os.getenv("KAFKA_TOPIC", "ecommerce-orders"), value).get(timeout=30)
        finally:
            producer.close()

    with psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "ecommerce"),
        user=os.getenv("POSTGRES_USER", "ecommerce_user"),
        password=os.getenv("POSTGRES_PASSWORD", "ecommerce_password"), autocommit=True,
    ) as db:
        def wait_for(expected_count):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if not db.execute("SELECT to_regclass('analytics_minute')").fetchone()[0]:
                    time.sleep(2)
                    continue
                row = db.execute("""
                    SELECT order_count, completed_order_count, completed_revenue,
                           failed_order_count, average_order_value, failed_order_rate
                    FROM analytics_minute WHERE dimension = 'product' AND dimension_value = %s
                """, (product,)).fetchone()
                if row and row[0] >= expected_count:
                    return row
                time.sleep(2)
            raise TimeoutError("Analytics not updated; inspect docker compose logs spark")

        send(events + events)
        first = wait_for(3)
        if first[:5] != (3, 1, Decimal(200), 1, Decimal(200)):
            raise AssertionError(first)
        subprocess.run(["docker", "compose", "restart", "spark"], check=True)
        # Replay plus a fresh late event in the original minute after restart.
        send(events + [event("completed", 400)])
        second = wait_for(4)
        if second != (4, 2, Decimal(600), 1, Decimal(300), Decimal("0.25")):
            raise AssertionError(second)
        ledger_count = db.execute("SELECT count(*) FROM analytics_events WHERE product = %s", (product,)).fetchone()[0]
        if ledger_count != 4:
            raise AssertionError(ledger_count)
        print("PASS: duplicate delivery + Spark restart + replay + late event")
        print(f"Product: {product}; unique orders=4, revenue=600, AOV=300, failure rate=25%")


if __name__ == "__main__":
    main()
