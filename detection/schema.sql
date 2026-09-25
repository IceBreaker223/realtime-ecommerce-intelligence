CREATE TABLE IF NOT EXISTS anomaly_checks (
    window_start TIMESTAMPTZ NOT NULL,
    detector TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('flagged', 'normal', 'insufficient_data')),
    unit TEXT NOT NULL,
    observed_value DOUBLE PRECISION NOT NULL,
    baseline_value DOUBLE PRECISION,
    threshold DOUBLE PRECISION,
    baseline_windows INTEGER NOT NULL,
    baseline_orders BIGINT NOT NULL,
    current_orders BIGINT NOT NULL,
    explanation TEXT NOT NULL,
    first_flagged_at TIMESTAMPTZ,
    evaluated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (window_start, detector, detector_version)
);
CREATE TABLE IF NOT EXISTS detector_status (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    last_successful_run TIMESTAMPTZ NOT NULL,
    detector_version TEXT NOT NULL
);
