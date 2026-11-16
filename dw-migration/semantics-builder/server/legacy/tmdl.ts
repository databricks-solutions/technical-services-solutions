/**
 * TMDL (the text folder of a Power BI project or a Tabular model) to the TMSL shape that tabular.ts reads: tables
 * with columns, measures and partitions, and relationships. Indentation (tabs, or 4 spaces) gives the nesting. Only
 * the objects and properties that the converter uses are read; the rest is skipped.
 */

export interface TmdlModel {
  tables: {
    name: string;
    description?: string;
    isHidden?: boolean;
    columns: {
      name: string;
      dataType?: string;
      sourceColumn?: string;
      isHidden?: boolean;
      type?: string;
      expression?: string;
      description?: string;
    }[];
    measures: { name: string; expression?: string; description?: string; isHidden?: boolean }[];
    partitions: { source: { type?: string; expression?: string } }[];
  }[];
  relationships: { fromTable: string; fromColumn: string; toTable: string; toColumn: string; isActive?: boolean }[];
}

const MAX_LINES = 500_000;

/** A name at the start of s: 'quoted name' (with '' for a quote) or a bare word. */
function readName(s: string): [string, string] {
  if (s.startsWith("'")) {
    let v = '';
    let i = 1;
    for (; i < s.length; i++) {
      if (s[i] === "'" && s[i + 1] === "'") {
        v += "'";
        i++;
      } else if (s[i] === "'") break;
      else v += s[i];
    }
    return [v, s.slice(i + 1)];
  }
  const m = /^[^\s=.]+/.exec(s);
  return [m?.[0] ?? '', s.slice(m?.[0].length ?? 0)];
}

/** Table.Column, with either part quoted. */
function readColumnRef(s: string): [string, string] | null {
  const [table, rest] = readName(s.trim());
  if (!rest.startsWith('.')) return null;
  const [column] = readName(rest.slice(1));
  return table && column ? [table, column] : null;
}

const indentOf = (line: string) => {
  const m = /^[\t ]*/.exec(line)![0];
  return [...m].reduce((n, c) => n + (c === '\t' ? 1 : 0.25), 0);
};
const unfence = (s: string) => s.replace(/^```\s*\n?/, '').replace(/\n?\s*```$/, '');

export function parseTmdl(src: string): TmdlModel {
  const lines = src.replace(/\r\n?/g, '\n').split('\n');
  if (lines.length > MAX_LINES) throw new Error('The model has too many lines.');
  const model: TmdlModel = { tables: [], relationships: [] };
  type Obj = Record<string, unknown>;
  let table: TmdlModel['tables'][number] | null = null;
  let rel: Obj | null = null;
  const rels: Obj[] = [];
  let item: Obj | null = null; // the measure, column or partition being read
  let doc: string[] = [];

  // Lines that are deeper than `base` belong to the expression that started on the line before.
  const block = (start: number, base: number, open = false) => {
    const out: string[] = [];
    let i = start;
    let fenced = open;
    for (; i < lines.length; i++) {
      const l = lines[i];
      if (l.trim().startsWith('```')) fenced = !fenced;
      else if (!fenced && l.trim() && indentOf(l) <= base) break;
      out.push(l.trim());
    }
    while (out.length && !out[out.length - 1]) out.pop();
    return { text: unfence(out.join('\n')), next: i };
  };

  for (let i = 0; i < lines.length; ) {
    const line = lines[i];
    const t = line.trim();
    const ind = Math.floor(indentOf(line));
    if (!t) {
      i++;
      continue;
    }
    if (t.startsWith('///')) {
      doc.push(t.slice(3).trim());
      i++;
      continue;
    }
    const description = doc.length ? doc.join('\n') : undefined;
    doc = [];
    if (ind === 0) {
      table = null;
      rel = null;
      item = null;
      const [kw, rest] = [t.split(/\s+/)[0], t.slice(t.split(/\s+/)[0].length).trim()];
      if (kw === 'table') {
        table = { name: readName(rest)[0], description, columns: [], measures: [], partitions: [] };
        model.tables.push(table);
      } else if (kw === 'relationship') {
        rel = {};
        rels.push(rel);
      }
      i++;
      continue;
    }
    if (ind === 1 && table) {
      const kw = t.split(/\s+/)[0];
      const rest = t.slice(kw.length).trim();
      if (kw === 'measure' || kw === 'column' || kw === 'partition') {
        const [name, after] = readName(rest);
        const eq = after.trim().startsWith('=') ? after.trim().slice(1).trim() : null;
        let expression: string | undefined;
        i++;
        if (eq !== null && kw !== 'partition') {
          const b = block(i, 2, eq.startsWith('```'));
          expression = unfence(`${eq}\n${b.text}`).trim();
          i = b.next;
        }
        if (kw === 'measure') {
          item = { name, expression, description };
          table.measures.push(item as TmdlModel['tables'][number]['measures'][number]);
        } else if (kw === 'column') {
          item = { name, description, ...(eq !== null ? { type: 'calculated', expression } : {}) };
          table.columns.push(item as TmdlModel['tables'][number]['columns'][number]);
        } else {
          item = { type: eq ?? undefined };
          table.partitions.push({ source: item });
        }
        continue;
      }
      item = null;
      if (t === 'isHidden') table.isHidden = true;
      i++;
      continue;
    }
    if (ind >= 2 && item) {
      const m = /^(\w+)\s*(?::\s*(.*)|=\s*(.*))?$/.exec(t);
      i++;
      if (!m) continue;
      const [, key, colon, eq] = m;
      if (eq !== undefined) {
        // An expression property, such as the source of a partition.
        const b = block(i, ind + 1, eq.trim().startsWith('```'));
        const text = unfence(`${eq}\n${b.text}`).trim();
        i = b.next;
        if (key === 'source' || key === 'expression') item.expression = text;
      } else if (colon === undefined) item[key] = true;
      else if (['dataType', 'sourceColumn', 'mode', 'description'].includes(key)) item[key] = colon.trim();
      else if (key === 'isHidden') item.isHidden = colon.trim() !== 'false';
      continue;
    }
    if (ind >= 1 && rel) {
      const m = /^(\w+)\s*:\s*(.*)$/.exec(t);
      if (m?.[1] === 'fromColumn' || m?.[1] === 'toColumn') {
        const ref = readColumnRef(m[2]);
        if (ref) {
          const side = m[1] === 'fromColumn' ? 'from' : 'to';
          rel[`${side}Table`] = ref[0];
          rel[`${side}Column`] = ref[1];
        }
      } else if (m?.[1] === 'isActive') rel.isActive = m[2].trim() !== 'false';
      i++;
      continue;
    }
    i++;
  }
  const str = (v: unknown) => (typeof v === 'string' ? v : '');
  model.relationships = rels
    .map((r) => ({
      fromTable: str(r.fromTable),
      fromColumn: str(r.fromColumn),
      toTable: str(r.toTable),
      toColumn: str(r.toColumn),
      ...(r.isActive === false ? { isActive: false } : {}),
    }))
    .filter((r) => r.fromTable && r.toTable);
  return model;
}
