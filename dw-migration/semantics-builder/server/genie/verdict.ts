import type { GenieExpected, GenieVerdict } from '../../shared/genie';

const flat = (s: string) => s.toLowerCase().replace(/[`"]/g, '').trim();

/** The view's measures and dimensions that a Genie query names. Measures count only inside MEASURE(). */
export function fieldsUsed(sql: string, view: { measures: string[]; dimensions: string[] }) {
  const inMeasure = [...sql.matchAll(/MEASURE\s*\(\s*(`[^`]+`|[\w.]+)\s*\)/gi)].map((m) => flat(m[1] ?? ''));
  const rest = flat(sql.replace(/MEASURE\s*\(\s*(`[^`]+`|[\w.]+)\s*\)/gi, ' '));
  const named = (n: string) => {
    const f = flat(n);
    return new RegExp(`(^|[^a-z0-9_])${f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^a-z0-9_])`).test(rest);
  };
  return {
    measures: view.measures.filter((m) => inMeasure.includes(flat(m))),
    dimensions: view.dimensions.filter(named),
  };
}

/** Compares the fields of Genie's SQL with the fields the user expects for the question. */
export function verdictOf(
  sql: string | null,
  view: { measures: string[]; dimensions: string[] },
  expected: GenieExpected | null
): { verdict: GenieVerdict; detail: string } {
  if (!sql) return { verdict: 'no_answer', detail: 'Genie did not run a query.' };
  const used = fieldsUsed(sql, view);
  const uses = `Uses ${used.measures.join(', ') || 'no measure'}${used.dimensions.length ? ` by ${used.dimensions.join(', ')}` : ''}.`;
  if (!expected) return { verdict: 'needs_review', detail: uses };
  const missing = [
    ...expected.measures.filter((m) => !used.measures.includes(m)).map((m) => `measure ${m}`),
    ...expected.dimensions.filter((d) => !used.dimensions.includes(d)).map((d) => `dimension ${d}`),
  ];
  return missing.length
    ? { verdict: 'different', detail: `Missing ${missing.join(', ')}. ${uses}` }
    : { verdict: 'matches', detail: uses };
}
