import { Component, KeyboardEvent, ReactNode, RefObject, useEffect, useId, useMemo, useRef, useState } from "react";
import { JobState, TERMINAL_LIFE_CYCLES, fmt } from "./api";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: any) {
    return { error: String(e?.message || e) };
  }
  render() {
    if (this.state.error) {
      return <ErrorState error={`This page failed to display: ${this.state.error}`} onRetry={() => this.setState({ error: null })} />;
    }
    return this.props.children;
  }
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="stack-sm">
        <h2>{title}</h2>
        {description && <p className="muted small">{description}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Card({ title, children, actions, note, id, headingRef }: {
  title?: ReactNode; children: ReactNode; actions?: ReactNode; note?: ReactNode; id?: string; headingRef?: RefObject<HTMLHeadingElement>;
}) {
  const generated = useId();
  const titleId = id || generated;
  return (
    <section className="card" aria-labelledby={title ? titleId : undefined}>
      {(title || actions) && (
        <header className="card-head">
          <div className="stack-sm">
            {title && <h3 id={titleId} ref={headingRef} tabIndex={headingRef ? -1 : undefined} className={headingRef ? "focus-target" : undefined}>{title}</h3>}
            {note && <p className="muted small">{note}</p>}
          </div>
          {actions && <div className="actions">{actions}</div>}
        </header>
      )}
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
  READY: "good", SUCCEEDED: "good", SUCCESS: "good", ok: "good", created: "good", granted: "good", deleted: "good", exists: "neutral",
  READY_WITH_WARNINGS: "warn", INCOMPLETE: "warn", NEEDS_ATTENTION: "warn", manual: "warn", would_create: "info",
  would_grant: "info", would_delete: "info", RUNNING: "info", PENDING: "info", QUEUED: "info", creating: "info",
  BLOCKED: "bad", FAILED: "bad", error: "bad", mismatch: "bad", CANCELED: "bad", TIMEDOUT: "bad", kept: "neutral", skipped: "neutral",
};

export function Badge({ value, tone }: { value: any; tone?: string }) {
  const t = tone || TONE[String(value)] || "neutral";
  return <span className={`badge ${t}`}>{String(value ?? "-").replace(/_/g, " ")}</span>;
}

/* ---------- Live region: one polite region for job progress and outcomes ---------- */

/** Mount once (App). announce() writes to it so screen readers hear job progress and completion. */
export function LiveRegion() {
  return <div id="app-live" className="sr-only" aria-live="polite" aria-atomic="true" />;
}

export function announce(message: string) {
  const el = document.getElementById("app-live");
  if (!el) return;
  el.textContent = "";
  window.setTimeout(() => { el.textContent = message; }, 50);
}

/* ---------- States: loading, empty, error, notices ---------- */

/** Visual placeholder only (hidden from screen readers); one "Loading" text announces the wait. */
export function Skeleton({ lines = 3, block = false, label = "Loading" }: { lines?: number; block?: boolean; label?: string }) {
  return (
    <div className="stack-sm">
      <span className="sr-only">{label}</span>
      <div className="stack-sm" aria-hidden="true">
        {block ? <span className="skeleton block" /> : Array.from({ length: lines }, (_, i) => (
          <span key={i} className="skeleton line" style={{ width: `${[92, 78, 85, 64, 70][i % 5]}%` }} />
        ))}
      </div>
    </div>
  );
}

export function SkeletonTable({ rows = 6, label = "Loading table" }: { rows?: number; label?: string }) {
  return (
    <div className="stack-sm">
      <span className="sr-only">{label}</span>
      <div className="skeleton-table" aria-hidden="true">
        <span className="skeleton line" style={{ height: 30 }} />
        {Array.from({ length: rows }, (_, i) => <span key={i} className="skeleton line" />)}
      </div>
    </div>
  );
}

export function SkeletonKpis() {
  return (
    <div className="kpis" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <div className="kpi" key={i}><span className="skeleton line" style={{ width: "50%" }} /><span className="skeleton line" style={{ width: "70%", height: 26, marginTop: 8 }} /></div>
      ))}
    </div>
  );
}

