"""Opt-in live smoke test: writes three synthetic orders and retains them."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from kafka import KafkaProducer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from producer.event_generator import generate_order


def main():
    root = Path(__file__).resolve().parents[1]
    orders = [generate_order() for _ in range(3)]
    producer = KafkaProducer(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        acks="all", value_serializer=lambda v: json.dumps(v).encode(),
    )
    try:
        for order in orders:
            producer.send(os.getenv("KAFKA_TOPIC", "ecommerce-orders"), order).get(timeout=30)
    finally:
        producer.close()
    log_path = root / "runtime" / "smoke-consumer.log"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        consumer = subprocess.Popen(
            [sys.executable, "-u", "-m", "producer.db_consumer"],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            with psycopg.connect(
                dbname=os.getenv("POSTGRES_DB", "ecommerce"),
                user=os.getenv("POSTGRES_USER", "ecommerce_user"),
                password=os.getenv("POSTGRES_PASSWORD", "ecommerce_password"),
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")), autocommit=True,
            ) as connection:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if consumer.poll() is not None:
                        raise RuntimeError(f"Consumer exited; inspect {log_path}")
                    exists = connection.execute("SELECT to_regclass('public.orders')").fetchone()[0]
                    if exists:
                        count = connection.execute(
                            "SELECT count(*) FROM orders WHERE event_id::text = ANY(%s)",
                            ([o["event_id"] for o in orders],),
                        ).fetchone()[0]
                        if count == 3:
                            print("PASS: host producer -> Kafka -> database consumer -> PostgreSQL (3/3)")
                            return
                    time.sleep(1)
                raise TimeoutError(f"Orders not saved; inspect {log_path}")
        finally:
            consumer.terminate()
            consumer.wait(timeout=10)


if __name__ == "__main__":
    main()
