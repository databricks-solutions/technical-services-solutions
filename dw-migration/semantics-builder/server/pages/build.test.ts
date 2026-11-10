import { describe, expect, it } from 'vitest';
import type { DictionaryEntry } from '../../shared/dictionary';
import { assetOf, clip, pageMarkdown, pagesBundle, piiWarnings } from '../../shared/pages';
import { validateMetricView } from '../../shared/metricView';
import { buildPages } from './build';

const view = validateMetricView(`version: 1.1
comment: Order revenue for sales leadership.
source: main.sales.orders
dimensions:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', order_date)
measures:
  - name: Net Revenue
    expr: SUM(amount - discount)
    comment: Revenue after discounts.
`).view!;

const entry = (e: Partial<DictionaryEntry>): DictionaryEntry => ({
  kind: 'metric',
  name: 'Net Revenue',
  definition: 'Revenue after discounts, before tax.',
  synonyms: ['net sales'],
  status: 'certified',
  notes: {},
  ...e,
});

const base = {
  project: 'Orders',
  subProject: 'Revenue',
  brief: {
    version: 2,
    brief: {
      title: 'Order revenue',
      businessGoal: 'One view of revenue.',
      audience: [],
      keyQuestions: ['What is net revenue by month?'],
      measures: [],
      dimensions: [],
      timeGrains: [],
      candidateSources: [],
      glossary: [
        { term: 'Net revenue', definition: 'Duplicate of the dictionary entry.' },
        { term: 'Backorder', definition: 'An order line that waits for stock.' },
      ],
      assumptions: [],
      openQuestions: [],
    },
  },
  dictionary: [entry({ formula: 'SUM(amount - discount)' }), entry({ name: 'Draft KPI', status: 'draft' })],
  dictionaryFile: 'dictionary.xlsx',
  view,
  target: 'main.sales.order_metrics',
  sourceTables: ['main.sales.orders'],
  includeEntity: true,
};

describe('buildPages', () => {
  it('makes Pages from certified entries, the glossary and the metric view', () => {
    const pages = buildPages(base);
    expect(pages.map((p) => [p.key, p.kind, p.title])).toEqual([
      ['metric:netrevenue', 'metric', 'Net Revenue'],
      ['term:backorder', 'term', 'Backorder'],
      ['entity:view', 'entity', 'Order revenue'],
    ]);
    const metric = pages[0];
    expect(metric.synonyms).toEqual(['net sales']);
    expect(metric.relatedAssets).toEqual(['main.sales.order_metrics']);
    expect(metric.body).toContain('`SUM(amount - discount)`');
    expect(metric.body).toContain('the measure `Net Revenue`');
    expect(pages[2].body).toContain('What is net revenue by month?');
    expect(pages[2].relatedAssets).toEqual(['main.sales.order_metrics', 'main.sales.orders']);
  });
  it('leaves the entity Page out on request, and works before publishing', () => {
    const pages = buildPages({ ...base, includeEntity: false, target: null });
    expect(pages.some((p) => p.kind === 'entity')).toBe(false);
    expect(pages[0].relatedAssets).toEqual([]);
  });
});

describe('Markdown and PII', () => {
  it('labels each Page field and bundles only included Pages', () => {
    const pages = buildPages(base);
    expect(pageMarkdown(pages[1], 'Sales')).toContain('- **Domain:** Sales');
    const bundle = pagesBundle({ domain: 'Sales', pages: pages.map((p, i) => ({ ...p, include: i !== 1 })) }, 'Orders');
    expect(bundle.match(/^# /gm)).toHaveLength(2);
    expect(bundle).not.toContain('# Backorder');
  });
  it('writes only the fields a Page has, and puts the sources in the body', () => {
    const md = pageMarkdown(
      { ...buildPages(base)[0], relatedAssets: ['main.sales.orders.amount'], sources: ['Dictionary (d.xlsx)'] },
      'Sales'
    );
    expect(md).not.toContain('**Type:**');
    expect(md).not.toContain('**Sources:**');
    expect(md).toContain('- **Related assets:** `main.sales.orders`');
    expect(md).toMatch(/## Sources\n\n- Dictionary \(d\.xlsx\)/);
  });
  it('clips a description to 160 characters at a word boundary', () => {
    const c = clip('word '.repeat(60));
    expect(c.length).toBeLessThanOrEqual(160);
    expect(c.endsWith('word...')).toBe(true);
    expect(clip('short')).toBe('short');
    expect(assetOf('a.b.c')).toBe('a.b.c');
  });
  it('warns on personal data', () => {
    expect(piiWarnings({ title: 'x', synonyms: [], description: 'Ask jane@example.com', body: '' })).toEqual([
      'It may contain an email address.',
    ]);
    expect(piiWarnings({ title: 'Net revenue', synonyms: [], description: 'SUM(amount)', body: '' })).toEqual([]);
  });
});
