import { quote } from './common';

/**
 * DAX measures to metric view SQL, by rules. It knows the common forms: SUM, AVERAGE, MIN, MAX, MEDIAN,
 * DISTINCTCOUNT, COUNT, COUNTA, COUNTROWS, DIVIDE, CALCULATE with simple filters, IF, BLANK, arithmetic and measure
 * references. Anything else (VAR, iterators such as SUMX, time intelligence, ALL, FILTER) returns null, and the
 * caller marks the measure for the AI or for a person.
 */

type Tok =
  | { t: 'num' | 'str' | 'op' | '(' | ')' | ',' | 'name'; v: string }
  | { t: 'col'; table: string; v: string }
  | { t: 'meas'; v: string }
  | { t: 'table'; v: string };

export interface DaxContext {
  /** The SQL of a column of a table in the view, or null. */
  column(table: string, column: string): string | null;
  /** True when the measure is converted (so MEASURE() can refer to it). */
  measure(name: string): boolean;
  /** True when the table is in the view (for COUNTROWS). */
  table(name: string): boolean;
}

function tokenize(dax: string): Tok[] | null {
  const s = dax.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(\/\/|--)[^\n]*/g, ' ');
  const out: Tok[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (/\s/.test(c)) i++;
    else if (/[0-9.]/.test(c)) {
      const m = /^[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?/.exec(s.slice(i));
      if (!m) return null;
      out.push({ t: 'num', v: m[0] });
      i += m[0].length;
    } else if (c === '"') {
      let j = i + 1;
      let v = '';
      for (; j < s.length; j++) {
        if (s[j] === '"' && s[j + 1] === '"') {
          v += '"';
          j++;
        } else if (s[j] === '"') break;
        else v += s[j];
      }
      if (j >= s.length) return null;
      out.push({ t: 'str', v });
      i = j + 1;
    } else if (c === "'" || c === '[' || /[A-Za-z_]/.test(c)) {
      let table = '';
      if (c === "'") {
        const end = s.indexOf("'", i + 1);
        if (end < 0) return null;
        table = s.slice(i + 1, end);
        i = end + 1;
      } else if (c !== '[') {
        const m = /^[A-Za-z_][A-Za-z0-9_.]*/.exec(s.slice(i))!;
        table = m[0];
        i += m[0].length;
      }
      if (s[i] === '[') {
        const end = s.indexOf(']', i);
        if (end < 0) return null;
        const name = s.slice(i + 1, end);
        out.push(table ? { t: 'col', table, v: name } : { t: 'meas', v: name });
        i = end + 1;
      } else if (c === "'") out.push({ t: 'table', v: table });
      else out.push({ t: 'name', v: table });
    } else if ('(),'.includes(c)) {
      out.push({ t: c as '(' | ')' | ',', v: c });
      i++;
    } else {
      const m = /^(&&|\|\||<>|<=|>=|[-+*/=<>&])/.exec(s.slice(i));
      if (!m) return null;
      out.push({ t: 'op', v: m[0] });
      i += m[0].length;
    }
  }
  return out;
}

