# Demo and interview guide

## Three-minute walkthrough

For a silent dashboard clip using real local API responses, install
`tests/requirements-browser.txt`, run `python -m playwright install ffmpeg`
(also `python -m playwright install chromium` on Linux), then run
`python scripts/record_demo.py` while the demo is running. The roughly one-minute
WebM is saved to `runtime/walkthrough/ab-insights.webm`. Use a recent demo history
so the one-hour view contains orders. This clip has no narration; use the outline
below for a longer narrated interview walkthrough.

Prepare with `python scripts/manage.py demo`; open the dashboard and select **1 hour**.
Use the actual UI and reports—do not claim that synthetic orders are customer traffic.

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:25 | Dashboard overview | “This is an end-to-end synthetic commerce platform. Orders become minute-level revenue, outcomes, and product analytics.” |
| 0:25–0:55 | Revenue chart and product/category switch | “Amounts are INR. Completed orders contribute revenue; failed and pending orders still contribute to the failure-rate denominator.” |
| 0:55–1:20 | Signals to investigate | “The final demo minute contains labeled failure and revenue spikes. Each signal exposes its baseline, threshold, and sample size.” |
| 1:20–1:50 | Architecture diagram and `analytics_sink.py` | “The event ledger and aggregate deltas commit together. Kafka delivery is at least once, while database accounting is idempotent.” |
| 1:50–2:20 | Recovery JSON and reconciliation result | “I killed Spark, queued each order twice, restarted it, and verified exact unique counts and revenue. SQL independently checks every aggregate.” |
| 2:20–2:45 | Benchmark report | “This is a small paced workload on my documented machine. It measures observed latency, including batching; it is not a maximum-capacity result.” |
| 2:45–3:00 | Tests/CI and scope | “The same commands run in CI. The next scaling step would be distributed sink staging and explicit retention, not adding more tools.” |

Optional live segment: replay `docker compose run --rm tools python -m scripts.demo`
and show unchanged unique demo counts. Re-running the full `manage.py demo` also
checks builds, so prepare it before a short recording rather than waiting on downloads.

## CV bullets you can substantiate

- Built a real-time commerce analytics platform using Python, Kafka, Spark Structured
  Streaming, PostgreSQL, FastAPI, and Docker, with a responsive analytics dashboard.
- Implemented transactional event deduplication and one-minute aggregate updates;
  verified replay safety and recovery after a forced Spark crash with duplicate input.
- Developed explainable statistical anomaly rules, API/database/browser tests, and
  a reproducible 840-order demo with labeled failure-rate and revenue spikes.
- Added a GitHub Actions verification workflow and reproducible latency/throughput
  benchmarks with raw evidence and documented environment limits.

After a hosted workflow run succeeds, “added a workflow” can become “automated
verification in GitHub Actions.” Add measured numbers only from the validation report,
and include workload/machine context. Do not claim production deployment, trained ML,
global exactly-once delivery, a maximum throughput, or real-world detector accuracy.

## Questions to be ready for

**Why Spark for a small workload?** It is a learning/portfolio implementation of
typed stream processing and event-time aggregation. A simpler consumer could handle
this volume; Spark provides room to demonstrate distributed processing once the sink scales.

**Where does exactly-once behavior come from?** Not from Kafka-to-PostgreSQL atomicity.
At-least-once input plus a unique event ledger and atomic SQL transaction make the
accounting idempotent. Raw consumer offsets are committed after SQL commits.

**What happens with late orders?** Their event-time minute is updated. The ledger
retains identities indefinitely; there is no watermark finalization policy in v1.

**Why no trained anomaly model?** The baseline is explainable and measurable. A model
needs richer labels, holdout evaluation, and drift/seasonality tests to justify complexity.

**What is the bottleneck?** Driver-side staging and serialized database transactions.
The test workload does not locate saturation. Measure first, then introduce distributed
staging, connection pooling, and partitioned state when the workload justifies them.

**What would production require?** Access control, managed secrets, TLS, backups,
retention/backfill policy, durable rejected-event handling, observability, failover,
and workload-specific capacity testing. Those are outside this portfolio release.

## Publication and presentation

The project is public at https://github.com/IceBreaker223/realtime-ecommerce-intelligence.
The README links the recorded walkthrough, engineering guide, and hosted verification.

- Use the repository link when sharing the project; localhost is only your local demo.
- Keep `.env`, runtime stores, virtual environments, and full service logs out of Git.
- Describe this as a synthetic-data portfolio project developed with AI coding assistance.
- Explain decisions you understand and demonstrate results you can reproduce.
- Do not describe the project as unaided work, employer experience, or a production deployment.
- No open-source license has been selected; public visibility alone does not grant a reuse license.

See the [reviewer guide](reviewer-guide.md) for a concise technical walkthrough and
[profile wording](professional-profile.md) for reusable career materials.
