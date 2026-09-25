"""Run via manage.py recovery: queue duplicate orders while Spark is killed."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from producer.event_generator import generate_order
from scripts.common import connect, producer, wait_events, write_report

MANIFEST = Path("runtime/recovery-manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["queue", "verify"])
    args = parser.parse_args()
    if args.phase == "queue":
        events = [generate_order() for _ in range(30)]
        for event in events:
            event["order_id"] = "RECOVERY-" + event["event_id"][:12]
        with producer() as sender:
            for event in events * 2:
                sender.send("ecommerce-orders", event).get(timeout=30)
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(dict(events=events, queued_at=datetime.now(timezone.utc).isoformat())), encoding="utf-8")
        print("Queued 30 unique orders twice while Spark is stopped", flush=True)
        return
    manifest = json.loads(MANIFEST.read_text())
    events = manifest["events"]
    ids = [event["event_id"] for event in events]
    began = time.perf_counter()
    with connect() as db:
        wait_events(db, ids)
        wait_events(db, ids, "orders")
        observed = db.execute("SELECT count(*), sum(total_amount) FILTER (WHERE status='completed') FROM analytics_events WHERE event_id = ANY(%s::uuid[])", (ids,)).fetchone()
    expected = sum(e["total_amount"] for e in events if e["status"] == "completed")
    if observed[0] != 30 or (observed[1] or 0) != expected:
        raise AssertionError("Recovery count/revenue mismatch")
    write_report("recovery.json", dict(result="passed", queued_unique_orders=30, kafka_messages=60,
        recovered_unique_orders=observed[0], completed_revenue=expected,
        verify_process_wait_seconds=round(time.perf_counter() - began, 3), queued_at=manifest["queued_at"],
        limitation="SIGKILL with backlog and duplicate delivery; not an exhaustive fault-injection campaign."))


if __name__ == "__main__":
    main()