/** True when the SQL is one aggregation call, such as SUM(x), and not SUM(a) / SUM(b). */
function oneAggregation(sql: string): boolean {
  const m = /^(SUM|AVG|MIN|MAX|MEDIAN|COUNT)\(/.exec(sql);
  if (!m || sql.includes('FILTER')) return false;
  let depth = 0;
  for (let k = m[0].length - 1; k < sql.length; k++) {
    if (sql[k] === '(') depth++;
    else if (sql[k] === ')' && --depth === 0) return k === sql.length - 1;
  }
  return false;
}

const OPS: Record<string, string> = { '&&': 'AND', '||': 'OR', '&': '||' };
const AGG: Record<string, string> = { SUM: 'SUM', AVERAGE: 'AVG', MIN: 'MIN', MAX: 'MAX', MEDIAN: 'MEDIAN' };

export function translateDax(dax: string, ctx: DaxContext): string | null {
  const parsed = tokenize(dax);
  if (!parsed?.length) return null;
  const toks: Tok[] = parsed;
  let i = 0;
  const fail = (): never => {
    throw new Error('no rule');
  };

  const col = (): string => {
    const t = toks[i++];
    if (t?.t !== 'col') fail();
    const c = t as { table: string; v: string };
    return ctx.column(c.table, c.v) ?? fail();
  };
  const expect = (t: string) => (toks[i++]?.t === t ? undefined : fail());

  // A list of expressions until the closing parenthesis of a call.
  const args = (): string[][] => {
    expect('(');
    const list: string[][] = [];
    if (toks[i]?.t === ')') {
      i++;
      return list;
    }
    for (;;) {
      list.push([expr()]);
      const t = toks[i++];
      if (t?.t === ')') return list;
      if (t?.t !== ',') fail();
    }
  };

  const call = (name: string): string => {
    const n = name.toUpperCase();
    if (AGG[n] || n === 'DISTINCTCOUNT' || n === 'COUNT' || n === 'COUNTA') {
      expect('(');
      const c = col();
      expect(')');
      return n === 'DISTINCTCOUNT' ? `COUNT(DISTINCT ${c})` : `${AGG[n] ?? 'COUNT'}(${c})`;
    }
    if (n === 'COUNTROWS') {
      expect('(');
      const t = toks[i++];
      if ((t?.t !== 'table' && t?.t !== 'name') || !ctx.table(t.v)) fail();
      expect(')');
      return 'COUNT(1)';
    }
    if (n === 'BLANK') {
      expect('(');
      expect(')');
      return 'NULL';
    }
    const a = args().map((x) => x[0]);
    if (n === 'DIVIDE' && (a.length === 2 || a.length === 3))
      return a.length === 2 ? `${a[0]} / NULLIF(${a[1]}, 0)` : `COALESCE(${a[0]} / NULLIF(${a[1]}, 0), ${a[2]})`;
    if (n === 'IF' && (a.length === 2 || a.length === 3))
      return `CASE WHEN ${a[0]} THEN ${a[1]}${a.length === 3 ? ` ELSE ${a[2]}` : ''} END`;
    // CALCULATE of one aggregation with boolean filters on columns. A filter on a measure has no metric view form.
    if (n === 'CALCULATE' && a.length >= 2 && oneAggregation(a[0]))
      return `${a[0]} FILTER (WHERE ${a
        .slice(1)
        .map((f) => (a.length > 2 ? `(${f})` : f))
        .join(' AND ')})`;
    return fail();
  };

  function expr(): string {
    const parts: string[] = [];
    while (i < toks.length && toks[i].t !== ')' && toks[i].t !== ',') {
      const t = toks[i];
      if (t.t === 'num' || t.t === 'str' || t.t === 'op') {
        parts.push(t.t === 'num' ? t.v : t.t === 'str' ? `'${t.v.replace(/'/g, "''")}'` : (OPS[t.v] ?? t.v));
        i++;
      } else if (t.t === 'meas') {
        if (!ctx.measure(t.v)) fail();
        parts.push(`MEASURE(${quote(t.v)})`);
        i++;
      } else if (t.t === 'col') parts.push(col());
      else if (t.t === '(') {
        i++;
        parts.push(`(${expr()})`);
        expect(')');
      } else if (t.t === 'name' && toks[i + 1]?.t === '(') {
        i++;
        parts.push(call(t.v));
      } else if (t.t === 'name' && /^(TRUE|FALSE)$/i.test(t.v)) {
        parts.push(t.v.toUpperCase());
        i++;
      } else fail();
    }
    if (!parts.length) fail();
    return parts.join(' ').replace(/\( /g, '(').replace(/ \)/g, ')');
  }

  try {
    const sql = expr();
    return i === toks.length ? sql : null;
  } catch {
    return null;
  }
}
