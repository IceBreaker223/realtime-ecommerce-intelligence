import json
import os
import time
from pathlib import Path
from urllib.request import urlopen

import psycopg
from kafka import KafkaProducer


def connect():
    return psycopg.connect(host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")), dbname=os.getenv("POSTGRES_DB", "ecommerce"),
        user=os.getenv("POSTGRES_USER", "ecommerce_user"),
        password=os.getenv("POSTGRES_PASSWORD", "ecommerce_password"),
        connect_timeout=5, autocommit=True)


def producer():
    return KafkaProducer(bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        acks="all", value_serializer=lambda value: json.dumps(value).encode(), max_block_ms=30000)


def wait_for(predicate, description, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.5)
    raise TimeoutError(description)


def wait_events(db, ids, table="analytics_events"):
    if table not in ("orders", "analytics_events"):
        raise ValueError("Unsupported table")
    def ready():
        if not db.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
            return False
        return db.execute(f"SELECT count(*) FROM {table} WHERE event_id = ANY(%s::uuid[])", (ids,)).fetchone()[0] == len(set(ids))
    wait_for(ready, f"Timed out waiting for {len(set(ids))} events in {table}")


def api(path):
    with urlopen(os.getenv("API_URL", "http://localhost:8000") + path, timeout=10) as response:
        return json.load(response)


def write_report(name, payload):
    path = Path("runtime/evidence") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str), flush=True)
