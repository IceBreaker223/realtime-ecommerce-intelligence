"""Transactional event ledger + Spark-computed minute deltas for a small demo.

The ledger and aggregate changes commit together. Event IDs, rather than Spark
batch IDs, protect against replay even when a checkpoint is replaced.
"""
import os
from datetime import timezone
from pathlib import Path

import psycopg
from pyspark.sql import functions as F

FIELDS = ("event_id", "event_timestamp", "product", "category", "status", "total_amount")


def connect():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "ecommerce"),
        user=os.getenv("POSTGRES_USER", "ecommerce_user"),
        password=os.getenv("POSTGRES_PASSWORD", "ecommerce_password"),
    )


def minute_metrics(orders):
    dimensions = F.array(
        F.struct(F.lit("all").alias("kind"), F.lit("").alias("value")),
        F.struct(F.lit("category").alias("kind"), F.col("category").alias("value")),
        F.struct(F.lit("product").alias("kind"), F.col("product").alias("value")),
    )
    expanded = orders.withColumn("dimension", F.explode(dimensions))
    completed = F.col("status") == "completed"
    return expanded.groupBy(
        F.window("event_timestamp", "1 minute").alias("minute"),
        F.col("dimension.kind").alias("dimension"),
        F.col("dimension.value").alias("dimension_value"),
    ).agg(
        F.count("*").alias("order_count"),
        F.sum(F.when(completed, 1).otherwise(0)).alias("completed_order_count"),
        F.sum(F.when(completed, F.col("total_amount")).otherwise(0)).alias("completed_revenue"),
        F.sum(F.when(F.col("status") == "failed", 1).otherwise(0)).alias("failed_order_count"),
    ).select(F.col("minute.start").alias("window_start"), "dimension", "dimension_value",
             "order_count", "completed_order_count", "completed_revenue", "failed_order_count")


def write_metrics(connection, aggregates):
    with connection.cursor() as cursor:
        for row in aggregates.toLocalIterator():
            values = list(row)
            values[0] = values[0].replace(tzinfo=timezone.utc)
            cursor.execute("""
                INSERT INTO analytics_minute
                    (window_start, dimension, dimension_value, order_count,
                     completed_order_count, completed_revenue, failed_order_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (window_start, dimension, dimension_value) DO UPDATE SET
                    order_count = analytics_minute.order_count + EXCLUDED.order_count,
                    completed_order_count = analytics_minute.completed_order_count + EXCLUDED.completed_order_count,
                    completed_revenue = analytics_minute.completed_revenue + EXCLUDED.completed_revenue,
                    failed_order_count = analytics_minute.failed_order_count + EXCLUDED.failed_order_count,
                    updated_at = CURRENT_TIMESTAMP
            """, values)


def persist_batch(batch, connection):
    """First accepted payload wins for an immutable event_id; conflicts fail closed."""
    valid = batch.filter("is_valid").select(*FIELDS).withColumn("event_id", F.lower("event_id"))
    with connection.transaction():
        # Serialize writers across the ledger and aggregates, including replays.
        connection.execute("SELECT pg_advisory_xact_lock(72409101)")
        connection.execute("SET LOCAL TIME ZONE 'UTC'")
        connection.execute(Path(__file__).with_name("analytics.sql").read_text())
        connection.execute("CREATE TEMP TABLE incoming_events (LIKE analytics_events) ON COMMIT DROP")
        with connection.cursor() as cursor:
            with cursor.copy("COPY incoming_events FROM STDIN") as copy:
                for row in valid.toLocalIterator():
                    values = list(row)
                    values[1] = values[1].replace(tzinfo=timezone.utc)
                    copy.write_row(values)
        # A reused ID with a changed payload is not an order lifecycle update.
        conflict = connection.execute("""
            SELECT 1 FROM (
                SELECT * FROM incoming_events
                UNION SELECT e.* FROM analytics_events e
                    JOIN incoming_events i USING (event_id)
            ) payloads GROUP BY event_id HAVING count(*) > 1 LIMIT 1
        """).fetchone()
        if conflict:
            raise ValueError("Conflicting payloads for an immutable event_id")
        inserted = connection.execute("""
            INSERT INTO analytics_events SELECT DISTINCT * FROM incoming_events
            ON CONFLICT (event_id) DO NOTHING RETURNING event_id
        """).fetchall()
        if inserted:
            ids = batch.sparkSession.createDataFrame([(str(r[0]),) for r in inserted], ["event_id"])
            new_orders = valid.dropDuplicates(["event_id"]).join(ids, "event_id", "inner")
            write_metrics(connection, minute_metrics(new_orders))
        return len(inserted)


def save_batch(batch, batch_id):
    batch.persist()
    try:
        rejected = batch.filter("not is_valid").count()
        with connect() as connection:
            inserted = persist_batch(batch, connection)
        print(f"Batch {batch_id}: committed {inserted} new events; rejected {rejected}", flush=True)
    finally:
        batch.unpersist()
