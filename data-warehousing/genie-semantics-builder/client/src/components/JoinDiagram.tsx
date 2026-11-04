import type { Join, MetricView, MetricViewIssue } from '../../../shared/metricView';

interface Node {
  path: (string | number)[];
  alias: string;
  table: string;
  on: string;
  depth: number;
  row: number;
  parentRow: number;
  warnings: string[];
}

const W = 300;
const H = 56;
const INDENT = 44;
const ROW = H + 20;

const startsWith = (path: (string | number)[], prefix: (string | number)[]) =>
  prefix.every((p, i) => path[i] === p) && path[prefix.length] !== 'joins';

function layout(view: MetricView, issues: MetricViewIssue[]): Node[] {
  const nodes: Node[] = [];
  const walk = (joins: Join[] | undefined, path: (string | number)[], depth: number, parentRow: number) =>
    (joins ?? []).forEach((j, i) => {
      const here = [...path, 'joins', i];
      const row = nodes.length + 1;
      nodes.push({
        path: here,
        alias: j.name,
        table: j.source,
        on: j.on ?? `using ${(j.using ?? []).join(', ')}`,
        depth,
        row,
        parentRow,
        warnings: issues.filter((x) => startsWith(x.path, here)).map((x) => x.message),
      });
      walk(j.joins, here, depth + 1, row);
    });
  walk(view.joins, [], 1, 0);
  return nodes;
}

const short = (table: string) => {
  const last = table.split('.').pop() ?? table;
  return last.length > 36 ? `${last.slice(0, 35)}...` : last;
};

/** Join tree as a diagram plus the same facts as a list, so screen readers get the keys too. */
export function JoinDiagram({ view, issues }: { view: MetricView; issues: MetricViewIssue[] }) {
  const nodes = layout(view, issues);
  const depth = Math.max(0, ...nodes.map((n) => n.depth));
  const box = (x: number, y: number, title: string, sub: string, kind: 'fact' | 'ok' | 'warn') => (
    <g transform={`translate(${x},${y})`}>
      <rect
        width={W}
        height={H}
        rx={6}
        fill={
          kind === 'fact'
            ? 'var(--db-accent-surface-subtle)'
            : kind === 'warn'
              ? 'var(--db-alert-surface-warning)'
              : 'transparent'
        }
        stroke={kind === 'warn' ? 'var(--db-alert-border-warning)' : 'var(--db-border-strong)'}
      />
      <text x={12} y={23} fontSize={14} fontWeight={600} fill="var(--db-text-base)">
        {title}
      </text>
      <text x={12} y={42} fontSize={12} fill="var(--db-text-subtle)">
        {sub}
      </text>
    </g>
  );
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <svg
        role="img"
        aria-label={`Fact table ${view.source} with ${nodes.length} joined tables`}
        width={depth * INDENT + W + 1}
        height={(nodes.length + 1) * ROW}
        style={{ maxWidth: '100%', height: 'auto' }}
        viewBox={`0 0 ${depth * INDENT + W + 1} ${(nodes.length + 1) * ROW}`}
      >
        {nodes.map((n) => {
          const x1 = (n.depth - 1) * INDENT + 18;
          const y1 = n.parentRow * ROW + H;
          const y2 = n.row * ROW + H / 2;
          return (
            <path
              key={`e-${n.alias}`}
              d={`M${x1},${y1} V${y2} H${n.depth * INDENT}`}
              fill="none"
              stroke="var(--db-border-strong)"
            >
              <title>{n.on}</title>
            </path>
          );
        })}
        {box(0, 0, 'source', short(view.source), 'fact')}
        {nodes.map((n) => (
          <g key={n.alias}>
            {box(n.depth * INDENT, n.row * ROW, n.alias, short(n.table), n.warnings.length ? 'warn' : 'ok')}
          </g>
        ))}
      </svg>
      <ul style={{ margin: 0, paddingLeft: 20 }}>
        <li>
          <code>source</code>: {view.source}
        </li>
        {nodes.map((n) => (
          <li key={n.alias}>
            <code>{n.alias}</code>: {n.table} on <code>{n.on}</code>
            {n.warnings.map((w) => (
              <div key={w} style={{ color: 'var(--db-alert-text-warning)' }}>
                Warning: {w}
              </div>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}
