export type NodeKind = 'table' | 'job';
export type EdgeKind = 'data' | 'orchestration';
export type Role = 'source' | 'intermediate' | 'terminal' | 'orphan' | 'job';

export interface LNode {
  id: string;
  name: string;
  kind: NodeKind;
  tags: string[];
  process?: string;
  role?: Role;
  uc?: { layer: string; target: string; sharedWith?: string[] };
  volume?: { rows?: number; bytes?: number };
}
export interface LEdge {
  from: string;
  to: string;
  kind: EdgeKind;
  via: string[];
  grain: 'statement' | 'job';
  tech: string;
}
export interface LProgram {
  name: string;
  tech: string;
  reads: string[];
  writes: string[];
  complexity?: string;
  type?: string | null;
  folder?: string | null;
  drivers?: Record<string, unknown>;
}
export interface ProcessInfo {
  name: string;
  tech: string[];
  programs: string[];
  objects: string[];
  complexity: Record<string, number>;
  maxComplexity: string;
  cycle: number | null;
  upstream: string[];
  downstream: string[];
  volume?: { rows: number; bytes: number };
}
export interface Hub {
  id: string;
  writers: string[];
  readers: string[];
  processCount: number;
}
export interface Insights {
  summary: {
    processes: number;
    programs: number;
    tables: number;
    edges: number;
    cycles: number;
    hubs: number;
    roles: Record<string, number>;
    complexity: Record<string, number>;
    technologies: Record<string, number>;
    volumes?: { provided: number; matched: number };
  };
  processes: ProcessInfo[];
  processEdges: { from: string; to: string; tables: string[] }[];
  hubs: Hub[];
  trust: Record<string, number>;
  statistics: Statistics;
}
export interface Statistics {
  fanIn: { id: string; count: number }[];
  fanOut: { id: string; count: number }[];
  transformations: { name: string; count: number }[];
  functions: { name: string; count: number }[];
  code: Record<string, number>;
  programTypes: Record<string, number>;
  schemas: { name: string; count: number }[];
  processSize: { min: number; median: number; max: number };
  crossProcessLinks: number;
  selfContainedProcesses: number;
}
export interface ColumnEdge {
  from: string;
  to: string;
  via: string[];
}
export interface Diff {
  previous: string;
  addedObjects: string[];
  removedObjects: { id: string; name: string; kind: string }[];
  addedEdges: { from: string; to: string; kind: string }[];
  removedEdges: { from: string; to: string; kind: string }[];
  addedProcesses: string[];
  removedProcesses: string[];
  movedObjects: { id: string; from: string | null; to: string | null }[];
}
export interface LineageDoc {
  insights: Insights;
  nodes: LNode[];
  edges: LEdge[];
  programs: LProgram[];
  columns?: ColumnEdge[];
  diff?: Diff;
}

export const LEVELS = ['LOW', 'MEDIUM', 'HIGH', 'COMPLEX', 'VERY_HIGH'] as const;
export const SHARED = '(shared by several processes)';

export interface Model {
  doc: LineageDoc;
  ins: Insights;
  byId: Map<string, LNode>;
  up: Map<string, LEdge[]>;
  down: Map<string, LEdge[]>;
  programs: Map<string, LProgram>;
  techOf: Map<string, Set<string>>;
  programsOf: Map<string, { program: LProgram; role: 'reads' | 'writes' }[]>;
  procByName: Map<string, ProcessInfo>;
  hubById: Map<string, Hub>;
  processOfProgram: Map<string, string>;
}

const PLACEHOLDER = '__LINEAGE_' + 'JSON__';

export async function loadDoc(): Promise<LineageDoc> {
  const raw = document.getElementById('lineage-data')?.textContent?.trim() ?? '';
  let doc: LineageDoc;
  if (raw && raw !== PLACEHOLDER) doc = JSON.parse(raw);
  else if (import.meta.env.DEV) doc = await fetch('./sample.json').then((r) => r.json());
  else throw new Error('This file has no lineage data. Generate it with sts-lb-lineage.');
  if (!doc.insights) throw new Error('This lineage file has no insights. Regenerate it with the current sts-lb-lineage.');
  return doc;
}

const push = <K, V>(m: Map<K, V[]>, k: K, v: V) => {
  const list = m.get(k);
  if (list) list.push(v);
  else m.set(k, [v]);
};

