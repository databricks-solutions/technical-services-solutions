import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { fieldUsageQuery, toFieldUsage } from './usage';

const view = validateMetricView(`version: "1.1"
source: main.sales.orders
dimensions:
  - name: Region
    expr: region
  - name: Channel
    expr: channel
measures:
  - name: Revenue
    expr: SUM(amount)
  - name: Orders
    expr: COUNT(1)
  - name: Average Order
    expr: MEASURE(Revenue) / MEASURE(\`Orders\`)
`).view!;

describe('usage', () => {
  it('reads lineage for the view only, with counts', () => {
    const q = fieldUsageQuery('Main.Gold.Sales', 30);
    expect(q).toContain("l.source_table_full_name = 'main.gold.sales'");
    expect(q).toContain('INTERVAL 30 DAYS');
    expect(q).not.toMatch(/statement_text|created_by AS/);
  });
  it('lists every field, unused ones with 0, and the measures that other measures use', () => {
    const u = toFieldUsage(view, [
      ['revenue', '12', '3', '2026-11-10T00:00:00Z'],
      ['region', '4', '2', '2026-11-09T00:00:00Z'],
    ]);
    expect(u.map((f) => [f.name, f.queries])).toEqual([
      ['Revenue', 12],
      ['Region', 4],
      ['Average Order', 0],
      ['Channel', 0],
      ['Orders', 0],
    ]);
    expect(u.find((f) => f.name === 'Orders')?.usedBy).toEqual(['Average Order']);
    expect(u.find((f) => f.name === 'Channel')?.usedBy).toEqual([]);
  });
});
