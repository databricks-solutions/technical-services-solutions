import { useEffect, useState } from "react";
import { api, type Product } from "../api";
import { Button, Card, Input, money } from "../components/ui";

const EMPTY = { sku: "", name: "", category: "general", price: 0, stock: 0 };

export default function Products() {
  const [products, setProducts] = useState<Product[]>([]);
  const [form, setForm] = useState<Omit<Product, "id">>(EMPTY);
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = () => api.listProducts().then(setProducts).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function submit() {
    setError("");
    try {
      if (editing) await api.updateProduct(editing, form);
      else await api.createProduct(form);
      setForm(EMPTY);
      setEditing(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Card className="h-fit p-5 lg:col-span-1">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-brand-navy/50">
          {editing ? "Edit product" : "New product"}
        </h3>
        <div className="space-y-3">
          <Input
            placeholder="SKU"
            value={form.sku}
            disabled={!!editing}
            onChange={(e) => setForm({ ...form, sku: e.target.value })}
          />
          <Input
            placeholder="Name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Input
            placeholder="Category"
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              type="number"
              placeholder="Price"
              value={form.price}
              onChange={(e) => setForm({ ...form, price: parseFloat(e.target.value) || 0 })}
            />
            <Input
              type="number"
              placeholder="Stock"
              value={form.stock}
              onChange={(e) => setForm({ ...form, stock: parseInt(e.target.value) || 0 })}
            />
          </div>
          {error && <p className="text-sm text-brand-red">{error}</p>}
          <div className="flex gap-2">
            <Button onClick={submit} disabled={!form.sku || !form.name}>
              {editing ? "Save changes" : "Add product"}
            </Button>
            {editing && (
              <Button
                variant="ghost"
                onClick={() => {
                  setEditing(null);
                  setForm(EMPTY);
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </div>
      </Card>

      <Card className="overflow-hidden lg:col-span-2">
        <table className="w-full text-sm">
          <thead className="bg-brand-sand/60 text-left text-xs uppercase tracking-wide text-brand-navy/50">
            <tr>
              <th className="px-4 py-3">SKU</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3 text-right">Price</th>
              <th className="px-4 py-3 text-right">Stock</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-black/5">
            {products.map((p) => (
              <tr key={p.id} className="hover:bg-brand-cream/60">
                <td className="px-4 py-3 font-mono text-xs">{p.sku}</td>
                <td className="px-4 py-3 font-medium">{p.name}</td>
                <td className="px-4 py-3 capitalize text-brand-navy/60">{p.category}</td>
                <td className="px-4 py-3 text-right">{money(p.price)}</td>
                <td className={`px-4 py-3 text-right font-semibold ${p.stock < 100 ? "text-brand-red" : ""}`}>
                  {p.stock}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setEditing(p.id);
                        setForm({ sku: p.sku, name: p.name, category: p.category, price: p.price, stock: p.stock });
                      }}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="danger"
                      onClick={async () => {
                        await api.deleteProduct(p.id);
                        load();
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
