import type { Ontology } from '../../../shared/readiness';

const W = 200;
const H = 56;
const GAP_X = 72;
const GAP_Y = 20;

const short = (t: string) => t.split('.').pop() ?? t;

/** Facts first, then each table one column further from the nearest fact. Unlinked tables go last. */
function layout(o: Ontology) {
  const next = new Map<string, Set<string>>();
  for (const l of o.links) {
    next.set(l.from, (next.get(l.from) ?? new Set()).add(l.to));
    next.set(l.to, (next.get(l.to) ?? new Set()).add(l.from));
  }
  const tables = o.entities.map((e) => e.table);
  const facts = o.entities.filter((e) => e.role === 'fact').map((e) => e.table);
  const start = facts.length ? facts : tables.filter((t) => next.has(t)).slice(0, 1);
  const level = new Map<string, number>(start.map((t) => [t, 0]));
  const queue = [...start];
  while (queue.length) {
    const t = queue.shift()!;
    for (const n of next.get(t) ?? []) {
      if (level.has(n) || !tables.includes(n)) continue;
      level.set(n, level.get(t)! + 1);
      queue.push(n);
    }
  }
  const last = Math.max(-1, ...level.values()) + 1;
  const rows = new Map<number, number>();
  const pos = new Map<string, { x: number; y: number }>();
  for (const t of tables) {
    const col = level.get(t) ?? last;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    pos.set(t, { x: col * (W + GAP_X), y: row * (H + GAP_Y) });
  }
  const cols = Math.max(1, ...[...pos.values()].map((p) => p.x / (W + GAP_X) + 1));
  return { pos, width: cols * (W + GAP_X) - GAP_X + 2, height: Math.max(1, ...rows.values()) * (H + GAP_Y) };
}

/** Entities and joins as a diagram, plus the same facts as a list for screen readers. */
export function OntologyGraph({ ontology }: { ontology: Ontology }) {
  const { pos, width, height } = layout(ontology);
  const entity = new Map(ontology.entities.map((e) => [e.table, e]));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ overflowX: 'auto' }}>
        <svg
          role="img"
          aria-label={`${ontology.entities.length} entities and ${ontology.links.length} relationships`}
          width={width}
          height={height}
          viewBox={`-1 -1 ${width} ${height}`}
        >
          {ontology.links.map((l) => {
            const a = pos.get(l.from);
            const b = pos.get(l.to);
            if (!a || !b) return null;
            const [p, q] = a.x <= b.x ? [a, b] : [b, a];
            const x1 = p.x + W;
            const x2 = p.x === q.x ? q.x + W : q.x;
            const bend = p.x === q.x ? x1 + GAP_X / 2 : (x1 + x2) / 2;
            return (
              <path
                key={`${l.from}.${l.column}`}
                d={`M${x1},${p.y + H / 2} C${bend},${p.y + H / 2} ${bend},${q.y + H / 2} ${x2},${q.y + H / 2}`}
                fill="none"
                stroke={l.declared ? 'var(--db-border-strong)' : 'var(--db-alert-border-warning)'}
                strokeWidth={1.5}
                strokeDasharray={l.declared ? undefined : '6 4'}
              >
                <title>
                  {short(l.from)}.{l.column} {'->'} {short(l.to)}.{l.refColumn}
                  {l.declared ? '' : ' (not declared)'}
                </title>
              </path>
            );
          })}
          {ontology.entities.map((e) => {
            const p = pos.get(e.table)!;
            const fact = e.role === 'fact';
            return (
              <g key={e.table} transform={`translate(${p.x},${p.y})`}>
                <rect
                  width={W}
                  height={H}
                  rx={6}
                  fill={fact ? 'var(--db-accent-surface-subtle)' : 'var(--db-surface-base)'}
                  stroke="var(--db-border-strong)"
                />
                <text x={10} y={20} fontSize={13} fontWeight={600} fill="var(--db-text-base)">
                  {e.entity.length > 24 ? `${e.entity.slice(0, 23)}...` : e.entity}
                </text>
                <text x={10} y={38} fontSize={11} fill="var(--db-text-subtle)">
                  {short(e.table)} - {fact ? 'fact' : e.role === 'dimension' ? 'dimension' : 'role not known'}
                  {e.score === null ? '' : ` - ${e.score}`}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <ul style={{ margin: 0, paddingLeft: 20 }}>
        {ontology.links.map((l) => (
          <li key={`${l.from}.${l.column}`}>
            {entity.get(l.from)?.entity ?? short(l.from)} to {entity.get(l.to)?.entity ?? short(l.to)}:{' '}
            <code>
              {short(l.from)}.{l.column}
            </code>{' '}
            ={' '}
            <code>
              {short(l.to)}.{l.refColumn}
            </code>
            {l.declared ? ' (declared foreign key)' : ' (suggested by the key names, not declared)'}
          </li>
        ))}
      </ul>
    </div>
  );
}
