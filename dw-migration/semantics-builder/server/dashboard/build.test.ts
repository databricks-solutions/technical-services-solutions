import { describe, expect, it } from 'vitest';
import type { MetricView } from '../../shared/metricView';
import { starterDashboard } from './build';

const mv = {
  version: '1.1',
  source: 'c.s.orders',
  dimensions: [
    { name: 'Order Month', expr: "DATE_TRUNC('MONTH', o_orderdate)" },
    { name: 'Region', expr: 'r_name' },
  ],
  measures: [
    { name: 'Net Revenue', expr: 'SUM(x)', format: { type: 'currency', currency_code: 'USD' } },
    {
      name: 'Prior Year',
      expr: 'MEASURE(`Net Revenue`)',
      window: [{ order: 'Order Month', range: 'trailing 1 year' }],
    },
    { name: 'Order Count', expr: 'COUNT(1)' },
  ],
} as MetricView;
const types = new Map([
  ['Order Month', 'timestamp'],
  ['Region', 'string'],
]);

describe('starterDashboard', () => {
  it('builds KPIs, a monthly trend and a breakdown on the metric view, with no window measure', () => {
    const plan = starterDashboard('Net revenue', 'c.s.v', mv, types);
    expect(plan).toMatchObject({ kpis: ['Net Revenue', 'Order Count'], trend: 'Order Month', breakdown: 'Region' });
    const d = JSON.parse(plan.json) as {
      datasets: { asset_name: string }[];
      pages: {
        layoutVersion: string;
        layout: {
          widget: { spec?: { widgetType: string; version: number } };
          position: { x: number; width: number; y: number };
        }[];
      }[];
    };
    expect(d.datasets).toEqual([{ name: 'ds_view', displayName: 'Net revenue', asset_name: 'c.s.v' }]);
    const layout = d.pages[0].layout;
    expect(layout.map((w) => w.widget.spec?.widgetType ?? 'text')).toEqual([
      'text',
      'counter',
      'counter',
      'line',
      'bar',
    ]);
    expect(
      layout.filter((w) => w.widget.spec?.widgetType === 'counter').every((w) => w.widget.spec!.version === 2)
    ).toBe(true);
    // Each row fills the 12 columns.
    for (const y of new Set(layout.map((w) => w.position.y)))
      expect(layout.filter((w) => w.position.y === y).reduce((n, w) => n + w.position.width, 0)).toBe(12);
    expect(plan.json).toContain('"currencyCode": "USD"');
    expect(plan.json).not.toContain('Prior Year');
  });
});

describe('dashboardCommand', () => {
  it('quotes the JSON and the folder for the shell, and checks the folder', async () => {
    const { dashboardCommand, validFolder } = await import('../../shared/dashboard');
    const cmd = dashboardCommand("Bob's - starter", 'wh1', '/Users/a@x.com', '{"a":"it\'s"}');
    expect(cmd).toContain(`--display-name 'Bob'\\''s - starter'`);
    expect(cmd).toContain(`--serialized-dashboard '{"a":"it'\\''s"}'`);
    expect(cmd).toContain(`--json '{"parent_path":"/Users/a@x.com"}'`);
    expect(validFolder('/Users/a@x.com/dash')).toBe(true);
    expect(validFolder('/Users/a/../b')).toBe(false);
    expect(validFolder('/tmp')).toBe(false);
  });
});