export function buildModel(doc: LineageDoc): Model {
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  const up = new Map<string, LEdge[]>();
  const down = new Map<string, LEdge[]>();
  const techOf = new Map<string, Set<string>>();
  const addTech = (id: string, t: string) => {
    if (!techOf.has(id)) techOf.set(id, new Set());
    techOf.get(id)!.add(t);
  };
  for (const e of doc.edges) {
    push(down, e.from, e);
    push(up, e.to, e);
    addTech(e.from, e.tech);
    addTech(e.to, e.tech);
  }
  const programs = new Map(doc.programs.map((p) => [p.name, p]));
  const programsOf = new Map<string, { program: LProgram; role: 'reads' | 'writes' }[]>();
  for (const p of doc.programs) {
    for (const id of p.reads) {
      push(programsOf, id, { program: p, role: 'reads' });
      addTech(id, p.tech);
    }
    for (const id of p.writes) {
      push(programsOf, id, { program: p, role: 'writes' });
      addTech(id, p.tech);
    }
  }
  const procByName = new Map(doc.insights.processes.map((p) => [p.name, p]));
  const processOfProgram = new Map<string, string>();
  for (const p of doc.insights.processes) for (const prog of p.programs) processOfProgram.set(prog, p.name);
  return {
    doc,
    ins: doc.insights,
    byId,
    up,
    down,
    programs,
    techOf,
    programsOf,
    procByName,
    hubById: new Map(doc.insights.hubs.map((h) => [h.id, h])),
    processOfProgram,
  };
}

export const shortName = (path: string) => {
  const last = path.split('/').pop() ?? path;
  // Talend jobs: "SourceCode.<project>.<job> 0.1.<PROJECT>.process.<folder>.<job>" -> "<job>"
  const i = last.lastIndexOf('.process.');
  return i >= 0 ? last.slice(last.lastIndexOf('.') + 1) : last;
};
export const techList = (m: Model, id: string) => [...(m.techOf.get(id) ?? [])].sort();

/** Breadth-first walk; depth Infinity = all. Returns node id -> hops from the start set. */
export function walk(m: Model, start: string[], side: 'up' | 'down', depth = Infinity): Map<string, number> {
  const seen = new Map(start.map((s) => [s, 0]));
  let frontier = start;
  for (let d = 1; d <= depth && frontier.length; d++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const e of (side === 'down' ? m.down : m.up).get(id) ?? []) {
        const other = side === 'down' ? e.to : e.from;
        if (!seen.has(other)) {
          seen.set(other, d);
          next.push(other);
        }
      }
    }
    frontier = next;
  }
  return seen;
}

/** Every node on some path from a to b (inclusive). */
export function pathBetween(m: Model, a: string[], b: string[]): Set<string> {
  const down = walk(m, a, 'down');
  const up = walk(m, b, 'up');
  return new Set([...down.keys()].filter((id) => up.has(id)));
}

export type GroupBy = 'process' | 'tech' | 'schema' | 'kind' | 'none';
export const GROUP_BY_LABEL: Record<GroupBy, string> = {
  process: 'Parent process',
  tech: 'Technology',
  schema: 'Schema',
  kind: 'Type',
  none: 'None',
};

export const schemaOf = (n: LNode) =>
  n.kind === 'job' ? '(jobs)' : n.name.includes('.') ? n.name.slice(0, n.name.lastIndexOf('.')) : '(no schema)';

export function groupOf(model: Model, by: GroupBy, id: string): string {
  const n = model.byId.get(id);
  if (!n) return 'Connected processes';
  switch (by) {
    case 'process':
      return n.process ?? '(no process)';
    case 'tech':
      return techList(model, id).join(', ') || '(unknown)';
    case 'schema':
      return schemaOf(n);
    case 'kind':
      return n.kind === 'job' ? 'Jobs' : 'Tables';
    default:
      return '';
  }
}

export const groupLabel = (by: GroupBy, key: string) => (by === 'process' ? shortName(key) : key);

export function downloadCsv(filename: string, header: string[], rows: (string | number)[][]) {
  const cell = (v: string | number) => {
    // neutralize spreadsheet formulas (CSV injection) in text cells
    const s = typeof v === 'string' && /^[=+\-@\t\r]/.test(v) ? `'${v}` : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [header, ...rows].map((r) => r.map(cell).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function fmtBytes(b?: number): string {
  if (b === undefined) return '-';
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let i = 0;
  let v = b;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${u[i]}`;
}

// ---------- optional AI (only when served by `sts-lb-lineage --serve`) ----------

/** Session token injected by the local server; absent (placeholder) when opened from file://. */
export function aiSession(): string | null {
  const v = document.querySelector('meta[name="sts-ai-session"]')?.getAttribute('content') ?? '';
  return location.protocol.startsWith('http') && /^[A-Za-z0-9_-]{32}$/.test(v) ? v : null;
}

export async function aiStatus(): Promise<{ endpoint: string; host: string } | null> {
  const s = aiSession();
  if (!s) return null;
  const r = await fetch('/api/ai/status', { headers: { 'X-STS-Session': s } });
  return r.ok ? r.json() : null;
}

export async function aiAsk(body: { target: string; mode: string; to?: string; question?: string; history?: { q: string; a: string }[] }) {
  const s = aiSession();
  if (!s) throw new Error('AI is available only when the viewer is served with --serve.');
  const r = await fetch('/api/ai', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-STS-Session': s },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(j.error ?? `HTTP ${r.status}`);
  return j as { answer: string; objects: number; truncated: boolean };
}
