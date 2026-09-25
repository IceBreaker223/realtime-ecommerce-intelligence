"""Deterministic 840-order replayable demo through Kafka, never direct SQL inserts."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from producer.event_generator import PRODUCTS
from scripts.common import api, connect, producer, wait_events, wait_for, write_report


def demo_events(anchor):
    events = []
    for minute in range(21):
        for index in range(40):
            product, category, price = PRODUCTS[index % len(PRODUCTS)]
            spike = minute == 20
            status = ("failed" if index < 24 else "completed") if spike else (
                "failed" if index % 10 == 0 else "pending" if index % 10 == 1 else "completed")
            quantity = 2 if spike else 1 + index % 4
            unit_price = 30000 if spike else price
            event_id = str(uuid5(NAMESPACE_URL, f"commerce-demo-v1:{anchor.isoformat()}:{minute}:{index}"))
            events.append(dict(event_id=event_id, order_id="DEMO-" + event_id[:12],
                customer_id=f"DEMO-{index:03}", customer_name=f"Synthetic customer {index:03}",
                city=["Mumbai", "Delhi", "Bengaluru", "Chennai"][index % 4], product=product,
                category=category, quantity=quantity, unit_price=unit_price, total_amount=quantity * unit_price,
                payment_method="UPI", status=status,
                timestamp=(anchor + timedelta(minutes=minute, seconds=index)).isoformat()))
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", action="store_true", help="Create another demo history instead of replaying the previous one")
    args = parser.parse_args()
    manifest = Path("runtime/demo-manifest.json")
    if manifest.exists() and not args.new:
        anchor = datetime.fromisoformat(json.loads(manifest.read_text())["anchor"])
    else:
        anchor = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=24)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"anchor": anchor.isoformat(), "version": 1}), encoding="utf-8")
    events = demo_events(anchor)
    with producer() as sender:
        futures = [sender.send("ecommerce-orders", event) for event in events]
        for future in futures:
            future.get(timeout=30)
    ids = [event["event_id"] for event in events]
    with connect() as db:
        wait_events(db, ids)
        wait_events(db, ids, "orders")
        target = anchor + timedelta(minutes=20)
        def detected():
            if not db.execute("SELECT to_regclass('anomaly_checks')").fetchone()[0]:
                return False
            return db.execute("SELECT count(*) FROM anomaly_checks WHERE window_start = %s AND status = 'flagged'", (target,)).fetchone()[0] >= 2
        wait_for(detected, "Expected demo spike alerts were not produced; inspect detector logs")
        observed = db.execute("SELECT sum(total_amount) FROM analytics_events WHERE event_id = ANY(%s::uuid[]) AND status='completed'", (ids,)).fetchone()[0]
    expected = sum(e["total_amount"] for e in events if e["status"] == "completed")
    if observed != expected:
        raise AssertionError(f"Demo revenue mismatch: {observed} != {expected}")
    summary = api("/api/v1/metrics/summary")
    write_report("demo.json", dict(result="passed", unique_demo_events=len(ids),
        anchor=anchor, anomaly_minute=target, expected_demo_revenue=expected,
        actual_demo_revenue=observed, flagged_detectors=2, api_summary=summary,
        replay_note="Same manifest reuses the same IDs; use --new for a new history."))


if __name__ == "__main__":
    main()
