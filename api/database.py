import os

import psycopg
from psycopg.rows import dict_row


def get_connection():
    """One read-only transaction per request; bounded connect and query waits."""
    with psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "ecommerce"),
        user=os.getenv("POSTGRES_USER", "ecommerce_user"),
        password=os.getenv("POSTGRES_PASSWORD", "ecommerce_password"),
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=5000 -c timezone=UTC",
        row_factory=dict_row,
    ) as connection:
        yield connection
