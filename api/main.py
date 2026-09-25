"""Read-only analytics API. Monetary values and rates serialize as decimal strings."""
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.database import get_connection
from api.models import AnomalyPage, BreakdownPage, Dimension, Summary, WindowPage

app = FastAPI(title="E-Commerce Intelligence API", version="0.1.0",
              description="One-minute UTC analytics. Decimal amounts/rates are strings; currency is INR.")
logger = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC / "index.html")


@app.exception_handler(psycopg.Error)
async def database_unavailable(request, exc):
    logger.warning("Analytics database request failed (%s)", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Analytics storage is unavailable or not initialized"})


def time_range(start: datetime | None = None, end: datetime | None = None):
    """UTC minute boundaries, [start, end); default the last 24h including current minute."""
    for name, value in (("start", start), ("end", end)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(422, f"{name} must include a timezone")
        if value is not None and (value.second != 0 or value.microsecond != 0):
            raise HTTPException(422, f"{name} must align to a minute boundary")
    end = (end or (datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1))).astimezone(timezone.utc)
    start = (start or end - timedelta(days=1)).astimezone(timezone.utc)
    if start >= end or end - start > timedelta(days=31):
        raise HTTPException(422, "Require start < end and a range of at most 31 days")
    return start, end


Range = Annotated[tuple[datetime, datetime], Depends(time_range)]
DB = Annotated[psycopg.Connection, Depends(get_connection)]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0, le=100000)]

AGGREGATES = """
    COALESCE(sum(order_count), 0)::bigint AS order_count,
    COALESCE(sum(completed_order_count), 0)::bigint AS completed_order_count,
    COALESCE(sum(completed_revenue), 0) AS completed_revenue,
    COALESCE(sum(failed_order_count), 0)::bigint AS failed_order_count,
    sum(completed_revenue) / NULLIF(sum(completed_order_count), 0) AS average_order_value,
    sum(failed_order_count)::numeric / NULLIF(sum(order_count), 0) AS failed_order_rate,
    max(updated_at) AS last_updated
"""


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def ready(db: DB):
    db.execute("SELECT window_start FROM analytics_minute LIMIT 1")
    return {"status": "ready"}


@app.get("/api/v1/metrics/summary", response_model=Summary, tags=["analytics"])
def summary(period: Range, db: DB):
    start, end = period
    row = db.execute(f"""
        SELECT {AGGREGATES} FROM analytics_minute
        WHERE dimension = 'all' AND window_start >= %s AND window_start < %s
    """, (start, end)).fetchone()
    return dict(row, start=start, end=end)


@app.get("/api/v1/metrics/windows", response_model=WindowPage, tags=["analytics"])
def windows(period: Range, db: DB, dimension: Dimension = "all",
            dimension_value: Annotated[str | None, Query(max_length=200)] = None,
            limit: Limit = 100, offset: Offset = 0):
    if dimension == "all" and dimension_value is not None:
        raise HTTPException(422, "dimension_value requires category or product")
    start, end = period
    filters = "dimension = %s AND window_start >= %s AND window_start < %s"
    params = [dimension, start, end]
    if dimension_value is not None:
        filters += " AND dimension_value = %s"
        params.append(dimension_value)
    rows = db.execute(f"""
        SELECT window_start, dimension, dimension_value, order_count,
               completed_order_count, completed_revenue, failed_order_count,
               average_order_value, failed_order_rate, updated_at AS last_updated
        FROM analytics_minute WHERE {filters}
        ORDER BY window_start DESC, dimension_value ASC LIMIT %s OFFSET %s
    """, params + [limit + 1, offset]).fetchall()
    return dict(start=start, end=end, limit=limit, offset=offset,
                has_more=len(rows) > limit, items=rows[:limit])


@app.get("/api/v1/metrics/breakdown", response_model=BreakdownPage, tags=["analytics"])
def breakdown(period: Range, db: DB, dimension: Literal["category", "product"] = "category",
              limit: Limit = 100, offset: Offset = 0):
    start, end = period
    rows = db.execute(f"""
        SELECT dimension_value, {AGGREGATES}
        FROM analytics_minute
        WHERE dimension = %s AND window_start >= %s AND window_start < %s
        GROUP BY dimension_value
        ORDER BY completed_revenue DESC, dimension_value ASC LIMIT %s OFFSET %s
    """, (dimension, start, end, limit + 1, offset)).fetchall()
    return dict(start=start, end=end, dimension=dimension, limit=limit, offset=offset,
                has_more=len(rows) > limit, items=rows[:limit])


@app.get("/api/v1/anomalies", response_model=AnomalyPage, tags=["anomalies"])
def anomalies(period: Range, db: DB,
              status: Literal["flagged", "normal", "insufficient_data", "all"] = "flagged",
              limit: Limit = 20, offset: Offset = 0):
    start, end = period
    worker = db.execute("SELECT * FROM detector_status WHERE singleton").fetchone()
    if not worker:
        raise HTTPException(503, "Detector has not completed its first evaluation")
    params = [start, end, worker["detector_version"]]
    filters = "window_start >= %s AND window_start < %s AND detector_version = %s"
    counts = db.execute(f"""
        SELECT count(*) AS checked_count,
               count(*) FILTER (WHERE status = 'insufficient_data') AS insufficient_count,
               count(*) FILTER (WHERE status = 'flagged') AS flagged_count
        FROM anomaly_checks WHERE {filters}
    """, params).fetchone()
    if status != "all":
        filters += " AND status = %s"
        params.append(status)
    rows = db.execute(f"""
        SELECT * FROM anomaly_checks WHERE {filters}
        ORDER BY window_start DESC, detector ASC LIMIT %s OFFSET %s
    """, params + [limit + 1, offset]).fetchall()
    return dict(counts, start=start, end=end, limit=limit, offset=offset,
                last_successful_run=worker["last_successful_run"],
                has_more=len(rows) > limit, items=rows[:limit])
