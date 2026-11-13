import type { Ontology } from '../../../shared/readiness';
import { LineageCanvas } from './LineageCanvas';
import type { CanvasEdge, CanvasNode } from './LineageCanvas';

const short = (t: string) => t.split('.').pop() ?? t;

/** Facts on the left, then each table one column further from the nearest fact, like Catalog Explorer lineage. */
function levels(o: Ontology) {
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
  return (t: string) => level.get(t) ?? last;
}

/** Tables and their joins on a canvas, plus the same facts as a list for screen readers. */
export function LineageGraph({ ontology }: { ontology: Ontology }) {
  const levelOf = levels(ontology);
  const keys = new Map<string, Set<string>>(ontology.entities.map((e) => [e.table, new Set()]));
  for (const l of ontology.links) {
    keys.get(l.from)?.add(l.column);
    keys.get(l.to)?.add(l.refColumn);
  }
  const rowAt = new Map<number, number>();
  const nodes: CanvasNode[] = ontology.entities.map((e) => {
    const col = levelOf(e.table);
    const row = rowAt.get(col) ?? 0;
    rowAt.set(col, row + 1);
    const role = e.role === 'fact' ? 'fact' : e.role === 'dimension' ? 'dimension' : 'role not known';
    return {
      id: e.table,
      title: short(e.table),
      subtitle: `${e.entity} - ${role}${e.score === null ? '' : ` - score ${e.score}`}`,
      kind: e.role === 'fact' ? 'fact' : 'table',
      columns: [...(keys.get(e.table) ?? [])].map((name) => ({ name, type: 'key' })),
      col,
      row,
    };
  });
  const edges: CanvasEdge[] = ontology.links.map((l) => ({
    id: `${l.from}.${l.column}>${l.to}`,
    source: l.from,
    target: l.to,
    label: `${l.column} = ${l.refColumn}`,
    dashed: !l.declared,
    warn: !l.declared,
  }));
  const entity = new Map(ontology.entities.map((e) => [e.table, e]));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <LineageCanvas
        label={`Relationships of ${ontology.entities.length} table${ontology.entities.length === 1 ? '' : 's'} and ${ontology.links.length} join${ontology.links.length === 1 ? '' : 's'}`}
        nodes={nodes}
        edges={edges}
      />
      <details>
        <summary>Joins as text</summary>
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
      </details>
    </div>
  );
}
