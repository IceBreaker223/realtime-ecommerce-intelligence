from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Dimension = Literal["all", "category", "product"]


class Metrics(BaseModel):
    order_count: int
    completed_order_count: int
    completed_revenue: Decimal
    failed_order_count: int
    average_order_value: Decimal | None
    failed_order_rate: Decimal | None
    last_updated: datetime | None


class Summary(Metrics):
    start: datetime
    end: datetime
    currency: Literal["INR"] = "INR"


class Window(Metrics):
    window_start: datetime
    dimension: Dimension
    dimension_value: str


class Breakdown(Metrics):
    dimension_value: str


class WindowPage(BaseModel):
    start: datetime
    end: datetime
    limit: int
    offset: int
    has_more: bool
    items: list[Window]


class BreakdownPage(BaseModel):
    start: datetime
    end: datetime
    dimension: Literal["category", "product"]
    limit: int
    offset: int
    has_more: bool
    items: list[Breakdown]


class Anomaly(BaseModel):
    window_start: datetime
    detector: str
    detector_version: str
    status: Literal["flagged", "normal", "insufficient_data"]
    unit: str
    observed_value: float
    baseline_value: float | None
    threshold: float | None
    baseline_windows: int
    baseline_orders: int
    current_orders: int
    explanation: str
    first_flagged_at: datetime | None
    evaluated_at: datetime


class AnomalyPage(BaseModel):
    start: datetime
    end: datetime
    limit: int
    offset: int
    has_more: bool
    last_successful_run: datetime | None
    checked_count: int
    insufficient_count: int
    flagged_count: int
    items: list[Anomaly]
