"""Typed Kafka orders with durable minute analytics; run in Docker."""
import os
from pyspark.sql import SparkSession, functions as F, types as T

ORDER_SCHEMA = T.StructType([
    T.StructField(name, T.StringType()) for name in (
        "event_id", "order_id", "customer_id", "customer_name", "city",
        "product", "category", "payment_method", "status", "timestamp",
    )
] + [
    T.StructField("quantity", T.IntegerType()),
    T.StructField("unit_price", T.DecimalType(12, 2)),
    T.StructField("total_amount", T.DecimalType(12, 2)),
])


def parse_orders(messages):
    orders = messages.select(
        F.from_json(F.col("value").cast("string"), ORDER_SCHEMA).alias("order")
    ).select("order.*").withColumn(
        "event_timestamp", F.expr("try_cast(timestamp as timestamp)")
    )
    valid = (
        F.col("event_id").rlike(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
        & F.col("event_timestamp").isNotNull()
        & F.col("product").isNotNull()
        & F.col("category").isNotNull()
        & F.col("status").isin("completed", "pending", "failed")
        & (F.col("quantity") > 0)
        & (F.col("unit_price") >= 0)
        & (F.col("total_amount") == F.col("quantity") * F.col("unit_price"))
    )
    return orders.withColumn("is_valid", F.coalesce(valid, F.lit(False)))


def metrics(orders, *dimensions):
    completed = F.col("status") == "completed"
    return orders.groupBy(*dimensions).agg(
        F.count("*").alias("order_count"),
        F.sum(F.when(completed, 1).otherwise(0)).alias("completed_order_count"),
        F.sum(F.when(completed, F.col("total_amount")).otherwise(0)).alias("completed_revenue"),
        F.avg(F.when(completed, F.col("total_amount"))).alias("average_order_value"),
        F.sum(F.when(F.col("status") == "failed", 1).otherwise(0)).alias("failed_order_count"),
        F.avg(F.when(F.col("status") == "failed", 1.0).otherwise(0.0)).alias("failed_order_rate"),
    )


def main():
    from analytics_sink import save_batch
    spark = (SparkSession.builder.appName("EcommerceKafkaStream")
             .master("local[2]").config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", "2").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    try:
        messages = (spark.readStream.format("kafka")
                    .option("kafka.bootstrap.servers", os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092"))
                    .option("subscribe", os.getenv("KAFKA_TOPIC", "ecommerce-orders"))
                    .option("startingOffsets", "earliest")
                    .option("maxOffsetsPerTrigger", "10000").load())
        query = (parse_orders(messages).writeStream.foreachBatch(save_batch)
                 .option("checkpointLocation", os.getenv("SPARK_CHECKPOINT_DIR", "/tmp/ecommerce-checkpoints"))
                 .trigger(processingTime="10 seconds").start())
        query.awaitTermination()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
