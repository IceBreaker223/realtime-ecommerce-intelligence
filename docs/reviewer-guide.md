# AB Insights: engineering walkthrough

**Abhishek Bhattacharya** | [LinkedIn](https://www.linkedin.com/in/abhishek-bhattacharya-9a399a299) | [GitHub](https://github.com/IceBreaker223)

AB Insights is a personal data-engineering portfolio project. It demonstrates
the path from synthetic orders to business metrics, with explicit checks for
duplicate delivery, recovery, and accounting correctness.

## Follow one order

1. The [producer](../producer/event_generator.py) creates an event with an ID,
   UTC timestamp, product, quantity, amount, and status, and waits for Kafka's acknowledgement.
2. [Spark](../streaming/spark_kafka_stream.py) parses and validates the event.
   Money uses decimal types. Malformed events are excluded from analytics.
3. The [database sink](../streaming/analytics_sink.py) inserts previously unseen
   IDs into a ledger and updates minute aggregates in the same transaction.
   A completed INR 2,000 order contributes INR 2,000 to revenue. A failed order
   contributes to order/failure counts, not completed revenue.
4. A replay of that ID makes no additional contribution. Conflicting payloads
   using the same ID fail rather than silently changing accounting.
5. The [API](../api/main.py) serves bounded, read-only queries. The
   [dashboard](../api/static/dashboard.js) refreshes periodically; processing and
   display updates are batched rather than instantaneous.
6. A [separate worker](../detection/worker.py) evaluates eligible minute aggregates
   with [statistical rules](../detection/detectors.py) and saves alert evidence.

A second [consumer](../producer/db_consumer.py) stores raw orders and commits Kafka
offsets after the database commit. Raw ingestion and analytics are separate paths.

## Decisions and evidence

| Decision | Reason | Where to inspect |
| --- | --- | --- |
| Event ledger plus atomic aggregate updates | Replayed messages must not inflate totals | [Sink transaction tests](../streaming/test_persistence.py) |
| Event-time minute windows | Delayed orders belong to their original activity minute | [Spark aggregation](../streaming/spark_kafka_stream.py), [architecture](architecture.md) |
| Completed-only revenue and weighted metrics | Avoid counting failed sales or averaging averages | [API tests](../api/tests/test_api.py) |
| Statistical rules with minimum sample sizes | Explain alerts and abstain when history is insufficient | [Detector tests](../tests/test_detectors.py) |
| Forced crash with duplicated backlog | Test recovery beyond a normal startup | [Recovery script](../scripts/recovery.py), [results](validation.md#crash-recovery) |
| Independent SQL reconciliation | Compare stored aggregates against the event ledger | [Reconciliation SQL](../tests/reconcile_analytics.sql) |

## Reproduce the evidence

With Docker Linux containers, Compose v2, and Python 3.11+, from the repository root:

```shell
python scripts/manage.py demo
python scripts/manage.py check
python scripts/manage.py recovery
python scripts/manage.py benchmark
```

The [hosted workflow](../.github/workflows/ci.yml) also runs browser tests and uploads
reports. See [successful verification of commit e0f4827](https://github.com/IceBreaker223/realtime-ecommerce-intelligence/actions/runs/36164133167)
and the [latest runs](https://github.com/IceBreaker223/realtime-ecommerce-intelligence/actions/workflows/ci.yml).
Hosted artifact availability is subject to GitHub retention; the commands and
checked-in local evidence remain available for reproduction.

The [runbook](runbook.md) covers live generation, fresh demo histories, browser
setup, and troubleshooting. The [validation report](validation.md) distinguishes
the local benchmark from hosted results and describes measurement limitations.

## Scope and authorship

This is synthetic-data portfolio work developed with AI coding assistance for
implementation, debugging, documentation, and presentation. The public code and
executable checks are evidence of system behavior, not proof of unaided authorship.

The implementation has one Kafka broker, driver-side sink staging, and serialized
database transactions. It does not claim production scale, a trained anomaly
model, sub-second latency, or real-world detector accuracy. No employer or customer
deployment is implied.

## A short live demonstration

Before presenting, run `python scripts/manage.py demo --new`, open
http://localhost:8000, select **1 hour**, and enable auto-refresh. This adds a new
synthetic history; retained previous histories can also appear in the selected range.

1. Explain revenue, order counts, and failure rate.
2. In another terminal run `docker compose run --rm tools python -m producer.event_generator`.
   Show new orders arriving after processing and refresh; stop the producer with Ctrl+C.
3. Compare products and categories, then explain an injected anomaly's evidence.
4. Show hosted CI and the recovery results. Distinguish the live UI from the separately recorded recovery test.

The [interview guide](portfolio.md) explains tradeoffs and likely follow-up questions.
