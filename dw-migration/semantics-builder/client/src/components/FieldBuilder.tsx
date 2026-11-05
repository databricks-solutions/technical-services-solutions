import { useMemo, useState } from 'react';
import { Alert, Button, FormUI, Input, SimpleSelect, SimpleSelectOption, Typography } from '@databricks/design-system';
import { AGGREGATIONS, GRAINS, fieldExpr } from '../../../shared/designer';
import { renderMetricView, validateMetricView } from '../../../shared/metricView';
import type { Join, MetricView } from '../../../shared/metricView';
import { useResource } from '../api';

interface Columns {
  tables: { fullName: string; columns: { name: string; type: string }[] }[];
}

const refsOf = (joins: Join[] | undefined, parent = ''): { ref: string; table: string }[] =>
  (joins ?? []).flatMap((j) => {
    const ref = parent ? `${parent}.${j.name}` : j.name;
    return [{ ref, table: j.source }, ...refsOf(j.joins, ref)];
  });

/** Add a measure or a dimension with a form: pick the table, the column and the aggregation, or write the SQL. */
export function FieldBuilder({
  projectId,
  view,
  busy,
  disabled,
  onSave,
}: {
  projectId: string;
  view: MetricView;
  busy: boolean;
  disabled: boolean;
  onSave: (yaml: string) => void;
}) {
  const columns = useResource<Columns>(`/api/projects/${projectId}/designs/columns`);
  const refs = useMemo(() => [{ ref: 'source', table: view.source }, ...refsOf(view.joins)], [view]);
  const [kind, setKind] = useState<'measure' | 'dimension'>('measure');
  const [name, setName] = useState('');
  const [ref, setRef] = useState('source');
  const [column, setColumn] = useState('');
  const [aggregation, setAggregation] = useState<(typeof AGGREGATIONS)[number]>('SUM');
  const [grain, setGrain] = useState<(typeof GRAINS)[number] | ''>('');
  const [expr, setExpr] = useState<string>();
  const [comment, setComment] = useState('');
  const [problems, setProblems] = useState<string[]>([]);

  const table = refs.find((r) => r.ref === ref)?.table ?? '';
  const cols = columns.data?.tables.find((t) => t.fullName.toLowerCase() === table.toLowerCase())?.columns ?? [];
  const built = fieldExpr({
    ref,
    column,
    ...(kind === 'measure' ? { aggregation } : grain ? { grain } : {}),
  });
  const sql = expr ?? built;

  const add = () => {
    const field = { name: name.trim(), expr: sql.trim(), ...(comment.trim() ? { comment: comment.trim() } : {}) };
    const next: MetricView =
      kind === 'measure'
        ? { ...view, measures: [...view.measures, field] }
        : { ...view, dimensions: [...view.dimensions, field] };
    if (!field.name || !field.expr) {
      setProblems(['Give the field a name and an expression.']);
      return;
    }
    const yaml = renderMetricView(next);
    const errors = validateMetricView(yaml).issues.filter((i) => i.severity === 'error');
    if (errors.length) {
      setProblems(errors.map((e) => e.message));
      return;
    }
    setProblems([]);
    setName('');
    setColumn('');
    setExpr(undefined);
    setComment('');
    onSave(yaml);
  };

  return (
    <section aria-label="Add a field" style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 880 }}>
      <Typography.Title level={4} withoutMargins>
        Add a field by hand
      </Typography.Title>
      <Typography.Text color="secondary">
        Pick the table and the column, or write the SQL. The field is saved as a new version.
      </Typography.Text>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div>
          <FormUI.Label htmlFor="fb-kind">Kind</FormUI.Label>
          <SimpleSelect
            componentId="gsb.field_builder.kind"
            id="fb-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as 'measure' | 'dimension')}
          >
            <SimpleSelectOption value="measure">Measure</SimpleSelectOption>
            <SimpleSelectOption value="dimension">Dimension</SimpleSelectOption>
          </SimpleSelect>
        </div>
        <div>
          <FormUI.Label htmlFor="fb-name" required>
            Name
          </FormUI.Label>
          <Input
            componentId="gsb.field_builder.name"
            id="fb-name"
            placeholder="For example Net Revenue"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: 220 }}
          />
        </div>
        <div>
          <FormUI.Label htmlFor="fb-table">Table</FormUI.Label>
          <SimpleSelect
            componentId="gsb.field_builder.table"
            id="fb-table"
            value={ref}
            onChange={(e) => {
              setRef(e.target.value);
              setColumn('');
              setExpr(undefined);
            }}
          >
            {refs.map((r) => (
              <SimpleSelectOption key={r.ref} value={r.ref}>
                {r.ref === 'source' ? `${r.table} (fact)` : `${r.ref} (${r.table.split('.').pop() ?? ''})`}
              </SimpleSelectOption>
            ))}
          </SimpleSelect>
        </div>
        <div>
          <FormUI.Label htmlFor="fb-column">Column</FormUI.Label>
          <SimpleSelect
            componentId="gsb.field_builder.column"
            id="fb-column"
            value={column}
            placeholder={columns.status === 'loading' ? 'Loading' : 'Pick a column'}
            onChange={(e) => {
              setColumn(e.target.value);
              setExpr(undefined);
            }}
          >
            {cols.map((c) => (
              <SimpleSelectOption key={c.name} value={c.name}>
                {`${c.name} (${c.type})`}
              </SimpleSelectOption>
            ))}
          </SimpleSelect>
        </div>
        {kind === 'measure' ? (
          <div>
            <FormUI.Label htmlFor="fb-agg">Aggregation</FormUI.Label>
            <SimpleSelect
              componentId="gsb.field_builder.aggregation"
              id="fb-agg"
              value={aggregation}
              onChange={(e) => {
                setAggregation(e.target.value as (typeof AGGREGATIONS)[number]);
                setExpr(undefined);
              }}
            >
              {AGGREGATIONS.map((a) => (
                <SimpleSelectOption key={a} value={a}>
                  {a.replace('_', ' ')}
                </SimpleSelectOption>
              ))}
            </SimpleSelect>
          </div>
        ) : (
          <div>
            <FormUI.Label htmlFor="fb-grain">Date grain</FormUI.Label>
            <SimpleSelect
              componentId="gsb.field_builder.grain"
              id="fb-grain"
              value={grain}
              placeholder="None"
              onChange={(e) => {
                setGrain(e.target.value as (typeof GRAINS)[number] | '');
                setExpr(undefined);
              }}
            >
              <SimpleSelectOption value="">None</SimpleSelectOption>
              {GRAINS.map((g) => (
                <SimpleSelectOption key={g} value={g}>
                  {g.toLowerCase()}
                </SimpleSelectOption>
              ))}
            </SimpleSelect>
          </div>
        )}
      </div>
      <div>
        <FormUI.Label htmlFor="fb-expr" required>
          SQL expression
        </FormUI.Label>
        <FormUI.Hint>Built from your choices. Edit it for a ratio, a filter or a CASE.</FormUI.Hint>
        <Input
          componentId="gsb.field_builder.expr"
          id="fb-expr"
          value={sql}
          onChange={(e) => setExpr(e.target.value)}
        />
      </div>
      <div>
        <FormUI.Label htmlFor="fb-comment">Comment</FormUI.Label>
        <Input
          componentId="gsb.field_builder.comment"
          id="fb-comment"
          placeholder="One sentence: what it means for the business"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      {problems.length > 0 && (
        <Alert
          componentId="gsb.field_builder.problems"
          type="error"
          closable={false}
          message="Fix these before you add the field"
          description={problems.join(' ')}
        />
      )}
      <div>
        <Button componentId="gsb.field_builder.add" loading={busy} disabled={disabled} onClick={add}>
          Add the {kind}
        </Button>
      </div>
    </section>
  );
}
