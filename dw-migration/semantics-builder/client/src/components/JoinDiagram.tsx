import { useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { Join, MetricView, MetricViewIssue } from '../../../shared/metricView';

const W = 210;
const VIEW_W = 260;
const HEAD = 48;
const ROW = 22;
const GAP_X = 64;
const GAP_Y = 24;
const MAX_ROWS = 14;
const MONO_FONT = 'ui-monospace, SFMono-Regular, Menlo, monospace';

const short = (t: string) => t.split('.').pop() ?? t;
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}...` : s);
const startsWith = (path: (string | number)[], prefix: (string | number)[]) =>
  prefix.every((p, i) => path[i] === p) && path[prefix.length] !== 'joins';

interface TableNode {
  alias: string;
  table: string;
  on: string;
  parent: string | null;
  depth: number;
  columns: string[];
  warnings: string[];
  x: number;
  y: number;
  h: number;
}

interface Field {
  kind: 'measure' | 'dimension';
  name: string;
  aliases: string[];
}

/**
 * The aliases an expression reads. A ref is a dotted path such as `dim_orders.dim_customer.c_name`: the column is the
 * last part, and the alias is the part before it.
 */
function refs(expr: string, aliases: string[]) {
  const used = new Map<string, Set<string>>();
  for (const m of expr.matchAll(/`?[A-Za-z_]\w*`?(?:\s*\.\s*`?[A-Za-z_]\w*`?)+/g)) {
    const parts = m[0].split('.').map((p) => p.replace(/`/g, '').trim());
    const column = parts.at(-1)!;
    const alias = parts.at(-2)!;
    if (!aliases.includes(alias)) continue;
    used.set(alias, (used.get(alias) ?? new Set()).add(column));
  }
  return used;
}

function layout(view: MetricView, issues: MetricViewIssue[]) {
  const nodes: Omit<TableNode, 'x' | 'y' | 'h' | 'columns'>[] = [
    { alias: 'source', table: view.source, on: '', parent: null, depth: 0, warnings: [] },
  ];
  const walk = (joins: Join[] | undefined, path: (string | number)[], parent: string, depth: number) =>
    (joins ?? []).forEach((j, i) => {
      const here = [...path, 'joins', i];
      nodes.push({
        alias: j.name,
        table: j.source,
        on: j.on ?? `USING (${(j.using ?? []).join(', ')})`,
        parent,
        depth,
        warnings: issues.filter((x) => startsWith(x.path, here)).map((x) => x.message),
      });
      walk(j.joins, here, j.name, depth + 1);
    });
  walk(view.joins, [], 'source', 1);

  const aliases = nodes.map((n) => n.alias);
  const columns = new Map<string, Set<string>>(aliases.map((a) => [a, new Set()]));
  const fields: Field[] = [
    ...view.measures.map((m) => ({ kind: 'measure' as const, name: m.name, expr: m.expr })),
    ...view.dimensions.map((d) => ({ kind: 'dimension' as const, name: d.name, expr: d.expr })),
  ].map((f) => {
    const used = refs(f.expr, aliases);
    for (const [a, cols] of used) for (const c of cols) columns.get(a)!.add(c);
    // A field with no alias ref reads the source columns directly.
    return { kind: f.kind, name: f.name, aliases: used.size ? [...used.keys()] : ['source'] };
  });
  for (const n of nodes) {
    const on = n.on;
    if (!on) continue;
    for (const [a, cols] of refs(on, aliases)) for (const c of cols) columns.get(a)!.add(c);
  }

  const heightOf = (rows: number) => HEAD + Math.max(1, Math.min(rows, MAX_ROWS + 1)) * ROW + 8;
  const colY = new Map<number, number>();
  const placed: TableNode[] = nodes.map((n) => {
    const cols = [...(columns.get(n.alias) ?? [])].sort();
    const h = heightOf(cols.length);
    const y = colY.get(n.depth) ?? 0;
    colY.set(n.depth, y + h + GAP_Y);
    return { ...n, columns: cols, x: n.depth * (W + GAP_X), y, h };
  });
  const viewX = (Math.max(...placed.map((n) => n.depth)) + 1) * (W + GAP_X);
  const viewH = HEAD + Math.min(fields.length, MAX_ROWS * 2 + 1) * ROW + 8;
  const tablesBottom = Math.max(...[...colY.values()].map((y) => y - GAP_Y));
  // Lines to the view run on a bus below the tables, so they never cross a table.
  const busY = Math.max(tablesBottom, viewH) + 24;
  return { nodes: placed, fields, viewX, viewH, busY, width: viewX + VIEW_W + 2, height: busY + 8 };
}

