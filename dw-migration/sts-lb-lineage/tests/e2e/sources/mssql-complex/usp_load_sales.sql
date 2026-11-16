CREATE PROCEDURE dw.usp_load_sales @load_date DATE
AS
BEGIN
    SET NOCOUNT ON;

    SELECT o.order_id, o.customer_id, o.order_date, l.product_id, l.qty * l.unit_price AS amount
    INTO #orders
    FROM raw.orders o
    JOIN raw.order_lines l ON l.order_id = o.order_id
    WHERE o.order_date = @load_date;

    WITH latest AS (
        SELECT customer_id, segment, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY valid_from DESC) AS rn
        FROM raw.customer_history
    )
    INSERT INTO stg.customer_segment (customer_id, segment)
    SELECT customer_id, segment FROM latest WHERE rn = 1;

    MERGE dw.fact_sales AS t
    USING (
        SELECT x.order_id, x.product_id, x.amount, s.segment, d.date_key
        FROM #orders x
        JOIN stg.customer_segment s ON s.customer_id = x.customer_id
        JOIN dw.dim_date d ON d.calendar_date = x.order_date
    ) AS src
    ON t.order_id = src.order_id AND t.product_id = src.product_id
    WHEN MATCHED THEN UPDATE SET t.amount = src.amount, t.segment = src.segment
    WHEN NOT MATCHED THEN INSERT (order_id, product_id, amount, segment, date_key)
        VALUES (src.order_id, src.product_id, src.amount, src.segment, src.date_key);

    DECLARE @sql NVARCHAR(MAX) = N'DELETE FROM stg.load_audit WHERE load_date < DATEADD(day, -30, @d)';
    EXEC sp_executesql @sql, N'@d DATE', @d = @load_date;

    INSERT INTO stg.load_audit (load_date, row_count) SELECT @load_date, COUNT(*) FROM #orders;
END;
GO
