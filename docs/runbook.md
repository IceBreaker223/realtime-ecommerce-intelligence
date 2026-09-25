# Runbook

## One-command demo

Start Docker Desktop's Linux engine, then run `python scripts/manage.py demo` from
the repository root. On Windows, `py -3.11` or the existing `.venv/Scripts/python.exe`
can replace `python`. The host entry point uses only Python's standard library;
application and test dependencies are installed in containers.

Expected result: 840 unique demo events, INR 6,630,400 completed revenue from those
events, and two flagged detector types in the final demo minute. Existing data is
not cleared, so overall dashboard totals may be larger. First startup can take
several minutes while downloading images and the Spark connector. Generated IDs
are stable for the anchor stored in `runtime/demo-manifest.json`; reruns are replays.
An old manifest replays its old event times. Use `demo --new` when you want fresh
activity, remembering that this adds another retained synthetic history.
Repeated or unrelated workloads can change the overall detector baseline; use an
isolated project with fresh volumes when you need the exact clean-demo expectations.

The raw order consumer now runs in Compose. Do not start a second host consumer
unless deliberately testing consumer-group behavior. For continuous synthetic data:

```shell
docker compose run --rm --no-deps tools python -m producer.event_generator
```

Stop this foreground producer with Ctrl+C. It publishes one order every two seconds.
`python scripts/manage.py start` starts the stack without sending demo data; on an
empty database, analytics readiness may remain false until Spark processes events.

## Storage, ports, and configuration

Fresh checkouts need no `.env`. Default ports bind to **127.0.0.1** only: Kafka 9092,
PostgreSQL 5432, API/dashboard 8000. Named volumes retain PostgreSQL, Kafka, and Spark
checkpoints. A one-shot init service sets volume ownership for the non-root Kafka
and Spark users (1000 and 185). Images and direct application dependencies are pinned;
the API's transitive dependency versions are constrained too.

Optional configuration is documented in `.env.example`. Copy it only when no `.env`
already exists. Compose reads `.env`; host Python clients read process environment.
Existing initialized PostgreSQL users/passwords are not changed by editing `.env`.
The supplied password and plaintext single-broker listeners are local demo defaults.

For this original workspace, the gitignored `.env` preserves the existing
`runtime/kafka-data` and `runtime/spark-checkpoints` bind mounts. New checkouts use
named volumes. Changing a storage setting selects another store; it does not migrate
data. Never delete a volume or checkpoint to work around an error without understanding
the resulting replay/history change. `manage.py stop` retains all stores.

For an isolated clean verification on Windows (no interference with the main stack):

```powershell
$env:COMPOSE_PROJECT_NAME='commerce-verification'
$env:KAFKA_STORAGE='kafka_data'
$env:SPARK_STORAGE='spark_checkpoints'
$env:KAFKA_PORT='19094'
$env:POSTGRES_PORT='15432'
$env:API_PORT='18000'
python scripts/manage.py demo
```

These variables apply to that terminal and child processes. Open localhost:18000.
Close that terminal to return to the normal defaults. Reports in `runtime/` are shared
within the checkout, so avoid running two evidence-producing jobs concurrently.

## Automated verification

```shell
python scripts/manage.py check
python scripts/manage.py recovery
python scripts/manage.py benchmark --count 300 --rate 20
```

`check` runs unit, API/PostgreSQL, detector/PostgreSQL, and Spark/PostgreSQL tests,
then independent SQL reconciliation and synthetic detector evaluation. Database
integration tests create and remove only their randomly named test schemas.

`recovery` intentionally sends SIGKILL to Spark, queues 30 unique orders twice,
restarts Spark in a `finally` block, and verifies the ledger, raw orders, and revenue.
It retains these synthetic records. It does not kill PostgreSQL or Kafka.

`benchmark` adds a bounded workload and writes `runtime/evidence/benchmark.json`.
Latency measures send initiation to first visible database observation, including
the 250ms poll interval and Spark trigger delay. The result is not a saturation test.

Browser tests require a small host test environment:

```shell
python -m venv .venv
# Windows: .venv\Scripts\python.exe; Linux/macOS: .venv/bin/python
python -m pip install -r tests/requirements-browser.txt
python -m playwright install --with-deps chromium
python tests/dashboard_smoke.py
```

Use the virtual environment's Python for the last three commands. Windows defaults
to installed Edge; set `BROWSER_CHANNEL=chromium` to use Playwright's Chromium instead.
`DASHBOARD_URL` overrides localhost:8000. Screenshots and reports go to `runtime/`.
CI executes these same entry points on Ubuntu and uploads artifacts following the
[GitHub Actions artifact workflow](https://docs.github.com/actions/configuring-and-managing-workflows/persisting-workflow-data-using-artifacts).

## Troubleshooting

| Symptom | Check / action |
| --- | --- |
| Docker engine unavailable | Start Docker Desktop with Linux containers; run `docker version` |
| Port already allocated | Stop the conflicting service or set the port overrides above |
| Spark exits | `docker compose logs --tail 100 spark`; first-run connector downloads need network access |
| API returns 503 | `docker compose logs api spark postgres`; analytics tables appear when Spark processes its first batch |
| Detector building baseline | Expected with fewer than 5 historical active minutes, 100 historical orders, or 10 target orders; run the deterministic demo |
| Stale dashboard badge | No recent aggregate writes; start the producer. API reachability is not stream health |
| Credential mismatch | Use credentials matching the existing database; `.env` does not reset initialized users |
| Permission error on old bind mounts | Preserve the store; inspect directory ownership. Fresh named volumes are initialized automatically |

Inspect `docker compose ps` and `docker compose logs --tail 100 SERVICE`. If a command
fails, fix its reported problem and rerun it; scripts exit nonzero on verification
failures. All service images should be rebuilt after source changes with `manage.py start`.
