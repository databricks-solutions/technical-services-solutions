import { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  FormUI,
  Input,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { ProjectDetail } from '../../../shared/brief';
import type { TestCase } from '../../../shared/designer';
import type { MetricView } from '../../../shared/metricView';
import {
  autoMap,
  MAX_RECONCILE_DIMENSIONS,
  MAX_RECONCILE_MEASURES,
  MAX_RECONCILE_ROWS,
  parseCsv,
  parseNumber,
  reconcileTests,
} from '../../../shared/reconcile';
import type { ReconcileBody, ReconcileResult, ReconcileStatus } from '../../../shared/reconcile';
import { api, useResource } from '../api';
import { SqlBlock } from './SqlBlock';

const STATUS: Record<ReconcileStatus, { color: 'teal' | 'coral' | 'lemon' | 'charcoal'; label: string }> = {
  passed: { color: 'teal', label: 'Passed' },
  failed: { color: 'coral', label: 'Failed' },
  missing: { color: 'lemon', label: 'Not in the view' },
  skipped: { color: 'charcoal', label: 'No value' },
};
const MAX_TESTS = 20;
const fmt = (n: number | null) => (n === null ? '' : n.toLocaleString(undefined, { maximumFractionDigits: 4 }));

/**
 * Reconcile a legacy report with the sandbox view of a validated version. The CSV is read in the browser; the
 * server runs the same grouping as you and returns each row with the difference. Nothing is stored.
 */
export function ReconcilePanel({
  projectId,
  version,
  view,
  validated,
  tests,
  saving,
  onAddTests,
}: {
  projectId: string;
  version: number;
  view: MetricView;
  validated: boolean;
  tests: TestCase[];
  saving: boolean;
  onAddTests: (tests: TestCase[]) => void;
}) {
  const fields = useMemo(
    () => ({ dimensions: view.dimensions.map((d) => d.name), measures: view.measures.map((m) => m.name) }),
    [view]
  );
  const [text, setText] = useState('');
  const [mapping, setMapping] = useState<string[]>([]);
  const [tolerance, setTolerance] = useState('1');
  const [result, setResult] = useState<{ body: ReconcileBody; out: ReconcileResult }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const csv = useMemo(() => parseCsv(text), [text]);
  // A new version needs a confirmed brief; an import leaves the brief as a draft.
  const detail = useResource<ProjectDetail>(`/api/projects/${projectId}`);
  const confirmed = !detail.data || detail.data.brief?.status === 'confirmed';

  const load = (t: string) => {
    setText(t);
    setResult(undefined);
    setError(undefined);
    setMapping(autoMap(parseCsv(t).header, fields).map((m) => (m ? `${m.kind}:${m.name}` : '')));
  };

  /** The request from the CSV and the mapping, or the first problem. */
  const build = (): ReconcileBody | string => {
    const cols = mapping.map((m, i) => ({ i, kind: m.split(':')[0], name: m.slice(m.indexOf(':') + 1) }));
    const dims = cols.filter((c) => c.kind === 'dimension');
    const measures = cols.filter((c) => c.kind === 'measure');
    const tol = Number(tolerance);
    if (!measures.length) return 'Map at least one column to a measure.';
    if (dims.length > MAX_RECONCILE_DIMENSIONS) return `Map at most ${MAX_RECONCILE_DIMENSIONS} dimension columns.`;
    if (measures.length > MAX_RECONCILE_MEASURES) return `Map at most ${MAX_RECONCILE_MEASURES} measure columns.`;
    const names = [...dims, ...measures].map((c) => c.name);
    if (new Set(names).size !== names.length) return 'Two columns map to the same field.';
    if (!Number.isFinite(tol) || tol < 0 || tol > 100) return 'The tolerance is a percent from 0 to 100.';
    if (!csv.rows.length) return 'The CSV has no rows under its header.';
    if (csv.rows.length > MAX_RECONCILE_ROWS) return `The CSV has more than ${MAX_RECONCILE_ROWS} rows.`;
    if (!dims.length && csv.rows.length > 1)
      return 'With no dimension column, the report has one row: the totals. Map a dimension column.';
    const rows: ReconcileBody['rows'] = [];
    for (const [r, row] of csv.rows.entries()) {
      const values: (number | null)[] = [];
      for (const c of measures) {
        const v = parseNumber(row[c.i] ?? '', csv.delimiter);
        if (v !== null && Number.isNaN(v))
          return `Row ${r + 2}, column ${csv.header[c.i]}: "${row[c.i]}" is not a number.`;
        values.push(v);
      }
      rows.push({ keys: dims.map((c) => row[c.i] ?? ''), values });
    }
    return { dimensions: dims.map((c) => c.name), measures: measures.map((c) => c.name), rows, tolerancePct: tol };
  };

  const run = () => {
    const body = build();
    if (typeof body === 'string') return setError(body);
    setBusy(true);
    setError(undefined);
    api<ReconcileResult>(`/api/projects/${projectId}/designs/${version}/reconcile`, body).then(
      (out) => {
        setBusy(false);
        setResult({ body, out });
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  const newTests = result
    ? reconcileTests(result.out, result.body.dimensions, result.body.tolerancePct, tests, MAX_TESTS)
    : [];
  const passing = result?.out.counts.passed ?? 0;

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 16 }}>
      <Typography.Text color="secondary">
        Compare the numbers of a legacy report with this version. Paste or load a CSV export of the report, with a
        header row: dimension columns (such as region or month) and measure columns. The app runs the same grouping on
        the sandbox view, as you, and shows each row with the difference. The values show here only; the app does not
        store them. A total with no dimension column is one row. Numbers can use 1,234.5 or 1.234,5; 12% reads as 0.12.
      </Typography.Text>
      {!validated && (
        <Alert
          componentId="gsb.reconcile.not_validated"
          type="info"
          closable={false}
          message="Validate this version first. Reconcile runs on its sandbox view."
        />
      )}
      <div>
        <FormUI.Label htmlFor="gsb-reconcile-csv">Legacy report (CSV)</FormUI.Label>
        <Input.TextArea
          componentId="gsb.reconcile.csv"
          id="gsb-reconcile-csv"
          rows={6}
          placeholder={'Region,Net Revenue\nASIA,1234567.89\nEUROPE,2345678.90'}
          value={text}
          onChange={(e) => load(e.target.value)}
        />
        <div style={{ marginTop: 8 }}>
          <FormUI.Label htmlFor="gsb-reconcile-file">Or load a file</FormUI.Label>
          <input
            id="gsb-reconcile-file"
            type="file"
            accept=".csv,.txt,.tsv"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              if (f.size > 2_000_000) return setError('The file is larger than 2 MB.');
              void f.text().then(load);
            }}
          />
        </div>
      </div>
      {csv.header.length > 0 && (
        <div role="group" aria-label="Columns" style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {csv.header.map((h, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <div key={i}>
              <FormUI.Label htmlFor={`gsb-reconcile-col-${i}`}>{h || `Column ${i + 1}`}</FormUI.Label>
              <SimpleSelect
                componentId="gsb.reconcile.column"
                id={`gsb-reconcile-col-${i}`}
                value={mapping[i] ?? ''}
                onChange={(e) => {
                  setResult(undefined);
                  setMapping(mapping.map((m, k) => (k === i ? e.target.value : m)));
                }}
              >
                <SimpleSelectOption value="">Ignore</SimpleSelectOption>
                {fields.dimensions.map((d) => (
                  <SimpleSelectOption key={`d:${d}`} value={`dimension:${d}`}>
                    Dimension: {d}
                  </SimpleSelectOption>
                ))}
                {fields.measures.map((m) => (
                  <SimpleSelectOption key={`m:${m}`} value={`measure:${m}`}>
                    Measure: {m}
                  </SimpleSelectOption>
                ))}
              </SimpleSelect>
            </div>
          ))}
          <div>
            <FormUI.Label htmlFor="gsb-reconcile-tol">Tolerance (%)</FormUI.Label>
            <Input
              componentId="gsb.reconcile.tolerance"
              id="gsb-reconcile-tol"
              type="number"
              min={0}
              max={100}
              step={0.1}
              value={tolerance}
              onChange={(e) => {
                setResult(undefined);
                setTolerance(e.target.value);
              }}
            />
          </div>
        </div>
      )}
      <div>
        <Button
          componentId="gsb.reconcile.run"
          type="primary"
          loading={busy}
          disabled={!validated || !csv.header.length || saving}
          onClick={run}
        >
          Reconcile
        </Button>
      </div>
      {error && <Alert componentId="gsb.reconcile.error" type="error" closable={false} message={error} />}
      {result && (
        <>
          <div role="status" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            {(Object.keys(STATUS) as ReconcileStatus[])
              .filter((s) => result.out.counts[s])
              .map((s) => (
                <Tag key={s} componentId="gsb.reconcile.count" color={STATUS[s].color}>
                  {result.out.counts[s]} {STATUS[s].label.toLowerCase()}
                </Tag>
              ))}
            <Typography.Text color="secondary">Tolerance {result.body.tolerancePct}%.</Typography.Text>
          </div>
          {result.out.truncated && (
            <Alert
              componentId="gsb.reconcile.truncated"
              type="warning"
              closable={false}
              message="The view returned the row limit, so some rows can show as not in the view. Use fewer rows."
            />
          )}
          <div style={{ overflowX: 'auto' }}>
            <Table aria-label="Reconcile result">
              <TableRow isHeader>
                {result.body.dimensions.map((d) => (
                  <TableHeader key={`d:${d}`} componentId="gsb.reconcile.h_dim">
                    {d}
                  </TableHeader>
                ))}
                {result.body.measures.flatMap((m) => [
                  <TableHeader key={`e:${m}`} componentId="gsb.reconcile.h_expected">
                    {m}: report
                  </TableHeader>,
                  <TableHeader key={`a:${m}`} componentId="gsb.reconcile.h_actual">
                    {m}: view
                  </TableHeader>,
                  <TableHeader key={`s:${m}`} componentId="gsb.reconcile.h_status">
                    {m}: difference
                  </TableHeader>,
                ])}
              </TableRow>
              {result.out.rows.map((row, r) => (
                // eslint-disable-next-line react/no-array-index-key
                <TableRow key={r}>
                  {row.keys.map((k, i) => (
                    // eslint-disable-next-line react/no-array-index-key
                    <TableCell key={`k${i}`}>{k}</TableCell>
                  ))}
                  {row.cells.flatMap((c) => [
                    <TableCell key={`e:${c.measure}`}>{fmt(c.expected)}</TableCell>,
                    <TableCell key={`a:${c.measure}`}>{fmt(c.actual)}</TableCell>,
                    <TableCell key={`s:${c.measure}`}>
                      <Tag componentId="gsb.reconcile.status" color={STATUS[c.status].color}>
                        {STATUS[c.status].label}
                      </Tag>
                      {c.diffPct !== null && ` ${Number(c.diffPct.toFixed(2))}%`}
                    </TableCell>,
                  ])}
                </TableRow>
              ))}
            </Table>
          </div>
          <SqlBlock label="The query that ran on the sandbox view" sql={result.out.sql} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              componentId="gsb.reconcile.add_tests"
              disabled={!newTests.length || saving || !confirmed}
              loading={saving}
              onClick={() => onAddTests([...tests, ...newTests])}
            >
              Add {newTests.length} passing {newTests.length === 1 ? 'value' : 'values'} as tests
            </Button>
            <Typography.Text color="secondary">
              {!confirmed && 'Confirm the Semantic Brief in Intent & Context first: tests make a new version. '}
              {passing > newTests.length
                ? `A version has at most ${MAX_TESTS} tests, so ${passing - newTests.length} passing values are left out. `
                : ''}
              Each test checks one measure against the report value, with the row as filters. The tests make a new
              version, which you validate again.
            </Typography.Text>
          </div>
        </>
      )}
    </section>
  );
}
