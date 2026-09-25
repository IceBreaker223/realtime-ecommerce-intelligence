from pathlib import Path
from scripts.common import connect, write_report


def main():
    query = (Path(__file__).resolve().parents[1] / "tests/reconcile_analytics.sql").read_text()
    # SET is a separate statement so fetchall reads the actual mismatch query.
    query = query.replace("SET TIME ZONE 'UTC';", "")
    with connect() as db:
        db.execute("SET TIME ZONE 'UTC'")
        differences = db.execute(query).fetchall()
    write_report("reconciliation.json", {"result": "passed" if not differences else "failed", "mismatches": differences})
    if differences:
        raise AssertionError("Stored analytics do not match the event ledger")


if __name__ == "__main__":
    main()
