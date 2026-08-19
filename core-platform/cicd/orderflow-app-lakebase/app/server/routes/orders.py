"""CRUD routes for orders (with line items) and customers."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import pool, rows_to_dicts

router = APIRouter(tags=["orders"])


class LineItem(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)


class OrderIn(BaseModel):
    customer_id: int
    items: list[LineItem] = Field(..., min_length=1)


class StatusPatch(BaseModel):
    status: str


# ---------------------------------------------------------------- customers
@router.get("/customers")
def list_customers():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM customers ORDER BY id")
        return rows_to_dicts(cur)


# ---------------------------------------------------------------- orders
@router.get("/orders")
def list_orders():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT o.*, c.name AS customer_name, c.email AS customer_email,
                      COALESCE(cnt.n, 0) AS item_count
               FROM orders o
               JOIN customers c ON c.id = o.customer_id
               LEFT JOIN (SELECT order_id, COUNT(*) n FROM order_items GROUP BY order_id) cnt
                      ON cnt.order_id = o.id
               ORDER BY o.created_at DESC"""
        )
        return rows_to_dicts(cur)


@router.get("/orders/{order_id}")
def get_order(order_id: int):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        orders = rows_to_dicts(cur)
        if not orders:
            raise HTTPException(404, "Order not found")
        cur.execute(
            """SELECT oi.*, p.name AS product_name, p.sku
               FROM order_items oi JOIN products p ON p.id = oi.product_id
               WHERE oi.order_id = %s ORDER BY oi.id""",
            (order_id,),
        )
        items = rows_to_dicts(cur)
    order = orders[0]
    order["items"] = items
    return order


@router.post("/orders", status_code=201)
def create_order(o: OrderIn):
    """Create an order + items in a single transaction, decrementing stock."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (customer_id, status, total) VALUES (%s, 'pending', 0) RETURNING id",
                (o.customer_id,),
            )
            order_id = cur.fetchone()[0]
            total = 0.0
            for item in o.items:
                cur.execute("SELECT price, stock FROM products WHERE id = %s", (item.product_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(400, f"Product {item.product_id} not found")
                price, stock = float(row[0]), row[1]
                if stock < item.quantity:
                    raise HTTPException(400, f"Insufficient stock for product {item.product_id}")
                cur.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
                    (order_id, item.product_id, item.quantity, price),
                )
                cur.execute(
                    "UPDATE products SET stock = stock - %s WHERE id = %s",
                    (item.quantity, item.product_id),
                )
                total += price * item.quantity
            cur.execute("UPDATE orders SET total = %s WHERE id = %s RETURNING *", (total, order_id))
            order = rows_to_dicts(cur)[0]
        conn.commit()
    return order


@router.patch("/orders/{order_id}")
def update_order_status(order_id: int, patch: StatusPatch):
    valid = {"pending", "paid", "shipped", "delivered", "cancelled"}
    if patch.status not in valid:
        raise HTTPException(400, f"Invalid status. Must be one of {sorted(valid)}")
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE orders SET status = %s WHERE id = %s RETURNING *",
                (patch.status, order_id),
            )
            rows = rows_to_dicts(cur)
        conn.commit()
    if not rows:
        raise HTTPException(404, "Order not found")
    return rows[0]


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: int):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM orders WHERE id = %s", (order_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Order not found")
        conn.commit()
