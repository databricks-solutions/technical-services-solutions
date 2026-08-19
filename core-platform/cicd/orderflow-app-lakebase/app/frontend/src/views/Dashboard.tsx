import { useEffect, useState } from "react";
import { api, type Stats } from "../api";
import { Card, StatusBadge, money } from "../components/ui";

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <Card className="p-5">
      <div className="text-sm font-medium text-brand-navy/50">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${accent ? "text-brand-red" : "text-brand-navy"}`}>{value}</div>
    </Card>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="text-brand-red">Failed to load: {error}</div>;
  if (!stats) return <div className="text-brand-navy/40">Loading dashboard…</div>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Revenue" value={money(stats.revenue)} accent />
        <Stat label="Orders" value={String(stats.order_count)} />
        <Stat label="Open orders" value={String(stats.open_orders)} />
        <Stat label="Products" value={String(stats.product_count)} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-brand-navy/50">
            Orders by status
          </h3>
          <div className="space-y-3">
            {stats.by_status.map((s) => (
              <div key={s.status} className="flex items-center justify-between">
                <StatusBadge status={s.status} />
                <div className="text-sm text-brand-navy/70">
                  <span className="font-semibold text-brand-navy">{s.count}</span> orders ·{" "}
                  {money(s.value)}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-brand-navy/50">
            Low stock watchlist
          </h3>
          {stats.low_stock.length === 0 ? (
            <p className="text-sm text-brand-navy/40">All products well stocked.</p>
          ) : (
            <div className="space-y-2">
              {stats.low_stock.map((p) => (
                <div key={p.sku} className="flex items-center justify-between text-sm">
                  <span className="font-medium">{p.name}</span>
                  <span
                    className={`font-semibold ${p.stock < 100 ? "text-brand-red" : "text-brand-navy/60"}`}
                  >
                    {p.stock} left
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
