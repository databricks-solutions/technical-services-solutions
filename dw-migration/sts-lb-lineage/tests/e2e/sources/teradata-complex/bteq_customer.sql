.LOGON tdpid/user,password;

CREATE VOLATILE TABLE vt_active AS (
  SEL c.customer_id, c.segment, a.region
  FROM raw.customer c
  INNER JOIN raw.address a ON a.customer_id = c.customer_id
  QUALIFY ROW_NUMBER() OVER (PARTITION BY c.customer_id ORDER BY a.valid_from DESC) = 1
) WITH DATA ON COMMIT PRESERVE ROWS;

MERGE INTO dw.dim_customer t
USING vt_active s
ON t.customer_id = s.customer_id
WHEN MATCHED THEN UPDATE SET segment = s.segment, region = s.region
WHEN NOT MATCHED THEN INSERT (customer_id, segment, region) VALUES (s.customer_id, s.segment, s.region);

INS INTO mart.customer_counts (region, segment, n)
SEL d.region, d.segment, COUNT(*) FROM dw.dim_customer d
INNER JOIN dw.fact_sales f ON f.customer_id = d.customer_id
GROUP BY 1, 2;

.IF ERRORCODE <> 0 THEN .QUIT 8;
.LOGOFF;
.QUIT 0;
