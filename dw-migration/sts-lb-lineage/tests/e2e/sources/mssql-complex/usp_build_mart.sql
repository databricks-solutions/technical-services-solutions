CREATE PROCEDURE mart.usp_build_mart
AS
BEGIN
    DECLARE @region VARCHAR(20);
    DECLARE region_cursor CURSOR FOR SELECT DISTINCT region FROM dw.dim_store;
    OPEN region_cursor;
    FETCH NEXT FROM region_cursor INTO @region;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        INSERT INTO mart.sales_by_region (region, segment, total_amount)
        SELECT st.region, f.segment, SUM(f.amount)
        FROM dw.fact_sales f
        JOIN dw.dim_store st ON st.store_id = f.store_id
        WHERE st.region = @region
        GROUP BY st.region, f.segment;
        FETCH NEXT FROM region_cursor INTO @region;
    END;
    CLOSE region_cursor;
    DEALLOCATE region_cursor;

    TRUNCATE TABLE mart.top_customers;
    INSERT INTO mart.top_customers (customer_id, total_amount)
    SELECT TOP 100 s.customer_id, SUM(f.amount)
    FROM dw.fact_sales f JOIN stg.customer_segment s ON s.segment = f.segment
    GROUP BY s.customer_id ORDER BY SUM(f.amount) DESC;
END;
GO
