/**
 * Tableau calculated fields to SQL, by rules. It knows aggregations (SUM, AVG, MIN, MAX, MEDIAN, COUNT, COUNTD),
 * ZN, IIF, IF/ELSEIF/ELSE/END, CASE/WHEN, ISNULL, ABS, ROUND, UPPER, LOWER, TRIM, LEN, CONTAINS, DATETRUNC,
 * arithmetic, comparisons and field references. LOD expressions ({FIXED ...}), table calculations and other
 * functions return null, for the AI or a person.
 */

export interface CalcContext {
  /** The SQL of a field reference such as [Sales] or [Calculation_123], or null. */
  field(name: string): string | null;
}

type Tok = { t: 'ref' | 'str' | 'num' | 'op' | 'name' | '(' | ')' | ','; v: string };

function tokenize(src: string): Tok[] | null {
  const s = src.replace(/\/\/[^\n]*/g, ' ').replace(/\/\*[\s\S]*?\*\//g, ' ');
  const out: Tok[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (/\s/.test(c)) i++;
    else if (c === '[') {
      // [Field] or [Data source].[Field]: the last part names the field.
      let end = s.indexOf(']', i);
      while (end >= 0 && s[end + 1] === ']') end = s.indexOf(']', end + 2);
      if (end < 0) return null;
      let v = s.slice(i + 1, end).replace(/]]/g, ']');
      i = end + 1;
      if (s[i] === '.' && s[i + 1] === '[') {
        const e2 = s.indexOf(']', i + 2);
        if (e2 < 0) return null;
        v = s.slice(i + 2, e2);
        i = e2 + 1;
      }
      out.push({ t: 'ref', v });
    } else if (c === "'" || c === '"') {
      let j = i + 1;
      let v = '';
      for (; j < s.length; j++) {
        if (s[j] === c && s[j + 1] === c) {
          v += c;
          j++;
        } else if (s[j] === c) break;
        else v += s[j];
      }
      if (j >= s.length) return null;
      out.push({ t: 'str', v });
      i = j + 1;
    } else if (/[0-9.]/.test(c)) {
      const m = /^[0-9]*\.?[0-9]+/.exec(s.slice(i));
      if (!m) return null;
      out.push({ t: 'num', v: m[0] });
      i += m[0].length;
    } else if (/[A-Za-z_]/.test(c)) {
      const m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(s.slice(i))!;
      out.push({ t: 'name', v: m[0] });
      i += m[0].length;
    } else if ('(),'.includes(c)) {
      out.push({ t: c as '(' | ')' | ',', v: c });
      i++;
    } else {
      const m = /^(==|!=|<>|<=|>=|[-+*/%=<>])/.exec(s.slice(i));
      if (!m) return null; // { } for LOD expressions, and anything else
      out.push({ t: 'op', v: m[0] });
      i += m[0].length;
    }
  }
  return out;
}

const AGG: Record<string, string> = {
  SUM: 'SUM',
  AVG: 'AVG',
  MIN: 'MIN',
  MAX: 'MAX',
  MEDIAN: 'MEDIAN',
  COUNT: 'COUNT',
};
const PASS: Record<string, string> = {
  ABS: 'ABS',
  ROUND: 'ROUND',
  UPPER: 'UPPER',
  LOWER: 'LOWER',
  TRIM: 'TRIM',
  LEN: 'LENGTH',
};
const KEYWORDS: Record<string, string> = {
  IF: 'CASE WHEN',
  THEN: 'THEN',
  ELSEIF: 'WHEN',
  ELSE: 'ELSE',
  END: 'END',
  CASE: 'CASE',
  WHEN: 'WHEN',
  AND: 'AND',
  OR: 'OR',
  NOT: 'NOT',
  TRUE: 'TRUE',
  FALSE: 'FALSE',
  NULL: 'NULL',
};
const GRAINS = new Set(['year', 'quarter', 'month', 'week', 'day', 'hour', 'minute']);

