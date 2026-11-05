import type { Ontology } from '../../../shared/readiness';

const W = 240;
const HEAD = 48;
const ROW = 24;
const GAP_X = 96;
const GAP_Y = 24;
const MONO_FONT = 'ui-monospace, SFMono-Regular, Menlo, monospace';

const short = (t: string) => t.split('.').pop() ?? t;
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}...` : s);

interface Box {
  x: number;
  y: number;
  col: number;
  keys: string[];
}

/** Facts on the left, then each table one column further from the nearest fact, like Catalog Explorer lineage. */
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

  // Each card lists the columns its joins use, so an edge starts and ends on a column row.
  const keys = new Map<string, string[]>(tables.map((t) => [t, []]));
  const addKey = (t: string, c: string) => {
    const list = keys.get(t);
    if (list && !list.includes(c)) list.push(c);
  };
  for (const l of o.links) {
    addKey(l.from, l.column);
    addKey(l.to, l.refColumn);
  }

  const heights = new Map<number, number>();
  const boxes = new Map<string, Box>();
  for (const t of tables) {
    const col = level.get(t) ?? last;
    const y = heights.get(col) ?? 0;
    const k = keys.get(t)!;
    boxes.set(t, { x: col * (W + GAP_X), y, col, keys: k });
    heights.set(col, y + cardHeight(k) + GAP_Y);
  }
  const cols = Math.max(1, ...[...boxes.values()].map((b) => b.col + 1));
  return { boxes, width: cols * (W + GAP_X) - GAP_X + 48, height: Math.max(1, ...heights.values()) };
}

const cardHeight = (keys: string[]) => HEAD + Math.max(1, keys.length) * ROW + 8;
const rowY = (b: Box, column: string) => b.y + HEAD + Math.max(0, b.keys.indexOf(column)) * ROW + ROW / 2 + 4;

/** Tables and their joins, column to column, plus the same facts as a list for screen readers. */
export function LineageGraph({ ontology }: { ontology: Ontology }) {
  const { boxes, width, height } = layout(ontology);
  const entity = new Map(ontology.entities.map((e) => [e.table, e]));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div
        style={{
          overflowX: 'auto',
          padding: 16,
          borderRadius: 8,
          border: '1px solid var(--db-border-base)',
          backgroundImage: 'radial-gradient(var(--db-border-base) 1px, transparent 1px)',
          backgroundSize: '16px 16px',
        }}
      >
        <svg
          role="img"
          aria-label={`Lineage of ${ontology.entities.length} table${ontology.entities.length === 1 ? '' : 's'} and ${ontology.links.length} join${ontology.links.length === 1 ? '' : 's'}`}
          width={width}
          height={height}
          viewBox={`-1 -1 ${width} ${height}`}
        >
          <defs>
            <marker id="gsb-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" fill="var(--db-text-subtle)" />
            </marker>
          </defs>
          {ontology.links.map((l) => {
            const a = boxes.get(l.from);
            const b = boxes.get(l.to);
            if (!a || !b) return null;
            const y1 = rowY(a, l.column);
            const y2 = rowY(b, l.refColumn);
            const sameCol = a.col === b.col;
            const forward = a.col < b.col;
            const x1 = forward || sameCol ? a.x + W : a.x;
            const x2 = forward ? b.x : b.x + W;
            const bend = sameCol ? x1 + GAP_X / 2 : (x1 + x2) / 2;
            return (
              <path
                key={`${l.from}.${l.column}`}
                d={`M${x1},${y1} C${bend},${y1} ${bend},${y2} ${x2},${y2}`}
                fill="none"
                stroke={l.declared ? 'var(--db-text-subtle)' : 'var(--db-alert-border-warning)'}
                strokeWidth={1.5}
                strokeDasharray={l.declared ? undefined : '6 4'}
                markerEnd="url(#gsb-arrow)"
              >
                <title>
                  {short(l.from)}.{l.column} {'->'} {short(l.to)}.{l.refColumn}
                  {l.declared ? ' (declared foreign key)' : ' (suggested, not declared)'}
                </title>
              </path>
            );
          })}
          {ontology.entities.map((e) => {
            const b = boxes.get(e.table)!;
            const fact = e.role === 'fact';
            const h = cardHeight(b.keys);
            return (
              <g key={e.table} transform={`translate(${b.x},${b.y})`}>
                <title>{e.table}</title>
                <rect width={W} height={h} rx={8} fill="var(--db-surface-base)" stroke="var(--db-border-strong)" />
                <rect width={4} height={h} rx={2} fill={fact ? 'var(--db-accent-text)' : 'var(--db-border-strong)'} />
                <rect x={14} y={12} width={14} height={14} rx={2} fill="none" stroke="var(--db-text-subtle)" />
                <line x1={14} y1={17} x2={28} y2={17} stroke="var(--db-text-subtle)" />
                <line x1={20} y1={12} x2={20} y2={26} stroke="var(--db-text-subtle)" />
                <text x={36} y={24} fontSize={13} fontWeight={600} fill="var(--db-text-base)">
                  {clip(short(e.table), 22)}
                </text>
                <text x={14} y={40} fontSize={11} fill="var(--db-text-subtle)">
                  {clip(e.entity, 18)} - {fact ? 'fact' : e.role === 'dimension' ? 'dimension' : 'role not known'}
                  {e.score === null ? '' : ` - score ${e.score}`}
                </text>
                <line x1={0} y1={HEAD} x2={W} y2={HEAD} stroke="var(--db-border-base)" />
                {b.keys.length ? (
                  b.keys.map((k, i) => (
                    <text
                      key={k}
                      x={14}
                      y={HEAD + i * ROW + ROW / 2 + 8}
                      fontSize={12}
                      fill="var(--db-text-base)"
                      fontFamily={MONO_FONT}
                    >
                      {clip(k, 28)}
                    </text>
                  ))
                ) : (
                  <text x={14} y={HEAD + ROW / 2 + 8} fontSize={12} fill="var(--db-text-subtle)">
                    No joins found
                  </text>
                )}
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
