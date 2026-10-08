import { useState } from "react";
import Dashboard from "./views/Dashboard";
import Products from "./views/Products";
import Orders from "./views/Orders";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "orders", label: "Orders" },
  { id: "products", label: "Products" },
] as const;

type Tab = (typeof TABS)[number]["id"];

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");

  return (
    <div className="min-h-full">
      <header className="border-b border-black/5 bg-brand-navy">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-red font-black text-white">
              O
            </div>
            <div>
              <div className="text-lg font-bold leading-tight text-white">OrderFlow</div>
              <div className="text-xs text-white/50">Order &amp; inventory management</div>
            </div>
          </div>
          <nav className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                  tab === t.id ? "bg-white/15 text-white" : "text-white/60 hover:text-white"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {tab === "dashboard" && <Dashboard />}
        {tab === "orders" && <Orders />}
        {tab === "products" && <Products />}
      </main>

      <footer className="mx-auto max-w-6xl px-6 py-6 text-center text-xs text-brand-navy/40">
        Built on Databricks · Lakebase · Databricks Apps · Lakeflow
      </footer>
    </div>
  );
}
