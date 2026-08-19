-- OrderFlow — seed data. Idempotent: safe to re-run.
INSERT INTO products (sku, name, category, price, stock) VALUES
    ('WID-001', 'Aluminum Widget',      'widgets',     9.99, 500),
    ('WID-002', 'Titanium Widget',      'widgets',    29.99, 220),
    ('GAD-001', 'Smart Gadget',         'gadgets',    49.99, 140),
    ('GAD-002', 'Pro Gadget',           'gadgets',    99.99,  60),
    ('GIZ-001', 'Pocket Gizmo',         'gizmos',     14.99, 300),
    ('GIZ-002', 'Deluxe Gizmo',         'gizmos',     39.99,  90),
    ('ACC-001', 'USB-C Cable',          'accessories', 7.49, 800),
    ('ACC-002', 'Carrying Case',        'accessories',19.99, 180)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO customers (email, name) VALUES
    ('ava@example.com',   'Ava Thompson'),
    ('liam@example.com',  'Liam Chen'),
    ('noah@example.com',  'Noah Patel'),
    ('emma@example.com',  'Emma Rossi'),
    ('olivia@example.com','Olivia Kim')
ON CONFLICT (email) DO NOTHING;

-- A couple of sample orders so the pipeline has data on first run.
WITH seed_orders AS (
  SELECT c.id AS customer_id, s.status, s.days_ago
  FROM (VALUES
      ('ava@example.com',   'delivered', 12),
      ('liam@example.com',  'shipped',    5),
      ('noah@example.com',  'paid',       2),
      ('emma@example.com',  'pending',    0)
  ) AS s(email, status, days_ago)
  JOIN customers c ON c.email = s.email
)
INSERT INTO orders (customer_id, status, total, created_at)
SELECT customer_id, status, 0, now() - (days_ago || ' days')::interval
FROM seed_orders
WHERE NOT EXISTS (SELECT 1 FROM orders);  -- only seed when table is empty

-- Line items for the seeded orders, then recompute totals.
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT o.id, p.id, gs.qty, p.price
FROM orders o
JOIN LATERAL (VALUES (1,2),(3,1),(5,3)) AS gs(prod_rank, qty) ON TRUE
JOIN (SELECT id, price, row_number() OVER (ORDER BY id) rn FROM products) p ON p.rn = gs.prod_rank
WHERE NOT EXISTS (SELECT 1 FROM order_items)
;

UPDATE orders o SET total = COALESCE(sub.s, 0)
FROM (SELECT order_id, SUM(quantity*unit_price) s FROM order_items GROUP BY order_id) sub
WHERE sub.order_id = o.id AND o.total = 0;