export function SkeletonCard({ title, block = false }: { title?: string; block?: boolean }) {
  return (
    <Card title={title}>
      {block ? <Skeleton block label={`Loading ${title || ""}`} /> : <SkeletonTable label={`Loading ${title || ""}`} />}
    </Card>
  );
}

export function Empty({ title, children, action }: { title?: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      {title && <div className="empty-title">{title}</div>}
      {children && <div className="small">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Couldn't load this" }: { error: string; onRetry?: () => void; title?: string }) {
  return (
    <Notice tone="error" title={title} action={onRetry && <button className="btn secondary sm" onClick={onRetry}>Try again</button>}>
      {friendly(error)}
    </Notice>
  );
}

/** Short inline error for a failed action (keeps the HTTP status out of the user's way). */
export function ErrorBox({ error }: { error: string }) {
  return <Notice tone="error">{friendly(error)}</Notice>;
}

function friendly(error: string) {
  const m = /^(\d{3}): ([\s\S]*)$/.exec(error);
  if (!m) return error;
  const [, code, text] = m;
  if (code === "401") return "Your session has no verified user. Ask the person who installed the app to enable user authorization, then reload.";
  if (code === "403") return text || "You don't have permission for this.";
  if (code === "504") return "The SQL warehouse took too long to answer (it may be starting). Try again in a minute.";
  return text || `Request failed (${code}).`;
}

export function Notice({ tone, title, children, action, onClose }: {
  tone: "success" | "error" | "warning" | "info"; title?: ReactNode; children?: ReactNode; action?: ReactNode; onClose?: () => void;
}) {
  const icon = { success: "✓", error: "!", warning: "!", info: "i" }[tone];
  return (
    <div className={`notice ${tone}`} role={tone === "error" ? "alert" : "status"} aria-live={tone === "error" ? "assertive" : "polite"}>
      <span className="notice-icon" aria-hidden="true">{icon}</span>
      <div className="notice-body">
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
        {action && <div className="row">{action}</div>}
      </div>
      {onClose && <button className="btn link sm" onClick={onClose} aria-label="Dismiss">Dismiss</button>}
    </div>
  );
}

/** Visible reason why an action is unavailable (linked to the button with aria-describedby). */
export function Reason({ id, children }: { id: string; children: ReactNode }) {
  return <p id={id} className="reason small">{children}</p>;
}

/** Time since a job or run started, ticking once a second (visible, not announced). */
export function Elapsed({ since }: { since: number | string | null | undefined }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (since === null || since === undefined || since === "") return null;
  const start = typeof since === "number" ? since : Date.parse(String(since).includes("T") ? String(since) : `${String(since).replace(" ", "T")}Z`);
  if (Number.isNaN(start)) return null;
  const s = Math.max(0, Math.floor((now - start) / 1000));
  const text = s >= 3600 ? `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`
    : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return <span className="muted small">running for {text}</span>;
}

/** Status of a started job, then the outcome (success or failure) once it ends. Changes are announced once. */
export function JobLine({ state, label, done }: { state: JobState | null; label: string; done?: ReactNode }) {
  const life = state?.life_cycle || "";
  const finished = !!state && (!!state.error || TERMINAL_LIFE_CYCLES.includes(life));
  const sentence = !state ? "" : state.error ? `${label}: status unknown`
    : !finished ? `${label}: ${life.toLowerCase()}`
    : state.result === "SUCCESS" ? `${label} finished` : `${label} ${String(state.result || life).toLowerCase()}`;
  const baseline = useRef<string | null>(null);
  useEffect(() => {
    if (baseline.current === null) { baseline.current = sentence; return; }
    if (sentence && sentence !== baseline.current) announce(sentence);
    baseline.current = sentence;
  }, [sentence]);
  if (!state) return <div className="jobline"><div className="spinner" aria-hidden="true" />{label}: starting</div>;
  if (state.error) return <Notice tone="error" title={`${label}: status unknown`}>{state.error}</Notice>;
  const link = state.url && <a href={state.url} target="_blank" rel="noreferrer">View job run</a>;
  if (!finished) {
    return (
      <div className="jobline">
        <div className="spinner" aria-hidden="true" /><span>{label}: {life.toLowerCase()}</span><Elapsed since={state.start_time} />{link}
      </div>
    );
  }
  if (state.result === "SUCCESS") return <Notice tone="success" title={`${label} finished`} action={link}>{done}</Notice>;
  return <Notice tone="error" title={`${label} ${String(state.result || state.life_cycle).toLowerCase()}`} action={link}>{state.message}</Notice>;
}

/* ---------- Tabs (arrow keys move between tabs; each tab controls the panel `${panelId}-panel`) ---------- */

/** Attributes for the tabpanel that shows the selected tab. */
export function tabPanel(panelId: string, value: string) {
  return { id: `${panelId}-panel`, role: "tabpanel", tabIndex: 0, "aria-labelledby": `${panelId}-tab-${value}` } as const;
}

export function Tabs({ tabs, value, onChange, className = "subtabs", label, panelId }: {
  tabs: readonly (readonly [string, ReactNode])[]; value: string; onChange: (k: string) => void; className?: string; label: string; panelId: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const j = (next + tabs.length) % tabs.length;
    onChange(tabs[j][0]);
    refs.current[j]?.focus();
  };
  return (
    <div className={className} role="tablist" aria-label={label}>
      {tabs.map(([k, l], i) => (
        <button key={k} ref={(el) => (refs.current[i] = el)} id={`${panelId}-tab-${k}`} aria-controls={`${panelId}-panel`}
                role="tab" aria-selected={value === k} tabIndex={value === k ? 0 : -1}
                onClick={() => onChange(k)} onKeyDown={(e) => onKey(e, i)}>{l}</button>
      ))}
    </div>
  );
}

/* ---------- Table ---------- */

export type Column<T> = { key: string; label: string; render?: (row: T) => ReactNode; num?: boolean; width?: string; sortable?: boolean };

export function Table<T extends Record<string, any>>({ rows, columns, search, pageSize = 25, empty, label, tools, rowCurrent }: {
  rows: T[]; columns: Column<T>[]; search?: boolean; pageSize?: number; empty?: ReactNode; label: string; tools?: ReactNode;
  /** Marks the row that is open elsewhere on the page (aria-current). */
  rowCurrent?: (row: T) => boolean;
}) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [page, setPage] = useState(0);
  const searchId = useId();
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
  const toggle = (key: string) => setSort((s) => ({ key, dir: s?.key === key && s.dir === -1 ? 1 : -1 }));
  return (
    <div>
      {(search || tools) && (
        <div className="table-tools">
          {search ? (
            <div>
              <label htmlFor={searchId} className="sr-only">Filter {label}</label>
              <input id={searchId} type="search" className="search" placeholder="Filter" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
            </div>
          ) : <span />}
          {tools && <div className="row">{tools}</div>}
        </div>
      )}
      {rows.length === 0 ? (
        typeof empty === "string" || !empty ? <Empty title={empty || "Nothing to show"} /> : empty
      ) : filtered.length === 0 ? (
        <Empty title="No matches" action={<button className="btn secondary sm" onClick={() => setQ("")}>Clear filter</button>}>Nothing matches “{q}”.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">{label}</caption>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key} scope="col" style={{ width: c.width }} className={c.num ? "num" : ""}
                      aria-sort={sort?.key === c.key ? (sort.dir === -1 ? "descending" : "ascending") : undefined}>
                    {c.label && c.sortable !== false ? (
                      <button className="sort" onClick={() => toggle(c.key)}>
                        {c.label}<span aria-hidden="true">{sort?.key === c.key ? (sort.dir === -1 ? "▾" : "▴") : ""}</span>
                      </button>
                    ) : c.label ? c.label : <span className="sr-only">Actions</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.map((row, i) => {
                const current = rowCurrent?.(row) ?? false;
                return (
                  <tr key={i} className={current ? "current" : undefined} aria-current={current ? "true" : undefined}>
                    {columns.map((c) => (
                      <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(row) : String(row[c.key] ?? "")}</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <Pager page={p} pages={pages} total={filtered.length} onPage={setPage} />
      )}
    </div>
  );
}

export function Pager({ page, pages, total, onPage, busy }: { page: number; pages: number; total: number; onPage: (p: number) => void; busy?: boolean }) {
  return (
    <nav className="pager" aria-label="Pages">
      <button className="btn secondary sm" disabled={page === 0 || busy} onClick={() => onPage(page - 1)}>Previous</button>
      <span className="small muted" aria-live="polite">Page {page + 1} of {pages} · {fmt(total)} rows</span>
      <button className="btn secondary sm" disabled={page >= pages - 1 || busy} onClick={() => onPage(page + 1)}>Next</button>
    </nav>
  );
}

/* ---------- Charts ---------- */

type Series = { key: string; label: string; cls: "legacy" | "ug" | "single" };

/** Line chart over snapshots, drawn as SVG. Each point has a tooltip; `summary` is the accessible name and
 *  `describedBy` can point at a data table elsewhere on the page. Scrolls sideways on narrow screens so labels stay readable. */
export function TrendChart({ points, series, label, valueFmt = fmtShort, id, describedBy }: {
  points: Record<string, any>[]; series: Series[]; label: string; valueFmt?: (v: number) => string; id?: string; describedBy?: string;
}) {
  if (points.length === 0) return <Empty title="No snapshots yet" />;
  const W = 640, H = 210, P = { l: 52, r: 16, t: 12, b: 30 };
  const max = Math.max(1, ...points.flatMap((p) => series.map((s) => Number(p[s.key]) || 0)));
  const x = (i: number) => P.l + (points.length === 1 ? (W - P.l - P.r) / 2 : (i * (W - P.l - P.r)) / (points.length - 1));
  const y = (v: number) => H - P.b - (v / max) * (H - P.t - P.b);
  const ticks = [0, 0.5, 1].map((f) => max * f);
  const last = points[points.length - 1];
  const summary = `${label}. ${points.length} snapshots. Latest (${String(last.snapshot_time).slice(0, 10)}): ` +
    series.map((s) => `${s.label} ${valueFmt(Number(last[s.key]) || 0)}`).join(", ") + ".";
  return (
    <figure className="stack-sm" style={{ margin: 0 }}>
      <div className="chart-scroll">
        <svg id={id} viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={summary} aria-describedby={describedBy}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className="grid" />
              <text x={P.l - 8} y={y(t) + 4} textAnchor="end" className="axis">{valueFmt(t)}</text>
            </g>
          ))}
          {series.map((s) => (
            <g key={s.key}>
              <polyline className={`line ${s.cls}`} points={points.map((p, i) => `${x(i)},${y(Number(p[s.key]) || 0)}`).join(" ")} />
              {points.map((p, i) => (
                <circle key={i} cx={x(i)} cy={y(Number(p[s.key]) || 0)} r={3.5} className={`dot ${s.cls}`}>
                  <title>{`${String(p.snapshot_time).slice(0, 16)} · ${s.label}: ${valueFmt(Number(p[s.key]) || 0)}`}</title>
                </circle>
              ))}
            </g>
          ))}
          {points.map((p, i) => (i === 0 || i === points.length - 1) && (
            <text key={i} x={x(i)} y={H - 10} textAnchor={points.length === 1 ? "middle" : i === 0 ? "start" : "end"} className="axis">
              {String(p.snapshot_time).slice(0, 10)}
            </text>
          ))}
        </svg>
      </div>
      {series.length > 1 && (
        <figcaption className="legend">
          {series.map((s) => <span key={s.key}><i className={`swatch ${s.cls}`} aria-hidden="true" />{s.label}</span>)}
        </figcaption>
      )}
    </figure>
  );
}

export function fmtShort(v: number) {
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(0) + "K";
  return String(Math.round(v));
}

export function Bars({ rows, labelKey, valueKey, label }: { rows: Record<string, any>[]; labelKey: string; valueKey: string; label: string }) {
  if (rows.length === 0) return <Empty title="No workspaces in the latest snapshot" />;
  const max = Math.max(1, ...rows.map((r) => Number(r[valueKey]) || 0));
  return (
    <ul className="bars" aria-label={label}>
      {rows.map((r) => (
        <li className="bar-row" key={r[labelKey]}>
          <span>{r[labelKey]}</span>
          <span className="bar-track" aria-hidden="true"><span className="bar-fill" style={{ width: `${(100 * (Number(r[valueKey]) || 0)) / max}%` }} /></span>
          <span className="bar-value">{fmt(r[valueKey])}</span>
        </li>
      ))}
    </ul>
  );
}

/* ---------- Actions ---------- */

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState<string | null>(null);
  return (
    <button className="btn secondary sm" aria-live="polite" onClick={() => {
      navigator.clipboard.writeText(text).then(() => setDone("Copied"), () => setDone("Copy failed")).finally(() => setTimeout(() => setDone(null), 1500));
    }}>
      {done || label}
    </button>
  );
}

/** Download menu: each item is a plain link to an export endpoint (the browser downloads the file). */
export function ExportMenu({ items, label = "Export" }: { items: { href: string; label: string; hint?: string }[]; label?: string }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) ref.current.open = false; };
    const esc = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape" && ref.current?.open) { ref.current.open = false; (ref.current.querySelector("summary") as HTMLElement)?.focus(); } };
    document.addEventListener("click", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("click", close); document.removeEventListener("keydown", esc); };
  }, []);
  return (
    <details className="menu" ref={ref}>
      <summary className="btn secondary sm">{label}<span aria-hidden="true">▾</span></summary>
      <div className="menu-list">
        {items.map((i) => (
          <a key={i.href} href={i.href} download onClick={() => { if (ref.current) ref.current.open = false; }}>
            {i.label}{i.hint && <span className="muted small">{i.hint}</span>}
          </a>
        ))}
        <p className="menu-note small muted">Exports are limited to 200,000 rows.</p>
      </div>
    </details>
  );
}

