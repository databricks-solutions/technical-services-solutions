// Small set of branded UI primitives (no external component lib needed).
import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-black/5 bg-white shadow-sm ${className}`}>{children}</div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed";
  const variants = {
    primary: "bg-brand-red text-white hover:bg-[#e02d1a]",
    ghost: "bg-transparent text-brand-navy hover:bg-black/5",
    danger: "bg-transparent text-brand-red hover:bg-brand-red/10",
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${variants[variant]} ${className}`}>
      {children}
    </button>
  );
}

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800",
  paid: "bg-blue-100 text-blue-800",
  shipped: "bg-indigo-100 text-indigo-800",
  delivered: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-rose-100 text-rose-800",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${
        STATUS_STYLES[status] || "bg-gray-100 text-gray-700"
      }`}
    >
      {status}
    </span>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-brand-red focus:ring-2 focus:ring-brand-red/20 ${
        props.className || ""
      }`}
    />
  );
}

export function money(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}
