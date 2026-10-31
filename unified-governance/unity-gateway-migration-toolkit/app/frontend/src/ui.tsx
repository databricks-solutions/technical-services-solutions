import { Component, ReactNode, useEffect, useMemo, useState } from "react";
import { JobState, TERMINAL_LIFE_CYCLES } from "./api";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: any) {
    return { error: String(e?.message || e) };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="alert bad" role="alert">
          Something on this page failed to render: {this.state.error}{" "}
          <button className="ghost small" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export function Card({ title, children, actions, note }: { title?: string; children: ReactNode; actions?: ReactNode; note?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          <h3>{title}</h3>
          <div>{actions}</div>
        </header>
      )}
      {note && <p className="muted small">{note}</p>}
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className={`kpi ${tone || ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

const TONE: Record<string, string> = {
  READY: "good", SUCCEEDED: "good", ok: "good", created: "good", granted: "good", deleted: "good", exists: "neutral",
  READY_WITH_WARNINGS: "warn", INCOMPLETE: "warn", NEEDS_ATTENTION: "warn", manual: "warn", would_create: "info",
  would_grant: "info", would_delete: "info", RUNNING: "info", PENDING: "info", QUEUED: "info", creating: "info",
  BLOCKED: "bad", FAILED: "bad", error: "bad", mismatch: "bad", kept: "neutral", skipped: "neutral",
};

export function Badge({ value, tone }: { value: any; tone?: string }) {
  const t = tone || TONE[String(value)] || "neutral";
  return <span className={`badge ${t}`}>{String(value ?? "-").replace(/_/g, " ")}</span>;
}

export function Loading({ text = "Loading" }: { text?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" /> {text}...
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="alert bad" role="alert">{error}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state muted">{children}</div>;
}

export function JobLine({ state, label }: { state: JobState | null; label: string }) {
  if (!state) return <div className="muted small" role="status">{label}: starting...</div>;
  if (state.error) return <div className="alert bad small" role="alert">{label}: {state.error}</div>;
  const running = !TERMINAL_LIFE_CYCLES.includes(state.life_cycle || "");
  return (
    <div className="jobline" role="status" aria-live="polite">
      {running && <div className="spinner" />}
      <span>{label}:</span> <Badge value={state.result || state.life_cycle} />
      {state.url && (
        <a href={state.url} target="_blank" rel="noreferrer">
          job run
        </a>
      )}
      {state.message && !running && state.result !== "SUCCESS" && <span className="muted small">{state.message}</span>}
    </div>
  );
}

export type Column<T> = { key: string; label: string; render?: (row: T) => ReactNode; num?: boolean; width?: string };

export function Table<T extends Record<string, any>>({ rows, columns, search, pageSize = 25, empty, label }: {
  rows: T[]; columns: Column<T>[]; search?: boolean; pageSize?: number; empty?: ReactNode; label?: string;
}) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [page, setPage] = useState(0);
  const filtered = useMemo(() => {
    let r = rows;
    if (q) {
      const needle = q.toLowerCase();
      r = r.filter((row) => columns.some((c) => String(row[c.key] ?? "").toLowerCase().includes(needle)));
    }
    if (sort) {
      const col = columns.find((c) => c.key === sort.key);
      r = [...r].sort((a, b) => {
        const x = a[sort.key], y = b[sort.key];
        const nx = Number(x), ny = Number(y);
        const cmp = col?.num && !Number.isNaN(nx) && !Number.isNaN(ny) ? nx - ny : String(x ?? "").localeCompare(String(y ?? ""));
        return cmp * sort.dir;
      });
    }
    return r;
  }, [rows, q, sort, columns]);
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  useEffect(() => { if (page > pages - 1) setPage(pages - 1); }, [page, pages]);
  const p = Math.min(page, pages - 1);
  const view = filtered.slice(p * pageSize, p * pageSize + pageSize);
  return (
    <div>
      {search && (
        <input className="search" placeholder="Filter..." aria-label={`Filter ${label || "rows"}`} value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
      )}
      {filtered.length === 0 ? (
        <Empty>{empty || "Nothing to show."}</Empty>
      ) : (
        <div className="table-wrap">
          <table aria-label={label}>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key} style={{ width: c.width }} className={c.num ? "num" : ""} tabIndex={c.label ? 0 : -1}
                      aria-sort={sort?.key === c.key ? (sort.dir === -1 ? "descending" : "ascending") : "none"}
                      onClick={() => setSort((s) => ({ key: c.key, dir: s?.key === c.key && s.dir === -1 ? 1 : -1 }))}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSort((s) => ({ key: c.key, dir: s?.key === c.key && s.dir === -1 ? 1 : -1 })); } }}>
                    {c.label}{sort?.key === c.key ? (sort.dir === -1 ? " ▾" : " ▴") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.map((row, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(row) : String(row[c.key] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <div className="pager">
          <button disabled={p === 0} onClick={() => setPage(p - 1)}>Prev</button>
          <span className="muted small">Page {p + 1} of {pages} ({filtered.length} rows)</span>
          <button disabled={p >= pages - 1} onClick={() => setPage(p + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}

/** Two-series line chart (legacy vs Unity Gateway), drawn as SVG. */
export function TrendChart({ points, series }: {
  points: Record<string, any>[]; series: { key: string; label: string; cls: string }[];
}) {
  if (points.length === 0) return <Empty>No snapshots yet.</Empty>;
  const W = 640, H = 200, P = { l: 56, r: 12, t: 12, b: 28 };
  const max = Math.max(1, ...points.flatMap((p) => series.map((s) => Number(p[s.key]) || 0)));
  const x = (i: number) => P.l + (points.length === 1 ? (W - P.l - P.r) / 2 : (i * (W - P.l - P.r)) / (points.length - 1));
  const y = (v: number) => H - P.b - (v / max) * (H - P.t - P.b);
  const ticks = [0, 0.5, 1].map((f) => max * f);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Traffic trend">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={P.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{fmtShort(t)}</text>
          </g>
        ))}
        {series.map((s) => (
          <g key={s.key}>
            <polyline className={`line ${s.cls}`} fill="none"
                      points={points.map((p, i) => `${x(i)},${y(Number(p[s.key]) || 0)}`).join(" ")} />
            {points.map((p, i) => <circle key={i} cx={x(i)} cy={y(Number(p[s.key]) || 0)} r={3} className={`dot ${s.cls}`} />)}
          </g>
        ))}
        {points.map((p, i) => (i === 0 || i === points.length - 1) && (
          <text key={i} x={x(i)} y={H - 8} textAnchor={i === 0 && points.length > 1 ? "start" : "end"} className="axis">
            {String(p.snapshot_time).slice(0, 16)}
          </text>
        ))}
      </svg>
      <div className="legend">
        {series.map((s) => <span key={s.key}><i className={`swatch ${s.cls}`} />{s.label}</span>)}
      </div>
    </div>
  );
}

function fmtShort(v: number) {
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(0) + "K";
  return String(Math.round(v));
}

export function Bars({ rows, labelKey, valueKey }: { rows: Record<string, any>[]; labelKey: string; valueKey: string }) {
  if (rows.length === 0) return <Empty>No workspaces in the latest snapshot.</Empty>;
  const max = Math.max(1, ...rows.map((r) => Number(r[valueKey]) || 0));
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="bar-row" key={r[labelKey]}>
          <span className="bar-label">{r[labelKey]}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(100 * (Number(r[valueKey]) || 0)) / max}%` }} /></span>
          <span className="bar-value">{r[valueKey]}</span>
        </div>
      ))}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState<string | null>(null);
  return (
    <button className="ghost small" onClick={() => {
      navigator.clipboard.writeText(text).then(() => setDone("Copied"), () => setDone("Copy failed")).finally(() => setTimeout(() => setDone(null), 1500));
    }}>
      {done || label}
    </button>
  );
}

export function Confirm({ word, title, body, onConfirm, onCancel, busy }: {
  word: string; title: string; body: ReactNode; onConfirm: () => void; onCancel: () => void; busy?: boolean;
}) {
  const [typed, setTyped] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);
  return (
    <div className="modal-back">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <h3 id="confirm-title">{title}</h3>
        <div>{body}</div>
        <label className="small" htmlFor="confirm-word">Type <b>{word}</b> to continue.</label>
        <input id="confirm-word" autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} />
        <div className="row end">
          <button className="ghost" onClick={onCancel}>Cancel</button>
          <button className="danger" disabled={typed !== word || busy} onClick={onConfirm}>{busy ? "Starting..." : title}</button>
        </div>
      </div>
    </div>
  );
}
