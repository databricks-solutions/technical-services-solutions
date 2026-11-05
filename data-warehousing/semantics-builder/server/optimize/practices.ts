import type { MetricView } from '../../shared/metricView';
import type { PracticeCheck } from '../../shared/optimize';

const MONEY = /revenue|sales|price|amount|cost|profit|margin value|spend|value|balance|fee/i;
const DATE = /\bDATE_TRUNC\s*\(|date|month|quarter|year|week|day\b/i;
const KEY_COLUMN = /(?:^|[._])(?:\w*key|\w*_id|id|uuid|comment|description)\s*$/i;
const NON_ADDITIVE = /COUNT\s*\(\s*DISTINCT|PERCENTILE|MEDIAN|APPROX_COUNT_DISTINCT|COUNT_IF\s*\(\s*DISTINCT/i;
const isRatio = (expr: string) => /\//.test(expr.replace(/'[^']*'/g, ''));

const check = (
  id: string,
  title: string,
  why: string,
  severity: PracticeCheck['severity'],
  fields: string[],
  instruction: ((fields: string[]) => string) | null
): PracticeCheck => ({
  id,
  title,
  why,
  severity,
  fields,
  instruction: instruction && fields.length ? instruction(fields) : null,
});

/** Rule-based review of a metric view for Genie, dashboards and certification. No model call. */
export function bestPractices(view: MetricView): PracticeCheck[] {
  const fields = [...view.measures, ...view.dimensions];
  // The refine endpoint takes 2,000 characters, so long lists are cut.
  const list = (names: string[]) =>
    names
      .slice(0, 12)
      .map((n) => `"${n}"`)
      .join(', ') + (names.length > 12 ? ` and ${names.length - 12} more` : '');
  return [
    check(
      'view_comment',
      'The view has a description',
      'Genie and Catalog Explorer show it to explain what the view is for.',
      'fix',
      view.comment?.trim() ? [] : ['(view)'],
      () => 'Add a top-level comment that says what the metric view covers, its grain and its main source.'
    ),
    check(
      'comments',
      'Every measure and dimension has a description',
      'Descriptions are the business definition. Genie uses them to pick the right field.',
      'fix',
      fields.filter((f) => !f.comment?.trim()).map((f) => f.name),
      (names) =>
        `Add a one-sentence business comment to ${list(names)}. Say what each one means, not how it is computed.`
    ),
    check(
      'genie_names',
      'Measures have synonyms and a display name',
      'Synonyms match the words users type in Genie; display names show in charts.',
      'improve',
      view.measures.filter((m) => !m.synonyms?.length || !m.display_name?.trim()).map((m) => m.name),
      (names) =>
        `Add display_name and two to five business synonyms to the measures ${list(names)}. Keep the names unchanged.`
    ),
    check(
      'formats',
      'Money, ratios and dates have a format',
      'A format makes values readable in Genie and dashboards: currency, percentage or date.',
      'improve',
      [
        ...view.measures.filter((m) => !m.format && (MONEY.test(m.name) || isRatio(m.expr))).map((m) => m.name),
        ...view.dimensions.filter((d) => !d.format && DATE.test(`${d.name} ${d.expr}`)).map((d) => d.name),
      ],
      (names) =>
        `Add a format to ${list(names)}: currency (with currency_code) for money, percentage for ratios and rates, date for date dimensions. Change nothing else.`
    ),
    check(
      'safe_ratio',
      'Ratios cannot divide by zero',
      'A ratio without NULLIF fails or returns infinity when the divisor is 0.',
      'fix',
      view.measures.filter((m) => isRatio(m.expr) && !/NULLIF\s*\(|TRY_DIVIDE\s*\(/i.test(m.expr)).map((m) => m.name),
      (names) => `Wrap the divisor of ${list(names)} in NULLIF(<divisor>, 0). Keep the meaning unchanged.`
    ),
    check(
      'high_cardinality',
      'Dimensions are business attributes, not keys or free text',
      'Keys and comments have a value per row: they make groupings huge and materializations large.',
      'improve',
      view.dimensions.filter((d) => KEY_COLUMN.test(d.expr.trim())).map((d) => d.name),
      (names) =>
        `Replace the dimensions ${list(names)} with descriptive attributes from the joined tables (names, categories), or remove them if a measure already counts them.`
    ),
    check(
      'non_additive',
      'Non-additive measures are known',
      'Distinct counts and percentiles cannot be summed or rolled up. Materializations must group by exactly the queried dimensions.',
      'info',
      view.measures.filter((m) => NON_ADDITIVE.test(m.expr)).map((m) => m.name),
      null
    ),
  ];
}
