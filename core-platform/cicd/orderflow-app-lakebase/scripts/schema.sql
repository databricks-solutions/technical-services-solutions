-- OrderFlow — Lakebase (Postgres) OLTP schema
-- Applied by scripts/init_db.sh against the `orderflow` database.
-- This is the transactional store the Databricks App reads/writes.

CREATE TABLE IF NOT EXISTS products (
    id          SERIAL PRIMARY KEY,
    sku         VARCHAR(40)  UNIQUE NOT NULL,
    name        VARCHAR(200) NOT NULL,
    category    VARCHAR(80)  NOT NULL DEFAULT 'general',
    price       NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    stock       INT          NOT NULL DEFAULT 0 CHECK (stock >= 0),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customers (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) UNIQUE NOT NULL,
    name        VARCHAR(120) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES customers(id),
    status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','paid','shipped','delivered','cancelled')),
    total        NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INT NOT NULL REFERENCES products(id),
    quantity    INT NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(10,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);
CREATE INDEX IF NOT EXISTS idx_items_order      ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product    ON order_items(product_id);

-- Keep updated_at fresh on row updates.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_products_updated ON products;
CREATE TRIGGER trg_products_updated BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_orders_updated ON orders;
CREATE TRIGGER trg_orders_updated BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
