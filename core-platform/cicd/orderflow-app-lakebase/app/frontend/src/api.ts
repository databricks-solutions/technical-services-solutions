// Thin typed fetch wrapper around the FastAPI backend.
export interface Product {
  id: number;
  sku: string;
  name: string;
  category: string;
  price: number;
  stock: number;
}

export interface Customer {
  id: number;
  name: string;
  email: string;
}

export interface OrderItem {
  id: number;
  product_id: number;
  product_name: string;
  sku: string;
  quantity: number;
  unit_price: number;
}

export interface Order {
  id: number;
  customer_id: number;
  customer_name?: string;
  customer_email?: string;
  status: string;
  total: number;
  created_at: string;
  item_count?: number;
  items?: OrderItem[];
}

export interface Stats {
  product_count: number;
  order_count: number;
  revenue: number;
  open_orders: number;
  by_status: { status: string; count: number; value: number }[];
  low_stock: { sku: string; name: string; stock: number }[];
}

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  stats: () => req<Stats>("/api/stats"),
  listProducts: () => req<Product[]>("/api/products"),
  createProduct: (p: Omit<Product, "id">) =>
    req<Product>("/api/products", { method: "POST", body: JSON.stringify(p) }),
  updateProduct: (id: number, p: Partial<Product>) =>
    req<Product>(`/api/products/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteProduct: (id: number) => req<void>(`/api/products/${id}`, { method: "DELETE" }),

  listCustomers: () => req<Customer[]>("/api/customers"),

  listOrders: () => req<Order[]>("/api/orders"),
  getOrder: (id: number) => req<Order>(`/api/orders/${id}`),
  createOrder: (customer_id: number, items: { product_id: number; quantity: number }[]) =>
    req<Order>("/api/orders", { method: "POST", body: JSON.stringify({ customer_id, items }) }),
  updateOrderStatus: (id: number, status: string) =>
    req<Order>(`/api/orders/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  deleteOrder: (id: number) => req<void>(`/api/orders/${id}`, { method: "DELETE" }),
};
