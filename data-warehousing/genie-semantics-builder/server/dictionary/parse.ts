import {
  DICTIONARY_AGGREGATIONS,
  DICTIONARY_COLUMNS,
  DICTIONARY_KINDS,
  DICTIONARY_STATUSES,
} from '../../shared/dictionary';
import type { DictionaryEntry, DictionaryKind } from '../../shared/dictionary';

export const MAX_ROWS = 2000;
export const MAX_COLUMNS = 50;
export const MAX_CELL = 4000;

const norm = (s: string) =>
  s
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, ' ');
const HEADERS = new Map<string, string>([
  ...DICTIONARY_COLUMNS.flatMap((c) => [c.key, c.header, ...c.aliases].map((h): [string, string] => [norm(h), c.key])),
  ['kind', 'kind'],
  ['type', 'kind'],
]);

/** The kind a sheet name or a Markdown heading stands for. */
export function kindOf(title: string): DictionaryKind | null {
  if (/metric|measure|kpi/i.test(title)) return 'metric';
  if (/dimension|attribute/i.test(title)) return 'dimension';
  if (/glossary|term/i.test(title)) return 'term';
  return null;
}

const entryKey = (e: Pick<DictionaryEntry, 'kind' | 'name'>) => `${e.kind}:${e.name.toLowerCase()}`;

/** A table whose first row is the header. Problems name the table and the row, counting the header as row 1. */
export function entriesFromTable(rows: string[][], kind: DictionaryKind, label = 'Table') {
  const entries: DictionaryEntry[] = [];
  const problems: string[] = [];
  const [header = [], ...body] = rows;
  const keys = header.slice(0, MAX_COLUMNS).map((h) => HEADERS.get(norm(h)) ?? null);
  if (!keys.includes('name')) return { entries, problems: [`${label}: no name column. Use the template headers.`] };
  if (body.length > MAX_ROWS) problems.push(`${label}: only the first ${MAX_ROWS} rows were read.`);

  const seen = new Map<string, number>();
  for (const [i, cells] of body.slice(0, MAX_ROWS).entries()) {
    const row = i + 2;
    const at = `${label} row ${row}`;
    if (cells.every((c) => !c?.trim())) continue;
    const fields: Record<string, string> = {};
    const notes: Record<string, string> = {};
    cells.slice(0, MAX_COLUMNS).forEach((raw, j) => {
      let v = (raw ?? '').trim();
      if (!v) return;
      if (v.length > MAX_CELL) {
        problems.push(`${at}: a cell is longer than ${MAX_CELL} characters and was cut.`);
        v = v.slice(0, MAX_CELL);
      }
      if (keys[j]) fields[keys[j]] = v;
      else if (header[j]?.trim()) notes[header[j].trim()] = v;
    });
    if (!fields.name) {
      problems.push(`${at}: name is empty.`);
      continue;
    }
    if (!fields.definition) {
      problems.push(`${at}: definition is empty.`);
      continue;
    }

    const k = (DICTIONARY_KINDS as readonly string[]).includes(fields.kind?.toLowerCase() ?? '')
      ? (fields.kind.toLowerCase() as DictionaryKind)
      : kind;
    const entry: DictionaryEntry = {
      kind: k,
      name: fields.name,
      definition: fields.definition,
      synonyms: (fields.synonyms ?? '')
        .split(';')
        .map((x) => x.trim())
        .filter(Boolean)
        .slice(0, 10),
      status: 'draft',
      notes,
    };
    for (const f of ['display_name', 'formula', 'format', 'grain', 'source', 'owner'] as const)
      if (fields[f]) entry[f] = fields[f];
    if (fields.aggregation) {
      const a = fields.aggregation.toLowerCase().replace(/\s+/g, '_');
      if ((DICTIONARY_AGGREGATIONS as readonly string[]).includes(a))
        entry.aggregation = a as DictionaryEntry['aggregation'];
      else
        problems.push(
          `${at}: aggregation "${fields.aggregation}" is not one of ${DICTIONARY_AGGREGATIONS.join(', ')}. It was left out.`
        );
    }
    if (fields.status) {
      const s = fields.status.toLowerCase();
      if ((DICTIONARY_STATUSES as readonly string[]).includes(s)) entry.status = s as DictionaryEntry['status'];
      else
        problems.push(
          `${at}: status "${fields.status}" is not one of ${DICTIONARY_STATUSES.join(', ')}. It was set to draft.`
        );
    }
    const dup = seen.get(entryKey(entry));
    if (dup) {
      problems.push(`${at}: "${entry.name}" is already on row ${dup}.`);
      continue;
    }
    seen.set(entryKey(entry), row);
    entries.push(entry);
  }
  return { entries, problems };
}

