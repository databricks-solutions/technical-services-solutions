import { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  FormUI,
  Input,
  PlusIcon,
  SimpleSelect,
  SimpleSelectOption,
  TrashIcon,
  Typography,
} from '@databricks/design-system';
import { saveDraftSchema } from '../../../shared/designer';
import type { Expectation, TestCase } from '../../../shared/designer';
import type { MetricView } from '../../../shared/metricView';

export function FieldPick({
  label,
  names,
  value,
  onChange,
}: {
  label: string;
  names: string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div role="group" aria-label={label} style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      <Typography.Text color="secondary">{label}</Typography.Text>
      {names.map((n) => (
        <Checkbox
          key={n}
          componentId="gsb.test_editor.pick"
          isChecked={value.includes(n)}
          onChange={(on) => onChange(on ? [...value, n] : value.filter((x) => x !== n))}
        >
          {n}
        </Checkbox>
      ))}
    </div>
  );
}

/** The expected value of one measure, and the dimension filters that pick the row. */
function ExpectFields({
  i,
  expect,
  dims,
  onChange,
}: {
  i: number;
  expect: Expectation;
  dims: string[];
  onChange: (e: Expectation) => void;
}) {
  const putFilter = (k: number, f: Expectation['filters'][number]) =>
    onChange({ ...expect, filters: expect.filters.map((x, j) => (j === k ? f : x)) });
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <FormUI.Label htmlFor={`te-value-${i}`}>Expected value</FormUI.Label>
          <Input
            componentId="gsb.test_editor.expected"
            id={`te-value-${i}`}
            type="number"
            value={Number.isNaN(expect.value) ? '' : String(expect.value)}
            onChange={(e) => onChange({ ...expect, value: e.target.value === '' ? NaN : Number(e.target.value) })}
          />
        </div>
        <div>
          <FormUI.Label htmlFor={`te-tol-${i}`}>Tolerance (%)</FormUI.Label>
          <Input
            componentId="gsb.test_editor.tolerance"
            id={`te-tol-${i}`}
            type="number"
            min={0}
            max={100}
            step={0.1}
            value={String(expect.tolerancePct)}
            onChange={(e) => onChange({ ...expect, tolerancePct: Number(e.target.value) })}
          />
        </div>
      </div>
      {expect.filters.map((f, k) => (
        // eslint-disable-next-line react/no-array-index-key
        <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <div>
            <FormUI.Label htmlFor={`te-fd-${i}-${k}`}>Where</FormUI.Label>
            <SimpleSelect
              componentId="gsb.test_editor.filter_dimension"
              id={`te-fd-${i}-${k}`}
              value={f.dimension}
              onChange={(e) => putFilter(k, { ...f, dimension: e.target.value })}
            >
              {dims.map((d) => (
                <SimpleSelectOption key={d} value={d}>
                  {d}
                </SimpleSelectOption>
              ))}
            </SimpleSelect>
          </div>
          <div style={{ flex: 1 }}>
            <FormUI.Label htmlFor={`te-fv-${i}-${k}`}>equals</FormUI.Label>
            <Input
              componentId="gsb.test_editor.filter_value"
              id={`te-fv-${i}-${k}`}
              placeholder="For example 2024"
              value={f.value}
              onChange={(e) => putFilter(k, { ...f, value: e.target.value })}
            />
          </div>
          <Button
            componentId="gsb.test_editor.filter_remove"
            icon={<TrashIcon />}
            aria-label={`Remove filter ${k + 1}`}
            onClick={() => onChange({ ...expect, filters: expect.filters.filter((_, j) => j !== k) })}
          />
        </div>
      ))}
      {dims.length > 0 && expect.filters.length < 5 && (
        <div>
          <Button
            componentId="gsb.test_editor.filter_add"
            size="small"
            icon={<PlusIcon />}
            onClick={() => onChange({ ...expect, filters: [...expect.filters, { dimension: dims[0], value: '' }] })}
          >
            Add a filter
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * Add, change and remove test cases by hand: a name, up to 3 dimensions and 1 to 4 measures each, or one measure
 * with an expected value.
 */
export function TestEditor({
  tests,
  view,
  saving,
  onSave,
  onCancel,
}: {
  tests: TestCase[];
  view: MetricView;
  saving: boolean;
  onSave: (tests: TestCase[]) => void;
  onCancel: () => void;
}) {
  const [rows, setRows] = useState<TestCase[]>(tests);
  const [problems, setProblems] = useState<string[]>([]);
  const dims = view.dimensions.map((d) => d.name);
  const measures = view.measures.map((m) => m.name);
  const put = (i: number, t: TestCase) => setRows((r) => r.map((x, j) => (j === i ? t : x)));

  const save = () => {
    const parsed = saveDraftSchema.shape.tests.safeParse(rows);
    if (!parsed.success) {
      setProblems(
        parsed.error.issues.map((i) => {
          const [n, field] = i.path;
          return `Test ${typeof n === 'number' ? n + 1 : ''} ${String(field ?? '')}: ${i.message}`;
        })
      );
      return;
    }
    const names = rows.map((t) => t.name.trim().toLowerCase());
    if (new Set(names).size !== names.length) {
      setProblems(['Give each test a different name.']);
      return;
    }
    setProblems([]);
    onSave(parsed.data ?? []);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {rows.map((t, i) => (
        <fieldset
          // Rows have no stable id; the inputs are controlled, so an index key cannot leave stale text.
          // eslint-disable-next-line react/no-array-index-key
          key={i}
          style={{
            border: '1px solid var(--db-border-base)',
            borderRadius: 8,
            padding: 12,
            margin: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <FormUI.Label htmlFor={`te-name-${i}`}>Test {i + 1} name</FormUI.Label>
              <Input
                componentId="gsb.test_editor.name"
                id={`te-name-${i}`}
                value={t.name}
                onChange={(e) => put(i, { ...t, name: e.target.value })}
              />
            </div>
            <Button
              componentId="gsb.test_editor.remove"
              icon={<TrashIcon />}
              aria-label={`Remove test ${i + 1}`}
              onClick={() => setRows((r) => r.filter((_, j) => j !== i))}
            />
          </div>
          <Checkbox
            componentId="gsb.test_editor.expect"
            isChecked={!!t.expect}
            onChange={(on) =>
              put(
                i,
                on
                  ? {
                      ...t,
                      dimensions: [],
                      measures: t.measures.slice(0, 1),
                      expect: { value: NaN, tolerancePct: 0.5, filters: [] },
                    }
                  : { name: t.name, dimensions: t.dimensions, measures: t.measures }
              )
            }
          >
            Check against an expected value, for example a total from the legacy report
          </Checkbox>
          <FieldPick
            label={t.expect ? 'Measure (1)' : 'Measures (1 to 4)'}
            names={measures}
            value={t.measures}
            onChange={(v) => put(i, { ...t, measures: t.expect ? v.slice(-1) : v })}
          />
          {t.expect ? (
            <ExpectFields i={i} expect={t.expect} dims={dims} onChange={(e) => put(i, { ...t, expect: e })} />
          ) : (
            <FieldPick
              label="By dimensions (up to 3)"
              names={dims}
              value={t.dimensions}
              onChange={(v) => put(i, { ...t, dimensions: v })}
            />
          )}
        </fieldset>
      ))}
      <div>
        <Button
          componentId="gsb.test_editor.add"
          size="small"
          icon={<PlusIcon />}
          onClick={() =>
            setRows((r) => [...r, { name: `Test ${r.length + 1}`, dimensions: [], measures: measures.slice(0, 1) }])
          }
        >
          Add a test
        </Button>
      </div>
      {problems.length > 0 && (
        <Alert
          componentId="gsb.test_editor.problems"
          type="error"
          closable={false}
          message="Fix these before you save"
          description={problems.join(' ')}
        />
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <Button componentId="gsb.test_editor.save" type="primary" loading={saving} onClick={save}>
          Save the tests
        </Button>
        <Button componentId="gsb.test_editor.cancel" disabled={saving} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
