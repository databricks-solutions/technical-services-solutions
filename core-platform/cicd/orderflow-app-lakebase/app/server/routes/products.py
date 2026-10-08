"""CRUD routes for products / inventory."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import pool, rows_to_dicts

router = APIRouter(prefix="/products", tags=["products"])


class ProductIn(BaseModel):
    sku: str = Field(..., max_length=40)
    name: str = Field(..., max_length=200)
    category: str = "general"
    price: float = Field(..., ge=0)
    stock: int = Field(0, ge=0)


class ProductPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    price: float | None = Field(None, ge=0)
    stock: int | None = Field(None, ge=0)


@router.get("")
def list_products():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM products ORDER BY id")
        return rows_to_dicts(cur)


@router.get("/{product_id}")
def get_product(product_id: int):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(404, "Product not found")
    return rows[0]


@router.post("", status_code=201)
def create_product(p: ProductIn):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO products (sku, name, category, price, stock)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (p.sku, p.name, p.category, p.price, p.stock),
            )
            row = rows_to_dicts(cur)[0]
        conn.commit()
    return row


@router.patch("/{product_id}")
def update_product(product_id: int, patch: ProductPatch):
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    sets = ", ".join(f"{k} = %s" for k in fields)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE products SET {sets} WHERE id = %s RETURNING *",
                (*fields.values(), product_id),
            )
            rows = rows_to_dicts(cur)
        conn.commit()
    if not rows:
        raise HTTPException(404, "Product not found")
    return rows[0]


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Product not found")
        conn.commit()
