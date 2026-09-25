import json
import os
from kafka.structs import OffsetAndMetadata, TopicPartition
import psycopg
from kafka import KafkaConsumer

DB_CONFIG = {
    "dbname": os.getenv("POSTGRES_DB", "ecommerce"),
    "user": os.getenv("POSTGRES_USER", "ecommerce_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "ecommerce_password"),
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
}

consumer = KafkaConsumer(
    os.getenv("KAFKA_TOPIC", "ecommerce-orders"),
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    auto_offset_reset="earliest",
    enable_auto_commit=False,
    group_id="ecommerce-db-consumer",
    value_deserializer=lambda message: json.loads(
        message.decode("utf-8")
    ),
)

connection = psycopg.connect(**DB_CONFIG)
cursor = connection.cursor()
cursor.execute("SET TIME ZONE 'UTC'")

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS orders (
        event_id UUID PRIMARY KEY,
        order_id VARCHAR(30),
        customer_id VARCHAR(30),
        customer_name VARCHAR(150),
        city VARCHAR(100),
        product VARCHAR(150),
        category VARCHAR(100),
        quantity INTEGER,
        unit_price NUMERIC(12,2),
        total_amount NUMERIC(12,2),
        payment_method VARCHAR(50),
        status VARCHAR(30),
        event_timestamp TIMESTAMP
    );
    """
)

connection.commit()

print("Waiting for Kafka orders and saving them to PostgreSQL...\n")

try:
    for message in consumer:
        order = message.value

        cursor.execute(
            """
            INSERT INTO orders (
                event_id,
                order_id,
                customer_id,
                customer_name,
                city,
                product,
                category,
                quantity,
                unit_price,
                total_amount,
                payment_method,
                status,
                event_timestamp
            )
            VALUES (
                %(event_id)s,
                %(order_id)s,
                %(customer_id)s,
                %(customer_name)s,
                %(city)s,
                %(product)s,
                %(category)s,
                %(quantity)s,
                %(unit_price)s,
                %(total_amount)s,
                %(payment_method)s,
                %(status)s,
                %(timestamp)s
            )
            ON CONFLICT (event_id) DO NOTHING;
            """,
            order,
        )

        connection.commit()
        # A replay after a crash is safe because event_id is a primary key.
        # Commit only this saved record, not positions of other fetched records.
        consumer.commit({
            TopicPartition(message.topic, message.partition):
                OffsetAndMetadata(message.offset + 1, "", -1)
        })

        print(
            f"Saved: {order['order_id']} | "
            f"{order['product']} | "
            f"₹{order['total_amount']} | "
            f"{order['status']}"
        )

except KeyboardInterrupt:
    print("\nDatabase consumer stopped.")

finally:
    cursor.close()
    connection.close()
    consumer.close()
