import { describe, expect, it } from 'vitest';
import { translateDax } from './dax';

const ctx = {
  column: (t: string, c: string) =>
    (
      ({
        'Sales.Amount': 'amount',
        'Sales.Qty': 'qty',
        'Sales.Status': 'status',
        'Customer.Segment': 'customer.segment',
      }) as Record<string, string>
    )[`${t}.${c}`] ?? null,
  measure: (n: string) => ['Total Sales', 'Orders'].includes(n),
  table: (n: string) => n === 'Sales',
};
const t = (dax: string) => translateDax(dax, ctx);

describe('translateDax', () => {
  it('translates the common forms', () => {
    expect(t('SUM(Sales[Amount])')).toBe('SUM(amount)');
    expect(t("SUM('Sales'[Amount]) // total")).toBe('SUM(amount)');
    expect(t('DISTINCTCOUNT(Sales[Qty])')).toBe('COUNT(DISTINCT qty)');
    expect(t('COUNTROWS(Sales)')).toBe('COUNT(1)');
    expect(t('DIVIDE([Total Sales], [Orders])')).toBe('MEASURE(`Total Sales`) / NULLIF(MEASURE(`Orders`), 0)');
    expect(t('DIVIDE([Total Sales], [Orders], 0)')).toBe(
      'COALESCE(MEASURE(`Total Sales`) / NULLIF(MEASURE(`Orders`), 0), 0)'
    );
    expect(t('[Total Sales] - [Orders] * 2')).toBe('MEASURE(`Total Sales`) - MEASURE(`Orders`) * 2');
    expect(t('CALCULATE(SUM(Sales[Amount]), Sales[Status] = "Done")')).toBe(
      "SUM(amount) FILTER (WHERE status = 'Done')"
    );
    expect(t('CALCULATE(SUM(Sales[Amount]), Sales[Status] = "A", Customer[Segment] <> "B")')).toBe(
      "SUM(amount) FILTER (WHERE (status = 'A') AND (customer.segment <> 'B'))"
    );
    expect(t('IF([Orders] > 0, [Total Sales], BLANK())')).toBe(
      'CASE WHEN MEASURE(`Orders`) > 0 THEN MEASURE(`Total Sales`) ELSE NULL END'
    );
  });

  it('returns null for forms with no rule, and for unknown names', () => {
    expect(t('SUMX(Sales, Sales[Amount] * Sales[Qty])')).toBeNull();
    expect(t('VAR x = 1 RETURN x')).toBeNull();
    expect(t('CALCULATE([Total Sales], ALL(Sales))')).toBeNull();
    expect(t('CALCULATE(SUM(Sales[Amount]) / SUM(Sales[Qty]), Sales[Status] = "A")')).toBeNull();
    expect(t('SUM(Sales[Profit])')).toBeNull();
    expect(t('[Unknown]')).toBeNull();
    expect(t('TOTALYTD([Total Sales], Sales[Date])')).toBeNull();
  });
});
