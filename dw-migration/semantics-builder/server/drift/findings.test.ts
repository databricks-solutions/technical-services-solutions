import { describe, expect, it } from 'vitest';
import type { TableProfile } from '../readiness/profile';
import { driftFindings } from './findings';

const yaml = `version: 1.1
source: c.s.orders
joins:
  - name: dim_customer
    source: c.s.customer
    "on": source.o_custkey = dim_customer.c_custkey
dimensions:
  - name: Region
    expr: dim_customer.c_region
measures:
  - name: Revenue
    expr: SUM(source.o_total)
`;
const t = (fullName: string, cols: [string, string][]): TableProfile => ({
  fullName,
  comment: '',
  columns: cols.map(([name, type]) => ({ name, type, comment: '' })),
  primaryKey: [],
  foreignKeys: [],
});
const orders = t('c.s.orders', [
  ['o_custkey', 'bigint'],
  ['o_total', 'decimal(18,2)'],
]);
const customer = t('c.s.customer', [
  ['c_custkey', 'bigint'],
  ['c_region', 'string'],
]);
const base = {
  target: 'main.m.v',
  promotedYaml: yaml,
  ucYaml: yaml,
  sources: [
    { fullName: 'c.s.orders', profile: orders },
    { fullName: 'c.s.customer', profile: customer },
  ],
  owner: 'me@x.com',
  grants: ['analysts:SELECT'],
  restricted: [],
  materialized: false,
  refreshStatus: null,
  totals: null,
  baseline: null,
  previous: null,
};

describe('driftFindings', () => {
  it('reports no drift and keeps a snapshot', () => {
    const out = driftFindings(base);
    expect(out.findings.map((f) => f.severity)).toEqual(['info']);
    expect(out.snapshot.columns['c.s.orders']).toEqual({ o_custkey: 'bigint', o_total: 'decimal(18,2)' });
  });

  it('finds schema, definition, governance, usage and data drift', () => {
    const changed = t('c.s.customer', [['c_custkey', 'string']]);
    const out = driftFindings({
      ...base,
      ucYaml: yaml.replace('SUM(source.o_total)', 'SUM(source.o_total) * 2'),
      sources: [
        { fullName: 'c.s.orders', profile: orders },
        { fullName: 'c.s.customer', profile: changed },
      ],
      owner: 'other@x.com',
      grants: [],
      restricted: ['c.s.orders'],
      materialized: true,
      refreshStatus: 'FAILED',
      totals: { Revenue: 150 },
      baseline: { Revenue: 100 },
      previous: driftFindings(base).snapshot,
    });
    const kinds = out.findings.map((f) => `${f.kind}:${f.severity}`);
    expect(kinds).toContain('definition:warning');
    expect(kinds).toContain('schema:error');
    expect(kinds).toContain('schema:warning');
    expect(kinds).toContain('governance:warning');
    expect(kinds).toContain('governance:error');
    expect(kinds).toContain('usage:error');
    expect(kinds).toContain('data:warning');
    expect(out.findings.find((f) => f.kind === 'data')?.detail).toMatch(/50%/);
    expect(out.findings[0]?.severity).toBe('error');
  });

  it('reports a missing view and an unreadable source as errors', () => {
    const out = driftFindings({ ...base, ucYaml: null, sources: [{ fullName: 'c.s.orders', error: 'denied' }] });
    expect(out.findings.filter((f) => f.severity === 'error').map((f) => f.kind)).toEqual(['definition', 'schema']);
  });
});

describe('totalsQuery', () => {
  it('reads one row of totals for the plain measures, quoted', async () => {
    const { totalsQuery } = await import('../api/drift');
    const { validateMetricView } = await import('../../shared/metricView');
    const q = totalsQuery('main.m.v', validateMetricView(yaml).view!);
    expect(q).toEqual({ sql: 'SELECT MEASURE(`Revenue`) AS m0 FROM `main`.`m`.`v`', names: ['Revenue'] });
   }, 30_000);
});