export function translateTableau(formula: string, ctx: CalcContext): string | null {
  const parsed = tokenize(formula);
  if (!parsed?.length) return null;
  const toks: Tok[] = parsed;
  let i = 0;
  const fail = (): never => {
    throw new Error('no rule');
  };
  const args = (): string[] => {
    if (toks[i++]?.t !== '(') fail();
    const list: string[] = [];
    if (toks[i]?.t === ')') {
      i++;
      return list;
    }
    for (;;) {
      list.push(expr());
      const t = toks[i++];
      if (t?.t === ')') return list;
      if (t?.t !== ',') fail();
    }
  };
  const call = (name: string): string => {
    const n = name.toUpperCase();
    // DATETRUNC('month', [Date]): the first argument is a grain literal.
    if (n === 'DATETRUNC') {
      if (
        toks[i]?.t !== '(' ||
        toks[i + 1]?.t !== 'str' ||
        !GRAINS.has(toks[i + 1].v.toLowerCase()) ||
        toks[i + 2]?.t !== ','
      )
        fail();
      const grain = toks[i + 1].v.toUpperCase();
      i += 3;
      const e = expr();
      if (toks[i++]?.t !== ')') fail();
      return `DATE_TRUNC('${grain}', ${e})`;
    }
    const a = args();
    if (AGG[n] && a.length === 1) return `${AGG[n]}(${a[0]})`;
    if (n === 'COUNTD' && a.length === 1) return `COUNT(DISTINCT ${a[0]})`;
    if (PASS[n] && a.length >= 1 && a.length <= 2) return `${PASS[n]}(${a.join(', ')})`;
    if (n === 'ZN' && a.length === 1) return `COALESCE(${a[0]}, 0)`;
    if (n === 'ISNULL' && a.length === 1) return `(${a[0]} IS NULL)`;
    if (n === 'IFNULL' && a.length === 2) return `COALESCE(${a[0]}, ${a[1]})`;
    if (n === 'IIF' && (a.length === 3 || a.length === 4)) return `CASE WHEN ${a[0]} THEN ${a[1]} ELSE ${a[2]} END`;
    if (n === 'CONTAINS' && a.length === 2) return `(INSTR(${a[0]}, ${a[1]}) > 0)`;
    return fail();
  };
  function expr(): string {
    const parts: string[] = [];
    let depth = 0;
    while (i < toks.length) {
      const t = toks[i];
      if ((t.t === ')' || t.t === ',') && depth === 0) break;
      if (t.t === 'ref') {
        parts.push(ctx.field(t.v) ?? fail());
        i++;
      } else if (t.t === 'str') {
        parts.push(`'${t.v.replace(/'/g, "''")}'`);
        i++;
      } else if (t.t === 'num') {
        parts.push(t.v);
        i++;
      } else if (t.t === 'op') {
        parts.push(t.v === '==' ? '=' : t.v === '!=' ? '<>' : t.v);
        i++;
      } else if (t.t === '(') {
        i++;
        parts.push(`(${expr()})`);
        if (toks[i++]?.t !== ')') fail();
      } else if (t.t === 'name' && toks[i + 1]?.t === '(' && !KEYWORDS[t.v.toUpperCase()]) {
        i++;
        parts.push(call(t.v));
      } else if (t.t === 'name' && KEYWORDS[t.v.toUpperCase()]) {
        const k = t.v.toUpperCase();
        // IF ... END and CASE ... END hold THEN and ELSE parts, so they are read as one expression.
        if (k === 'IF' || k === 'CASE') depth++;
        if (k === 'END') depth--;
        if (depth < 0) fail();
        parts.push(KEYWORDS[k]);
        i++;
      } else fail();
    }
    if (!parts.length || depth !== 0) fail();
    return parts.join(' ').replace(/\( /g, '(').replace(/ \)/g, ')');
  }
  try {
    const sql = expr();
    return i === toks.length ? sql : null;
  } catch {
    return null;
  }
}

/** True when the SQL aggregates, so it can be a measure as it is. */
export const aggregates = (sql: string) => /\b(SUM|AVG|MIN|MAX|MEDIAN|COUNT|MEASURE)\(/.test(sql);
