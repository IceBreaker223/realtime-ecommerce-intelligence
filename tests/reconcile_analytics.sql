-- Independent SQL calculation: zero rows means every stored metric matches.
SET TIME ZONE 'UTC';
WITH expected AS (
    SELECT date_trunc('minute', event_timestamp) AS window_start,
           d.dimension, d.dimension_value,
           count(*) AS order_count,
           count(*) FILTER (WHERE status = 'completed') AS completed_order_count,
           coalesce(sum(total_amount) FILTER (WHERE status = 'completed'), 0) AS completed_revenue,
           count(*) FILTER (WHERE status = 'failed') AS failed_order_count,
           avg(total_amount) FILTER (WHERE status = 'completed') AS average_order_value,
           count(*) FILTER (WHERE status = 'failed')::numeric / count(*) AS failed_order_rate
    FROM analytics_events
    CROSS JOIN LATERAL (VALUES ('all', ''), ('category', category), ('product', product))
        AS d(dimension, dimension_value)
    GROUP BY 1, 2, 3
)
SELECT coalesce(e.window_start, a.window_start) AS window_start,
       coalesce(e.dimension, a.dimension) AS dimension,
       coalesce(e.dimension_value, a.dimension_value) AS dimension_value
FROM expected e FULL OUTER JOIN analytics_minute a
    USING (window_start, dimension, dimension_value)
WHERE ROW(e.order_count, e.completed_order_count, e.completed_revenue,
          e.failed_order_count, e.average_order_value, e.failed_order_rate)
   IS DISTINCT FROM
      ROW(a.order_count, a.completed_order_count, a.completed_revenue,
          a.failed_order_count, a.average_order_value, a.failed_order_rate);
