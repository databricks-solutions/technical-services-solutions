import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { readZipEntry } from '../legacy/zip';
import { bundleFiles, testStatement } from './build';
import { writeZip } from './zip';

const yaml = `version: "1.1"
source: main.sales.orders
dimensions:
  - name: Region
    expr: region
measures:
  - name: Revenue
    expr: SUM(amount)
`;
const input = {
  target: 'main.gold.sales_metrics',
  yaml,
  view: validateMetricView(yaml).view!,
  version: 4,
  project: 'Sales',
  subProject: "O'Brien revenue",
  tests: [
    { name: 'Revenue by region', measures: ['Revenue'], dimensions: ['Region'] },
    {
      name: 'EMEA 2024',
      measures: ['Revenue'],
      dimensions: [],
      expect: { value: 1200, tolerancePct: 0.5, filters: [{ dimension: 'Region', value: "O'Hare" }] },
    },
  ],
};

describe('bundleFiles', () => {
  const files = bundleFiles(input);
  it('has a bundle, two jobs and the SQL files', () => {
    expect(Object.keys(files).sort()).toEqual([
      'README.md',
      'databricks.yml',
      'resources/sales_metrics_deploy.job.yml',
      'resources/sales_metrics_nightly_check.job.yml',
      'src/create_view.sql',
      'src/drift.sql',
      'src/tests.sql',
    ]);
    expect(files['databricks.yml']).toContain('name: sales_metrics_metric_view');
    expect(files['resources/sales_metrics_nightly_check.job.yml']).toContain("quartz_cron_expression: '0 0 2 * * ?'");
    expect(files['src/create_view.sql']).toContain('CREATE OR REPLACE VIEW `main`.`gold`.`sales_metrics` WITH METRICS');
    expect(files['src/drift.sql']).toContain("= 'region,revenue'");
  });
  it('asserts an expected value with its tolerance, and quotes the values', () => {
    expect(testStatement(input.target, input.tests[1])).toContain(
      "SELECT assert_true(abs(MEASURE(`Revenue`) - 1200) <= abs(1200) * 0.5 / 100, 'Test \"EMEA 2024\": Revenue is outside 0.5% of the expected value.') FROM `main`.`gold`.`sales_metrics` WHERE `Region` = 'O\\'Hare';"
    );
  });
  it('makes a zip that reads back', () => {
    const zip = writeZip(files);
    expect(readZipEntry(zip, (n) => n === 'src/tests.sql')?.toString('utf8')).toBe(files['src/tests.sql']);
  });
});
