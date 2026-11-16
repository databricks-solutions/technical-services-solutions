import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { checkStatement } from '../sql/allowlist';
import { biQuery } from './bi';

const view = validateMetricView(`version: "1.1"
source: main.sales.orders
dimensions:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', order_date)
measures:
  - name: Prior Revenue
    expr: SUM(amount)
    window:
      - order: Order Month
        range: trailing 1 month
        semiadditive: last
  - name: Revenue
    expr: SUM(amount)
`).view!;

describe('biQuery', () => {
  it('uses a plain measure and the first dimension, in the shape BI tools send', () => {
    const q = biQuery('main.gold.sales', view)!;
    expect(q.measure).toBe('Revenue');
    expect(q.sql).toBe(
      'SELECT `Order Month`, MEASURE(`Revenue`) AS `Revenue`\nFROM `main`.`gold`.`sales`\nGROUP BY `Order Month`'
    );
    expect(checkStatement(`${q.sql}\nLIMIT 100`).kind).toBe('read');
  });
});
