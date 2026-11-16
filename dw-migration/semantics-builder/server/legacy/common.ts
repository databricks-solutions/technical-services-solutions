import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField, LegacyPreview } from '../../shared/legacy';
import { renderMetricView, validateMetricView } from '../../shared/metricView';
import type { MetricView } from '../../shared/metricView';

/** The result of every legacy converter: the preview, the view, and a note for each field. */
export interface LegacyResult {
  preview: LegacyPreview;
  view: MetricView | null;
  explanations: Explanations;
}

/** A converter whose hard expressions can go to the AI: the ones with no rule, and what the AI may use. */
export interface AiResult extends LegacyResult {
  todo: { name: string; dax: string }[];
  catalog: { columns: { table: string; column: string; sql: string }[]; measures: string[] };
}

/** order_total -> Order Total. Legacy names are often snake case; metric view names are for people. */
export const human = (s: string) =>
  s
    .replace(/_+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();

export const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const quote = (s: string) => `\`${s.replace(/`/g, '``')}\``;

/** Unique field names: a second "Revenue" becomes "Revenue 2". */
export function namer() {
  const names = new Set<string>();
  return (n: string) => {
    let name = n.slice(0, 255);
    for (let i = 2; names.has(name.toLowerCase()); i++) name = `${n.slice(0, 250)} ${i}`;
    names.add(name.toLowerCase());
    return name;
  };
}

export const noteOf = (tool: string, status: FieldStatus, text: string) =>
  `From ${tool} (${status === 'converted' ? 'converted' : status === 'review' ? 'converted, check it' : 'not converted'}): ${text}`;

/** The summary, the YAML and its errors as issues, for any converter. */
export function finish(
  format: LegacyPreview['format'],
  tool: string,
  fileName: string,
  view: MetricView,
  fields: LegacyField[],
  sources: string[],
  issues: string[],
  explanations: Explanations
): LegacyResult {
  const counts = (s: FieldStatus) => fields.filter((f) => f.status === s).length;
  explanations.summary = `Imported from ${tool} (${fileName}): ${counts('converted')} converted, ${counts('review')} to check, ${counts('manual')} not converted.`;
  if (!view.measures.length) issues.push('No measure could be converted, so there is no draft.');
  const yaml = view.measures.length ? renderMetricView(view) : null;
  if (yaml)
    for (const i of validateMetricView(yaml).issues.filter((x) => x.severity === 'error')) issues.push(i.message);
  return { preview: { format, yaml, fields, sources, issues }, view: yaml ? view : null, explanations };
}
