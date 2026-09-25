CREATE TABLE IF NOT EXISTS analytics_events (
    event_id UUID PRIMARY KEY,
    event_timestamp TIMESTAMPTZ NOT NULL,
    product TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'pending', 'failed')),
    total_amount NUMERIC(12,2) NOT NULL CHECK (total_amount >= 0)
);

CREATE TABLE IF NOT EXISTS analytics_minute (
    window_start TIMESTAMPTZ NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('all', 'category', 'product')),
    dimension_value TEXT NOT NULL,
    order_count BIGINT NOT NULL,
    completed_order_count BIGINT NOT NULL,
    completed_revenue NUMERIC(24,2) NOT NULL,
    failed_order_count BIGINT NOT NULL,
    average_order_value NUMERIC GENERATED ALWAYS AS
        (completed_revenue / NULLIF(completed_order_count, 0)) STORED,
    failed_order_rate NUMERIC GENERATED ALWAYS AS
        (failed_order_count::NUMERIC / NULLIF(order_count, 0)) STORED,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (window_start, dimension, dimension_value)
);