/**
 * The model as lineage, like Catalog Explorer: the source table, the tables it joins, then the metric view with its
 * fields. Each table lists the columns the view uses. Select a table to see the fields that read it.
 */
export function JoinDiagram({ view, issues }: { view: MetricView; issues: MetricViewIssue[] }) {
  const { nodes, fields, viewX, viewH, busY, width, height } = layout(view, issues);
  const [selected, setSelected] = useState<string>();
  const byAlias = new Map(nodes.map((n) => [n.alias, n]));
  const lit = (f: Field) => !!selected && f.aliases.includes(selected);
  const shown = fields.slice(0, MAX_ROWS * 2);
  const toggle = (alias: string) => setSelected((s) => (s === alias ? undefined : alias));
  const onKey = (alias: string) => (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle(alias);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ overflow: 'auto', border: '1px solid var(--db-border-base)', borderRadius: 8, padding: 16 }}>
        <svg
          role="group"
          aria-label={`Lineage of the metric view: ${nodes.length} tables, ${fields.length} fields`}
          viewBox={`0 0 ${width} ${height}`}
          style={{ width: '100%', minWidth: Math.min(width, 900), height: 'auto' }}
        >
          <defs>
            <marker
              id="gsb-model-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="var(--db-text-subtle)" />
            </marker>
          </defs>
          {nodes
            .filter((n) => n.parent)
            .map((n) => {
              const p = byAlias.get(n.parent!)!;
              const x1 = p.x + W;
              const y1 = p.y + HEAD / 2;
              const x2 = n.x;
              const y2 = n.y + HEAD / 2;
              const mid = (x1 + x2) / 2;
              return (
                <path
                  key={`j-${n.alias}`}
                  d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`}
                  fill="none"
                  stroke={n.warnings.length ? 'var(--db-alert-border-warning)' : 'var(--db-text-subtle)'}
                  strokeWidth={1.5}
                  markerEnd="url(#gsb-model-arrow)"
                >
                  <title>
                    {n.parent} joins {n.alias} ON {n.on}
                  </title>
                </path>
              );
            })}
          {nodes
            .filter((n) => !n.parent || n.alias === selected)
            .map((n) => {
              const x1 = n.x + W / 2;
              const x2 = viewX + VIEW_W / 2;
              const on = selected === n.alias;
              return (
                <path
                  key={`v-${n.alias}`}
                  d={`M${x1},${n.y + n.h} V${busY} H${x2} V${viewH}`}
                  fill="none"
                  stroke={on ? 'var(--db-accent-text)' : 'var(--db-text-subtle)'}
                  strokeWidth={on ? 2 : 1.5}
                  markerEnd="url(#gsb-model-arrow)"
                >
                  <title>The metric view reads {n.parent ? n.alias : 'its source'}</title>
                </path>
              );
            })}
          {nodes.map((n) => {
            const on = selected === n.alias;
            const warn = n.warnings.length > 0;
            const rows = n.columns.slice(0, MAX_ROWS);
            return (
              <g
                key={n.alias}
                transform={`translate(${n.x},${n.y})`}
                role="button"
                tabIndex={0}
                aria-pressed={on}
                aria-label={`${n.alias}: ${n.table}. ${n.columns.length} columns used.${warn ? ` Warning: ${n.warnings.join(' ')}` : ''}`}
                onClick={() => toggle(n.alias)}
                onKeyDown={onKey(n.alias)}
                style={{ cursor: 'pointer' }}
              >
                <title>{n.table}</title>
                <rect
                  width={W}
                  height={n.h}
                  rx={8}
                  fill={warn ? 'var(--db-alert-surface-warning)' : 'var(--db-surface-base)'}
                  stroke={
                    on ? 'var(--db-accent-text)' : warn ? 'var(--db-alert-border-warning)' : 'var(--db-border-strong)'
                  }
                  strokeWidth={on ? 2 : 1}
                />
                <rect
                  width={4}
                  height={n.h}
                  rx={2}
                  fill={n.parent ? 'var(--db-border-strong)' : 'var(--db-accent-text)'}
                />
                <rect x={14} y={12} width={14} height={14} rx={2} fill="none" stroke="var(--db-text-subtle)" />
                <line x1={14} y1={17} x2={28} y2={17} stroke="var(--db-text-subtle)" />
                <line x1={20} y1={12} x2={20} y2={26} stroke="var(--db-text-subtle)" />
                <text x={36} y={24} fontSize={13} fontWeight={600} fill="var(--db-text-base)">
                  {clip(short(n.table), 20)}
                </text>
                <text x={14} y={40} fontSize={11} fill="var(--db-text-subtle)">
                  {n.parent ? `as ${clip(n.alias, 18)}` : 'source (fact)'}
                  {warn ? ' - warning' : ''}
                </text>
                <line x1={0} y1={HEAD} x2={W} y2={HEAD} stroke="var(--db-border-base)" />
                {rows.length ? (
                  rows.map((c, i) => (
                    <text
                      key={c}
                      x={14}
                      y={HEAD + i * ROW + ROW / 2 + 8}
                      fontSize={12}
                      fill="var(--db-text-base)"
                      fontFamily={MONO_FONT}
                    >
                      {clip(c, 25)}
                    </text>
                  ))
                ) : (
                  <text x={14} y={HEAD + ROW / 2 + 8} fontSize={12} fill="var(--db-text-subtle)">
                    No column named
                  </text>
                )}
                {n.columns.length > MAX_ROWS && (
                  <text x={14} y={HEAD + MAX_ROWS * ROW + ROW / 2 + 8} fontSize={12} fill="var(--db-text-subtle)">
                    +{n.columns.length - MAX_ROWS} more
                  </text>
                )}
              </g>
            );
          })}
          <g transform={`translate(${viewX},0)`}>
            <rect
              width={VIEW_W}
              height={viewH}
              rx={8}
              fill="var(--db-accent-surface-subtle)"
              stroke="var(--db-accent-text)"
            />
            <text x={14} y={24} fontSize={13} fontWeight={600} fill="var(--db-text-base)">
              Metric view
            </text>
            <text x={14} y={40} fontSize={11} fill="var(--db-text-subtle)">
              {view.measures.length} measures, {view.dimensions.length} dimensions
            </text>
            <line x1={0} y1={HEAD} x2={VIEW_W} y2={HEAD} stroke="var(--db-border-base)" />
            {shown.map((f, i) => (
              <text
                key={`${f.kind}:${f.name}`}
                x={14}
                y={HEAD + i * ROW + ROW / 2 + 8}
                fontSize={12}
                fontWeight={lit(f) ? 700 : undefined}
                fill={lit(f) ? 'var(--db-accent-text)' : selected ? 'var(--db-text-subtle)' : 'var(--db-text-base)'}
              >
                {f.kind === 'measure' ? 'Σ ' : '# '}
                {clip(f.name, 30)}
              </text>
            ))}
            {fields.length > shown.length && (
              <text x={14} y={HEAD + shown.length * ROW + ROW / 2 + 8} fontSize={12} fill="var(--db-text-subtle)">
                +{fields.length - shown.length} more
              </text>
            )}
          </g>
        </svg>
      </div>
      <ul style={{ margin: 0, paddingLeft: 20 }}>
        <li>
          <code>source</code>: {view.source}
        </li>
        {nodes
          .filter((n) => n.parent)
          .map((n) => (
            <li key={n.alias}>
              <code>{n.alias}</code>: {n.table} joined to <code>{n.parent}</code> on <code>{n.on}</code>
              {n.warnings.map((w) => (
                <div key={w} style={{ color: 'var(--db-alert-text-warning)' }}>
                  Warning: {w}
                </div>
              ))}
            </li>
          ))}
        {selected && (
          <li>
            Fields that read <code>{selected}</code>:{' '}
            {fields
              .filter(lit)
              .map((f) => f.name)
              .join(', ') || 'none'}
          </li>
        )}
      </ul>
    </div>
  );
}
