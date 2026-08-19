import { Fragment, useEffect, useState } from "react";
import { api, type Customer, type Order, type Product } from "../api";
import { Button, Card, StatusBadge, money } from "../components/ui";

const STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"];

export default function Orders() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [detail, setDetail] = useState<Record<number, Order>>({});
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.listOrders().then(setOrders).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api.listProducts().then(setProducts);
    api.listCustomers().then(setCustomers);
  }, []);

  async function toggle(id: number) {
    if (expanded === id) return setExpanded(null);
    if (!detail[id]) {
      const o = await api.getOrder(id);
      setDetail((d) => ({ ...d, [id]: o }));
    }
    setExpanded(id);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-brand-navy/50">
          {orders.length} orders
        </h3>
        <Button onClick={() => setCreating(true)}>+ New order</Button>
      </div>

      {error && <p className="text-sm text-brand-red">{error}</p>}

      {creating && (
        <NewOrderForm
          products={products}
          customers={customers}
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            load();
            api.listProducts().then(setProducts);
          }}
        />
      )}

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-brand-sand/60 text-left text-xs uppercase tracking-wide text-brand-navy/50">
            <tr>
              <th className="px-4 py-3">#</th>
              <th className="px-4 py-3">Customer</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Items</th>
              <th className="px-4 py-3 text-right">Total</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-black/5">
            {orders.map((o) => (
              <Fragment key={o.id}>
                <tr className="cursor-pointer hover:bg-brand-cream/60" onClick={() => toggle(o.id)}>
                  <td className="px-4 py-3 font-mono text-xs">#{o.id}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{o.customer_name}</div>
                    <div className="text-xs text-brand-navy/50">{o.customer_email}</div>
                  </td>
                  <td className="px-4 py-3">
                    <select
                      value={o.status}
                      onClick={(e) => e.stopPropagation()}
                      onChange={async (e) => {
                        await api.updateOrderStatus(o.id, e.target.value);
                        load();
                      }}
                      className="rounded-md border border-black/10 bg-white px-2 py-1 text-xs"
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-right">{o.item_count}</td>
                  <td className="px-4 py-3 text-right font-semibold">{money(o.total)}</td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="danger"
                      onClick={async (): Promise<void> => {
                        await api.deleteOrder(o.id);
                        load();
                      }}
                    >
                      Delete
                    </Button>
                  </td>
                </tr>
                {expanded === o.id && detail[o.id] && (
                  <tr className="bg-brand-cream/40">
                    <td colSpan={6} className="px-6 py-3">
                      <div className="flex items-center gap-2 text-xs">
                        <StatusBadge status={o.status} />
                        <span className="text-brand-navy/40">
                          {new Date(o.created_at).toLocaleString()}
                        </span>
                      </div>
                      <table className="mt-2 w-full text-xs">
                        <tbody>
                          {detail[o.id].items?.map((it) => (
                            <tr key={it.id}>
                              <td className="py-1 font-mono text-brand-navy/50">{it.sku}</td>
                              <td className="py-1">{it.product_name}</td>
                              <td className="py-1 text-right">
                                {it.quantity} × {money(it.unit_price)}
                              </td>
                              <td className="py-1 text-right font-semibold">
                                {money(it.quantity * it.unit_price)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function NewOrderForm({
  products,
  customers,
  onClose,
  onCreated,
}: {
  products: Product[];
  customers: Customer[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [customerId, setCustomerId] = useState<number>(customers[0]?.id ?? 0);
  const [lines, setLines] = useState<{ product_id: number; quantity: number }[]>([
    { product_id: products[0]?.id ?? 0, quantity: 1 },
  ]);
  const [error, setError] = useState("");

  const total = lines.reduce((sum, l) => {
    const p = products.find((p) => p.id === l.product_id);
    return sum + (p ? p.price * l.quantity : 0);
  }, 0);

  async function submit() {
    setError("");
    try {
      await api.createOrder(customerId || customers[0].id, lines);
      onCreated();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="font-semibold">New order</h4>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="space-y-3">
        <select
          value={customerId}
          onChange={(e) => setCustomerId(parseInt(e.target.value))}
          className="w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
        >
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.email})
            </option>
          ))}
        </select>

        {lines.map((line, i) => (
          <div key={i} className="flex gap-2">
            <select
              value={line.product_id}
              onChange={(e) => {
                const next = [...lines];
                next[i].product_id = parseInt(e.target.value);
                setLines(next);
              }}
              className="flex-1 rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
            >
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {money(p.price)} ({p.stock} in stock)
                </option>
              ))}
            </select>
            <input
              type="number"
              min={1}
              value={line.quantity}
              onChange={(e) => {
                const next = [...lines];
                next[i].quantity = parseInt(e.target.value) || 1;
                setLines(next);
              }}
              className="w-20 rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
            />
            <Button
              variant="danger"
              onClick={() => setLines(lines.filter((_, idx) => idx !== i))}
              disabled={lines.length === 1}
            >
              ✕
            </Button>
          </div>
        ))}

        <Button
          variant="ghost"
          onClick={() => setLines([...lines, { product_id: products[0]?.id ?? 0, quantity: 1 }])}
        >
          + Add line
        </Button>

        {error && <p className="text-sm text-brand-red">{error}</p>}

        <div className="flex items-center justify-between border-t border-black/5 pt-3">
          <span className="text-lg font-bold">{money(total)}</span>
          <Button onClick={submit}>Create order</Button>
        </div>
      </div>
    </Card>
  );
}
