import json
from kafka import KafkaConsumer

consumer = KafkaConsumer(
    "ecommerce-orders",
    bootstrap_servers="localhost:9092",
    auto_offset_reset="earliest",
    enable_auto_commit=True,
    group_id="ecommerce-consumer-group",
    value_deserializer=lambda message: json.loads(
        message.decode("utf-8")
    )
)

print("Waiting for ecommerce orders...\n")

try:
    for message in consumer:
        order = message.value

        print(
            f"Received: {order['order_id']} | "
            f"{order['product']} | "
            f"₹{order['total_amount']} | "
            f"{order['status']}"
        )

except KeyboardInterrupt:
    print("\nConsumer stopped.")

finally:
    consumer.close()