export function Confirm({ word, title, body, onConfirm, onCancel, busy }: {
  word: string; title: string; body: ReactNode; onConfirm: () => void; onCancel: () => void; busy?: boolean;
}) {
  const [typed, setTyped] = useState("");
  const dialog = useRef<HTMLDivElement>(null);
  const [opener] = useState<Element | null>(() => document.activeElement);
  // Keep the latest onCancel in a ref so the key handler isn't re-bound (and focus disturbed) on every parent render.
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && !busy) cancel.current();
      if (e.key === "Tab" && dialog.current) { // keep focus inside the dialog
        const f = dialog.current.querySelectorAll<HTMLElement>("input, button:not(:disabled)");
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy]);
  // Give focus back to the control that opened the dialog, once, when it closes.
  useEffect(() => () => { (opener as HTMLElement | null)?.focus?.(); }, [opener]);
  const ok = typed === word && !busy;
  return (
    <div className="modal-back">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title" ref={dialog}>
        <h3 id="confirm-title">{title}</h3>
        <div className="stack-sm">{body}</div>
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); if (ok) onConfirm(); }}>
          <label className="field" htmlFor="confirm-word">Type {word} to confirm</label>
          <input id="confirm-word" autoFocus autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
          <div className="row">
            <button type="button" className="btn secondary" onClick={onCancel} disabled={busy}>Cancel</button>
            <button type="submit" className="btn danger" disabled={!ok}>{busy ? "Starting…" : title}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
