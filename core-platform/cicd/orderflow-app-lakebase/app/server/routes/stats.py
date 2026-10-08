"""Dashboard summary stats computed live from Lakebase."""
from fastapi import APIRouter

from ..db import pool, rows_to_dicts

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
def dashboard_stats():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM products")
        product_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM orders")
        order_count = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(total), 0) FROM orders WHERE status <> 'cancelled'")
        revenue = float(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM orders WHERE status IN ('pending','paid','shipped')")
        open_orders = cur.fetchone()[0]
        cur.execute(
            """SELECT status, COUNT(*) AS count, COALESCE(SUM(total),0) AS value
               FROM orders GROUP BY status ORDER BY count DESC"""
        )
        by_status = rows_to_dicts(cur)
        cur.execute("SELECT sku, name, stock FROM products WHERE stock < 100 ORDER BY stock LIMIT 5")
        low_stock = rows_to_dicts(cur)
    return {
        "product_count": product_count,
        "order_count": order_count,
        "revenue": round(revenue, 2),
        "open_orders": open_orders,
        "by_status": by_status,
        "low_stock": low_stock,
    }
