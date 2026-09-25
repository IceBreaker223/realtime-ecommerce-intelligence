"""Small paced ingestion benchmark; observed latency includes the polling interval."""
import argparse
import json
import math
import platform
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from producer.event_generator import generate_order
from scripts.common import connect, producer, write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--rate", type=float, default=20)
    args = parser.parse_args()
    if not 10 <= args.count <= 5000 or not 0 < args.rate <= 500:
        parser.error("Use 10–5000 events and a rate above 0 and at most 500 events/s")
    run_id = uuid4().hex
    events = [generate_order() for _ in range(args.count)]
    for event in events:
        event["order_id"] = "BENCH-" + event["event_id"][:12]
    ids = [event["event_id"] for event in events]
    sent, observed = {}, {}
    failures = []
    stop = threading.Event()

    def observer():
        try:
            with connect() as db:
                while not stop.is_set():
                    rows = db.execute("SELECT event_id::text FROM analytics_events WHERE event_id = ANY(%s::uuid[])", (ids,)).fetchall()
                    at = time.perf_counter()
                    for row in rows:
                        observed.setdefault(row[0], at)
                    if len(observed) == len(ids):
                        return
                    stop.wait(.25)
        except Exception as error:
            failures.append(str(error))

    observer_thread = threading.Thread(target=observer, daemon=True)
    started_utc = datetime.now(timezone.utc).isoformat()
    with producer() as sender:
        began = time.perf_counter()
        observer_thread.start()
        try:
            for index, event in enumerate(events):
                delay = began + index / args.rate - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                event["timestamp"] = datetime.now(timezone.utc).isoformat()
                sent[event["event_id"]] = time.perf_counter()
                sender.send("ecommerce-orders", event).get(timeout=30)
            publish_seconds = time.perf_counter() - began
            observer_thread.join(timeout=180)
        finally:
            stop.set()
            observer_thread.join(timeout=10)
    if failures or len(observed) != len(ids):
        raise RuntimeError(f"Benchmark incomplete: {len(observed)}/{len(ids)} events; {failures}")
    latencies = sorted(observed[event_id] - sent[event_id] for event_id in ids)
    elapsed = max(observed.values()) - began
    with connect() as db:
        ledger = db.execute("SELECT count(*), sum(total_amount) FILTER (WHERE status='completed') FROM analytics_events WHERE event_id = ANY(%s::uuid[])", (ids,)).fetchone()
    expected_revenue = sum(e["total_amount"] for e in events if e["status"] == "completed")
    if ledger[0] != args.count or (ledger[1] or 0) != expected_revenue:
        raise AssertionError("Benchmark count/revenue mismatch")
    environment = Path("runtime/evidence/environment.json")
    write_report("benchmark.json", dict(result="passed", run_id=run_id, started_at=started_utc,
        count=args.count, target_events_per_second=args.rate, publish_seconds=round(publish_seconds, 3),
        actual_publish_events_per_second=round(args.count / publish_seconds, 2),
        first_send_to_all_visible_seconds=round(elapsed, 3),
        observed_completion_events_per_second=round(args.count / elapsed, 2),
        latency_seconds={"p50": round(latencies[math.ceil(len(latencies)*.5)-1], 3),
                         "p95": round(latencies[math.ceil(len(latencies)*.95)-1], 3), "max": round(max(latencies), 3)},
        poll_interval_seconds=.25, completed_revenue=expected_revenue,
        environment=json.loads(environment.read_text()) if environment.exists() else {"platform": platform.system(), "python": platform.python_version()},
        limitations="Single paced run, warm local single-node stack. Not a saturation or sustained-capacity test. Latency is send initiation to first DB observation, including polling and Spark trigger delay."))


if __name__ == "__main__":
    main()
