from faker import Faker
from kafka import KafkaProducer
import os
import random
import uuid
import json
import time
from datetime import datetime, timezone

fake = Faker("en_IN")

PRODUCTS = [
    ("Gaming Mouse", "Electronics", 1499),
    ("Mechanical Keyboard", "Electronics", 3499),
    ("Wireless Headphones", "Electronics", 4999),
    ("Laptop Stand", "Accessories", 1299),
    ("USB-C Hub", "Accessories", 2199),
    ("Running Shoes", "Fashion", 2999),
    ("Backpack", "Fashion", 1999),
    ("Smart Watch", "Electronics", 6999),
]

PAYMENT_METHODS = [
    "UPI",
    "Credit Card",
    "Debit Card",
    "Net Banking",
    "Cash on Delivery",
]

def generate_order():
    product_name, category, base_price = random.choice(PRODUCTS)

    quantity = random.randint(1, 4)
    total_amount = base_price * quantity

    order = {
        "event_id": str(uuid.uuid4()),
        "order_id": f"ORD-{random.randint(100000, 999999)}",
        "customer_id": f"CUST-{random.randint(1000, 9999)}",
        "customer_name": fake.name(),
        "city": fake.city(),
        "product": product_name,
        "category": category,
        "quantity": quantity,
        "unit_price": base_price,
        "total_amount": total_amount,
        "payment_method": random.choice(PAYMENT_METHODS),
        "status": random.choice(
            ["completed", "completed", "completed", "pending", "failed"]
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return order


if __name__ == "__main__":
    producer = KafkaProducer(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        acks="all",
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    print("Starting e-commerce Kafka producer...\n")

    try:
        while True:
            order = generate_order()

            producer.send(
                os.getenv("KAFKA_TOPIC", "ecommerce-orders"),
                value=order
            ).get(timeout=30)

            producer.flush()

            print(
                f"Sent: {order['order_id']} | "
                f"{order['product']} | "
                f"₹{order['total_amount']}"
            )

            time.sleep(2)

    except KeyboardInterrupt:
        print("\nProducer stopped.")

    finally:
        producer.close()
