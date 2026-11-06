import { useMemo, useState } from 'react';
import type { Join, MetricView, MetricViewIssue } from '../../../shared/metricView';
import { LineageCanvas } from './LineageCanvas';
import type { CanvasEdge, CanvasNode } from './LineageCanvas';

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
  warnings: string[];
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

function model(view: MetricView, issues: MetricViewIssue[]) {
  const tables: TableNode[] = [{ alias: 'source', table: view.source, on: '', parent: null, depth: 0, warnings: [] }];
  const walk = (joins: Join[] | undefined, path: (string | number)[], parent: string, depth: number) =>
    (joins ?? []).forEach((j, i) => {
      const here = [...path, 'joins', i];
      tables.push({
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

  const aliases = tables.map((t) => t.alias);
  const columns = new Map<string, Set<string>>(aliases.map((a) => [a, new Set()]));
  const fields = [
    ...view.measures.map((m) => ({ kind: 'measure' as const, name: m.name, expr: m.expr })),
    ...view.dimensions.map((d) => ({ kind: 'dimension' as const, name: d.name, expr: d.expr })),
  ].map((f) => {
    const used = refs(f.expr, aliases);
    for (const [a, cols] of used) for (const c of cols) columns.get(a)!.add(c);
    // A field with no alias ref reads the source columns directly.
    return { kind: f.kind, name: f.name, aliases: used.size ? [...used.keys()] : ['source'] };
  });
  for (const t of tables)
    if (t.on) for (const [a, cols] of refs(t.on, aliases)) for (const c of cols) columns.get(a)!.add(c);
  return { tables, fields, columns };
}

/**
 * The model as lineage on a canvas, like Catalog Explorer: the source table, the tables it joins, then the metric
 * view with its fields. Open a table to see the columns the view uses. Select a table to light up its fields.
 */
export function JoinDiagram({ view, issues }: { view: MetricView; issues: MetricViewIssue[] }) {
  const { tables, fields, columns } = useMemo(() => model(view, issues), [view, issues]);
  const [selected, setSelected] = useState<string>();
  const rowAt = new Map<number, number>();
  const nodes: CanvasNode[] = tables.map((t) => {
    const row = rowAt.get(t.depth) ?? 0;
    rowAt.set(t.depth, row + 1);
    return {
      id: t.alias,
      title: short(t.table),
      subtitle: t.parent ? `as ${t.alias}` : 'source (fact)',
      kind: t.parent ? 'table' : 'fact',
      columns: [...(columns.get(t.alias) ?? [])].sort().map((name) => ({ name })),
      warning: t.warnings.join(' ') || undefined,
      col: t.depth,
      row,
    };
  });
  const viewCol = Math.max(...tables.map((t) => t.depth)) + 1;
  nodes.push({
    id: '__view',
    title: 'Metric view',
    subtitle: `${view.measures.length} measures, ${view.dimensions.length} dimensions`,
    kind: 'view',
    columns: fields.map((f) => ({
      name: f.name,
      type: f.kind,
      highlight: !!selected && f.aliases.includes(selected),
    })),
    col: viewCol,
    row: 0,
  });
  const edges: CanvasEdge[] = [
    ...tables
      .filter((t) => t.parent)
      .map((t) => ({
        id: `j-${t.alias}`,
        source: t.parent!,
        target: t.alias,
        label: clip(t.on, 30),
        warn: t.warnings.length > 0,
      })),
    ...tables
      .filter((t) => !t.parent || t.alias === selected)
      .map((t) => ({
        id: `v-${t.alias}`,
        source: t.alias,
        target: '__view',
        dashed: !!t.parent,
        highlight: t.alias === selected,
      })),
  ];
  const lit = fields.filter((f) => selected && f.aliases.includes(selected)).map((f) => f.name);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <LineageCanvas
        label={`Lineage of the metric view: ${tables.length} tables, ${fields.length} fields`}
        nodes={nodes}
        edges={edges}
        selected={selected}
        onSelect={(id) => setSelected((s) => (s === id || id === '__view' ? undefined : id))}
      />
      {selected && (
        <div role="status" style={{ fontSize: 13 }}>
          Fields that read <code>{selected}</code>: {lit.join(', ') || 'none'}
        </div>
      )}
      <details>
        <summary>Joins as text</summary>
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          <li>
            <code>source</code>: {view.source}
          </li>
          {tables
            .filter((t) => t.parent)
            .map((t) => (
              <li key={t.alias}>
                <code>{t.alias}</code>: {t.table} joined to <code>{t.parent}</code> on <code>{t.on}</code>
                {t.warnings.map((w) => (
                  <div key={w} style={{ color: 'var(--db-alert-text-warning)' }}>
                    Warning: {w}
                  </div>
                ))}
              </li>
            ))}
        </ul>
      </details>
    </div>
  );
}
