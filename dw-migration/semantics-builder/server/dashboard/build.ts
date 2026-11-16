import type { MetricView } from '../../shared/metricView';

const MAX_KPIS = 3;
const TEXT = /^(string|varchar|char)/i;
const TIME = /^(date|timestamp)/i;

type Measure = MetricView['measures'][number];

/** The dashboard number format of a measure, from its metric view format. */
function formatOf(m: Measure) {
  const compact = { abbreviation: 'compact', decimalPlaces: { type: 'max', places: 2 } };
  if (m.format?.type === 'currency')
    return { type: 'number-currency', currencyCode: m.format.currency_code, ...compact };
  if (m.format?.type === 'percentage') return { type: 'number-percent', decimalPlaces: { type: 'max', places: 1 } };
  return { type: 'number', ...compact };
}

const field = (m: string) => ({ name: `measure(${m})`, expression: `MEASURE(\`${m.replace(/`/g, '``')}\`)` });
const dimField = (d: string) => ({ name: d, expression: `\`${d.replace(/`/g, '``')}\`` });
const monthly = (d: string) => ({
  name: `monthly(${d})`,
  expression: `DATE_TRUNC("MONTH", \`${d.replace(/`/g, '``')}\`)`,
});
const query = (fields: object[]) => [
  { name: 'main_query', query: { datasetName: 'ds_view', fields, disaggregated: false } },
];
const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '') || 'x';

export interface DashboardPlan {
  json: string;
  kpis: string[];
  trend: string | null;
  breakdown: string | null;
}

/**
 * A starter AI/BI dashboard on a promoted metric view: KPI counters for the first measures (with a monthly
 * sparkline), a monthly trend of the first measure, and the first measure by the first text dimension. The dataset
 * is the metric view itself, so every number comes from its governed measures. Window measures are left out: they
 * need their own time field to be correct.
 */
export function starterDashboard(
  title: string,
  view: string,
  mv: MetricView,
  /** The column types of the promoted view, by name. */
  types: Map<string, string>
): DashboardPlan {
  const measures = mv.measures.filter((m) => !m.window);
  const kpis = measures.slice(0, MAX_KPIS);
  const time = mv.dimensions.find((d) => TIME.test(types.get(d.name) ?? ''))?.name ?? null;
  const top = mv.dimensions.find((d) => TEXT.test(types.get(d.name) ?? ''))?.name ?? null;
  const main = kpis[0];
  const layout: object[] = [
    {
      widget: {
        name: 'title',
        multilineTextboxSpec: {
          lines: [`## ${title}\n`, '\n', `From the metric view ${view}. A starter draft: review it, then publish it.`],
        },
      },
      position: { x: 0, y: 0, width: 12, height: 2 },
    },
  ];
  const width = kpis.length ? 12 / kpis.length : 12;
  kpis.forEach((m, i) => {
    layout.push({
      widget: {
        name: `kpi-${i}-${slug(m.name)}`,
        queries: query([field(m.name), ...(time ? [monthly(time)] : [])]),
        spec: {
          version: 2,
          widgetType: 'counter',
          encodings: {
            value: { fieldName: `measure(${m.name})`, displayName: m.display_name ?? m.name, format: formatOf(m) },
            ...(time ? { period: { fieldName: `monthly(${time})` } } : {}),
          },
          frame: { showTitle: true, title: m.display_name ?? m.name },
        },
      },
      position: { x: i * width, y: 2, width, height: 3 },
    });
  });
  const charts: object[] = [];
  if (main && time)
    charts.push({
      name: `trend-${slug(main.name)}`,
      queries: query([monthly(time), field(main.name)]),
      spec: {
        version: 3,
        widgetType: 'line',
        encodings: {
          x: { fieldName: `monthly(${time})`, scale: { type: 'temporal' }, displayName: time },
          y: {
            fieldName: `measure(${main.name})`,
            scale: { type: 'quantitative' },
            displayName: main.display_name ?? main.name,
          },
        },
        frame: { showTitle: true, title: `${main.display_name ?? main.name} by month` },
      },
    });
  if (main && top)
    charts.push({
      name: `by-${slug(top)}`,
      queries: query([dimField(top), field(main.name)]),
      spec: {
        version: 3,
        widgetType: 'bar',
        encodings: {
          x: { fieldName: top, scale: { type: 'categorical' }, displayName: top },
          y: {
            fieldName: `measure(${main.name})`,
            scale: { type: 'quantitative' },
            displayName: main.display_name ?? main.name,
          },
        },
        frame: { showTitle: true, title: `${main.display_name ?? main.name} by ${top}` },
      },
    });
  charts.forEach((widget, i) =>
    layout.push({ widget, position: { x: i * (12 / charts.length), y: 5, width: 12 / charts.length, height: 6 } })
  );
  const dashboard = {
    datasets: [{ name: 'ds_view', displayName: title, asset_name: view }],
    pages: [
      { name: 'overview', displayName: 'Overview', pageType: 'PAGE_TYPE_CANVAS', layoutVersion: 'GRID_V1', layout },
    ],
  };
  return {
    json: JSON.stringify(dashboard, null, 2),
    kpis: kpis.map((m) => m.name),
    trend: main && time ? time : null,
    breakdown: main && top ? top : null,
  };
}
