GET DATA /TYPE=ODBC /CONNECT='DSN=srcdb' /SQL='SELECT customer_id, status FROM raw.orders WHERE status IS NOT NULL'.
SAVE TRANSLATE /TYPE=ODBC /CONNECT='DSN=stgdb' /TABLE='stg.orders_clean' /REPLACE.
GET DATA /TYPE=ODBC /CONNECT='DSN=stgdb' /SQL='SELECT customer_id, count(*) AS n FROM stg.orders_clean GROUP BY customer_id'.
SAVE TRANSLATE /TYPE=ODBC /CONNECT='DSN=dwdb' /TABLE='dw.fact_orders' /REPLACE.
