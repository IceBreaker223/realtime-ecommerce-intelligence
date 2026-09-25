# Validation report — portfolio v1

Recorded **2026-09-25**. Results describe the local implementation and specific
workloads below. They are not production guarantees or maximum-capacity claims.

## Environment

- Windows 11 host, Docker Desktop using WSL2 Linux containers; x86_64.
- Docker engine 29.8.0; 12 visible logical CPUs; 12,348,694,528 bytes (~11.50 GiB)
  visible to Docker. See [environment.json](evidence/environment.json).
- Spark 4.2.0, Java 21 in the image, `local[2]`, two shuffle partitions, 10-second
  processing trigger, maximum 10,000 source records per batch.
- Kafka 4.3.1, PostgreSQL 17, one broker, three topic partitions on the fresh stack.
- The original local stack was idle but running alongside the isolated verification
  stack. No dedicated benchmark machine or CPU isolation was used.

## Clean setup and deterministic demo

A separate Compose project (`commerce-verification`) was started with empty named
volumes on alternate ports. No host Java/Spark/Node setup was used. The demo sent
840 unique synthetic events representing 21 minutes: twenty baseline minutes and
one injected failure/revenue spike minute.

- 840 unique events reached both the raw order table and analytics ledger.
- Completed demo revenue matched the independent fixture expectation:
  **INR 6,630,400**; 656 completed orders and 104 failed orders.
- The detector flagged both injected anomaly types.
- Re-running the same manifest retained 840 unique demo events and the same revenue.
- SQL reconciliation found no differences between the event ledger and minute
  totals for any dimension. See [reconciliation.json](evidence/reconciliation.json).

The same demo was then applied to the original workspace while preserving its
existing storage. The main dashboard includes retained earlier synthetic records,
so its overall totals are not expected to equal a fresh demo alone.

## Crash recovery

Command: `python scripts/manage.py recovery` on the isolated stack.

Spark was killed with **SIGKILL**. While it was stopped, 30 unique orders were each
published twice (60 Kafka messages). Spark was restarted with its existing checkpoint.

- Recovered unique orders: **30/30** in analytics and raw PostgreSQL ingestion.
- Completed revenue: **INR 177,441**, exactly matching the generated workload.
- Restart command to successful verification: **25.456 seconds**.
- Independent SQL reconciliation: **zero mismatches**.

See [recovery.json](evidence/recovery.json). The elapsed time includes Compose startup,
Spark initialization, processing, and polling. This tests backlog recovery and
duplicate delivery, not every possible crash point. Separate transaction tests
inject a failure after aggregate writes but before commit and verify rollback.

## Paced performance measurement

Command: `python scripts/manage.py benchmark --count 300 --rate 20`.

| Measurement | Observed result |
| --- | ---: |
| Unique orders | 300 |
| Target publish rate | 20 orders/s |
| Actual publish rate | 20.06 orders/s |
| Publish duration | 14.952 s |
| First send to all records visible | 25.930 s |
| Completion rate over that full interval | 11.57 orders/s |
| Observed latency p50 | 5.259 s |
| Observed latency p95 | 11.480 s |
| Observed latency maximum | 12.230 s |
| Count/revenue verification | Passed |

See [benchmark.json](evidence/benchmark.json). A producer and database observer run
concurrently in one client process. For each event, latency starts immediately
before `send()` and ends on the first successful ledger observation. The observer
polls every 250 ms; that delay is included. Percentiles use nearest-rank selection.

This is **one small paced run on a warm stack**, not a sustained load, stress test,
or saturation measurement. Spark's ten-second trigger contributes substantially
to latency. No claim of sub-second processing, scalable capacity, or an SLA follows
from these results. Repeated runs will vary with load, trigger alignment, and network.

## Automated checks

The verification commands exercise these suites:

| Suite | Tests | Coverage |
| --- | ---: | --- |
| Pure Python | 8 | Generator arithmetic/UTC, detector rules/leakage/sample sizes, deterministic demo IDs/labels |
| FastAPI + PostgreSQL | 8 | Weighted metrics, time bounds, pagination, safe parameter binding, readiness/errors |
| Detector + PostgreSQL/API | 3 | Replay-safe persistence, late revisions, eligibility, alert evidence/pagination |
| Spark analytics + PostgreSQL | 4 | Typed validation, revenue semantics, transaction rollback, deduplication |
| Browser | 7 | Desktop/mobile, filters, chart paging, empty/offline states, alerts, safe rendering |

Total: **30 automated tests**, plus the full demo, recovery workload, benchmark,
and SQL reconciliation. Database tests use isolated schemas; browser fixtures do
not write synthetic rows to the live database. Screenshots show the real running
application. Test commands and artifacts are described in the [runbook](runbook.md).
The machine-readable [check summary](evidence/checks.json), [browser report](evidence/browser.json),
and [main-workspace demo report](evidence/demo.json) record successful completion.
The [desktop](assets/dashboard-desktop.png) and [mobile](assets/dashboard-mobile.png)
captures use the one-hour view of the deterministic demo.

The GitHub Actions workflow runs equivalent commands and uploads reports/logs.
The public repository now runs
[hosted verification](https://github.com/IceBreaker223/realtime-ecommerce-intelligence/actions/workflows/ci.yml).
The measurements above describe the local machine; hosted results and their
downloadable artifacts are recorded separately in each workflow run.

## Detector evaluation

The fixed-seed synthetic evaluator tested 200 deliberately easy examples per rule:
100 positive and 100 negative. Each rule returned precision 1.0 and recall 1.0.
See [anomaly-evaluation.json](evidence/anomaly-evaluation.json).

These scores validate rule mechanics on obvious injected spikes. They do not
estimate real-world accuracy: histories are independent, anomalies are large,
and there is no seasonality or drift. Detection delay is configured (two-minute
allowance plus the poll cycle), not measured by this offline evaluator.