/** RFC 4180 CSV: quoted cells may hold commas, quotes ("") and line breaks. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += ch;
  }
  if (cell || row.length) rows.push([...row, cell]);
  return rows;
}

const splitRow = (line: string) =>
  line
    .trim()
    .replace(/^\||\|$/g, '')
    .split(/(?<!\\)\|/)
    .map((c) => c.trim().replace(/\\\|/g, '|'));

/** Merges tables and drops entries already seen in an earlier table. */
function merge(parts: { entries: DictionaryEntry[]; problems: string[] }[]) {
  const entries: DictionaryEntry[] = [];
  const problems = parts.flatMap((p) => p.problems);
  const seen = new Set<string>();
  for (const e of parts.flatMap((p) => p.entries)) {
    if (seen.has(entryKey(e))) problems.push(`"${e.name}" is in more than one table; the first one was kept.`);
    else {
      seen.add(entryKey(e));
      entries.push(e);
    }
  }
  return { entries, problems };
}

/** Every pipe table with a name column. The heading above a table sets its kind. */
export function parseMarkdown(text: string) {
  const lines = text.split(/\r?\n/);
  const parts: ReturnType<typeof entriesFromTable>[] = [];
  let heading = '';
  for (let i = 0; i < lines.length; i++) {
    const h = /^#{1,6}\s+(.*)$/.exec(lines[i]);
    if (h) heading = h[1].trim();
    if (!lines[i].trim().startsWith('|') || !/^\s*\|?\s*:?-{3,}/.test(lines[i + 1] ?? '')) continue;
    const rows = [splitRow(lines[i])];
    let j = i + 2;
    for (; j < lines.length && lines[j].trim().startsWith('|'); j++) rows.push(splitRow(lines[j]));
    i = j - 1;
    if (!rows[0].some((c) => HEADERS.get(norm(c)) === 'name')) continue;
    parts.push(entriesFromTable(rows, kindOf(heading) ?? 'metric', heading || 'Table'));
  }
  if (!parts.length) return { entries: [], problems: ['No table with a name column was found.'] };
  return merge(parts);
}

/** Every sheet but "Read me"; the sheet name sets the kind. Cell values come as text, formulas never run. */
export async function parseXlsx(buffer: Buffer) {
  const { default: readExcelFile } = await import('read-excel-file/node');
  const sheets = await readExcelFile(buffer);
  const parts = sheets
    .filter((s) => !/read ?me/i.test(s.sheet))
    .map((s) =>
      entriesFromTable(
        s.data.map((r) =>
          r.map((c) =>
            c === null || c === undefined ? '' : c instanceof Date ? c.toISOString().slice(0, 10) : String(c)
          )
        ),
        kindOf(s.sheet) ?? 'metric',
        s.sheet
      )
    )
    .filter(
      (p) =>
        !(
          p.entries.length === 0 &&
          p.problems.length === 1 &&
          p.problems[0].endsWith('no name column. Use the template headers.')
        )
    );
  if (!parts.length) return { entries: [], problems: ['No sheet with a name column was found.'] };
  return merge(parts);
}
