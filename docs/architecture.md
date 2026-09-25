# Architecture and engineering decisions

## 1. Event identity is the accounting boundary

Each immutable order snapshot has a UUID `event_id`. Neither Kafka offsets nor Spark
batch IDs identify business events: offsets change on republishing, and batch IDs
can restart with a new checkpoint. The ledger's primary key enforces uniqueness.
If an ID is reused with conflicting analytics fields, ingestion fails for investigation.
Status updates/refunds need a versioned event contract rather than overwriting this rule.

The raw order consumer uses at-least-once delivery: commit SQL, then that record's
offset. A crash between those operations replays the record; `ON CONFLICT` prevents
a second raw row. This is not a global exactly-once transaction between Kafka and SQL.

## 2. Ledger and aggregate deltas commit atomically

Spark validates typed JSON, stages valid rows into a temporary PostgreSQL table,
inserts previously unseen IDs, computes minute deltas for those IDs, and updates
the aggregates within one transaction. A transaction-level advisory lock serializes
writers. Failure before commit rolls everything back; failure after commit is safe
to replay because the ledger already contains the affected IDs.

This trades throughput for understandable correctness. Records pass through the
Spark driver, each trigger is capped at 10,000 source records, and a SQL transaction
remains open during aggregation. Larger systems should use distributed staging and
explicit sink coordination. The benchmark documents this implementation, not that
future architecture.

## 3. Event-time minutes remain revisable

Windows are UTC `[start, start + 1 minute)`. Money uses fixed-precision decimals.
AOV is cumulative completed revenue divided by completed count; failure rate uses
all valid orders including pending. Empty minutes have no row and undefined averages
are null. Category, product, and overall rows are separate views of the same events;
they must not be summed together.

Late events update past minutes without a watermark cutoff. Deduplication state is
durable in PostgreSQL rather than bounded in Spark memory. The tradeoff is an unbounded
ledger and no claim that historical minutes are final. Future retention must be
coordinated with Kafka replay and backfill policies.

## 4. Operational state is separate from business state

Persistent checkpoints resume Kafka offsets; the event ledger protects accounting.
The raw orders table is separate from analytics and is not automatically backfilled
into Spark. Therefore legacy raw counts can exceed retained Kafka-derived analytics.
The independent SQL reconciliation query is the authority for aggregate consistency.

The dashboard distinguishes API access, aggregate freshness, and detector heartbeat.
It does not infer Kafka/Spark health from a successful HTTP response or zero orders.
There is no external alert delivery: anomaly signals remain in the database/UI.

## 5. Statistical baseline before trained ML

The detector compares a minute with the preceding 60 minutes of active history,
excluding future data. It abstains when the sample is too small. Rules flag unusually
high failure rates and revenue, and retain observed value, threshold, baseline,
sample size, version, and evaluation time. The last 24 hours are recomputed every
30 seconds after a two-minute lateness allowance; older checks remain snapshots.

Synthetic labeled tests prove the mechanics and prevent leakage. Their perfect
scores on deliberately easy examples do not establish real-world accuracy. A trained
model should be evaluated on held-out, more realistic scenarios before replacing
the baseline.

## 6. Small deployment surface

FastAPI serves both API and static dashboard; no separate frontend build or CDN is
required. Read-only transactions and bounded queries keep the API behavior explicit.
Named Docker volumes and pinned base images make the demo portable. The API currently
opens one connection per request, has no authentication, and is bound to localhost.
Production deployment needs secrets management, access control, connection pooling,
backups, retention, metrics, and high availability; v1 does not claim these capabilities.
