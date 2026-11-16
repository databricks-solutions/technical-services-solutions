import { useState } from 'react';
import {
  Alert,
  Button,
  Input,
  PencilIcon,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  TrashIcon,
  Typography,
} from '@databricks/design-system';
import type { Additivity, Explanations } from '../../../shared/designer';
import type { DictionaryEntry } from '../../../shared/dictionary';
import { renderMetricView, validateMetricView } from '../../../shared/metricView';
import type { MetricView } from '../../../shared/metricView';
import { useResource } from '../api';
import { FieldBuilder } from './FieldBuilder';
import { MONO } from './SqlBlock';

type Field = MetricView['dimensions'][number];
type Kind = 'measures' | 'dimensions';

const ADDITIVITY: Record<Additivity, string> = {
  additive: 'Additive',
  semi_additive: 'Semi-additive',
  non_additive: 'Not additive',
  ratio: 'Ratio',
};
const flat = (x: string) => x.toLowerCase().replace(/[^a-z0-9]/g, '');

/**
 * Measures and dimensions as two tables. Edit makes the name, SQL and comment cells editable, adds the
 * field form and remove buttons; Save checks the view and creates one new version.
 */
export function FieldTables({
  projectId,
  view,
  explanations,
  disabled,
  saving,
  onSave,
}: {
  projectId: string;
  view: MetricView;
  explanations: Explanations;
  /** True while the YAML has unsaved edits or another action runs. */
  disabled: boolean;
  saving: boolean;
  onSave: (yaml: string) => void;
}) {
  const dict = useResource<{ entries: DictionaryEntry[] }>(`/api/projects/${projectId}/dictionary`).data?.entries ?? [];
  const [edit, setEdit] = useState<MetricView>();
  const [problems, setProblems] = useState<string[]>([]);
  const shown = edit ?? view;

  const tagOf = (f: Field) => {
    const e = dict.find(
      (d) => d.kind !== 'term' && [f.name, f.display_name ?? ''].some((n) => n && flat(n) === flat(d.name))
    );
    return e ? (e.status === 'certified' ? 'Certified' : 'Dictionary') : null;
  };
  const put = (kind: Kind, i: number, f: Partial<Field>) =>
    setEdit((v) => (v ? { ...v, [kind]: v[kind].map((x, j) => (j === i ? { ...x, ...f } : x)) } : v));
  const remove = (kind: Kind, i: number) =>
    setEdit((v) => (v ? { ...v, [kind]: v[kind].filter((_, j) => j !== i) } : v));

  const save = () => {
    if (!edit) return;
    const yaml = renderMetricView(edit);
    const errors = validateMetricView(yaml).issues.filter((i) => i.severity === 'error');
    if (errors.length) {
      setProblems(errors.map((e) => e.message));
      return;
    }
    setProblems([]);
    onSave(yaml);
  };

  const table = (kind: Kind) => {
    const rows = shown[kind];
    return (
      <Table aria-label={kind === 'measures' ? 'Measures' : 'Dimensions'} scrollable>
        <TableRow isHeader>
          <TableHeader componentId="gsb.fields.h_name">Name</TableHeader>
          <TableHeader componentId="gsb.fields.h_expr">SQL</TableHeader>
          {kind === 'measures' && <TableHeader componentId="gsb.fields.h_kind">Kind</TableHeader>}
          <TableHeader componentId="gsb.fields.h_comment">Comment</TableHeader>
          <TableHeader componentId="gsb.fields.h_tag">Dictionary</TableHeader>
          {edit && <TableHeader componentId="gsb.fields.h_remove"> </TableHeader>}
        </TableRow>
        {rows.map((f, i) => {
          const tag = tagOf(f);
          const e = kind === 'measures' ? explanations.measures[f.name] : undefined;
          const m = kind === 'measures' ? view.measures.find((x) => x.name === f.name) : undefined;
          return (
            // Names can change while editing, so the row index is the stable key here.
            // eslint-disable-next-line react/no-array-index-key
            <TableRow key={i}>
              <TableCell>
                {edit ? (
                  <Input
                    componentId="gsb.fields.name"
                    aria-label={`Name of ${kind === 'measures' ? 'measure' : 'dimension'} ${i + 1}`}
                    value={f.name}
                    onChange={(ev) => put(kind, i, { name: ev.target.value })}
                  />
                ) : (
                  <Typography.Text bold>{f.display_name ?? f.name}</Typography.Text>
                )}
              </TableCell>
              <TableCell>
                {edit ? (
                  <Input
                    componentId="gsb.fields.expr"
                    aria-label={`SQL of ${kind === 'measures' ? 'measure' : 'dimension'} ${i + 1}`}
                    value={f.expr}
                    onChange={(ev) => put(kind, i, { expr: ev.target.value })}
                  />
                ) : (
                  <code style={{ ...MONO, overflowWrap: 'anywhere' }}>{f.expr}</code>
                )}
              </TableCell>
              {kind === 'measures' && (
                <TableCell>{e ? ADDITIVITY[e.additivity] : m && 'window' in m && m.window ? 'Window' : ''}</TableCell>
              )}
              <TableCell>
                {edit ? (
                  <Input
                    componentId="gsb.fields.comment"
                    aria-label={`Comment of ${kind === 'measures' ? 'measure' : 'dimension'} ${i + 1}`}
                    value={f.comment ?? ''}
                    onChange={(ev) => put(kind, i, { comment: ev.target.value || undefined })}
                  />
                ) : (
                  <Typography.Text>
                    {f.comment ??
                      (kind === 'measures' ? e?.explanation : explanations.dimensions[f.name]?.explanation) ??
                      ''}
                  </Typography.Text>
                )}
              </TableCell>
              <TableCell>
                {tag && (
                  <Tag componentId="gsb.fields.tag" color={tag === 'Certified' ? 'teal' : 'indigo'}>
                    {tag}
                  </Tag>
                )}
              </TableCell>
              {edit && (
                <TableCell>
                  <Button
                    componentId="gsb.fields.remove"
                    icon={<TrashIcon />}
                    aria-label={`Remove ${f.name}`}
                    onClick={() => remove(kind, i)}
                  />
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </Table>
    );
  };

  return (
    <section aria-label="Fields" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Typography.Title level={4} withoutMargins>
          Measures ({shown.measures.length})
        </Typography.Title>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {edit ? (
            <>
              <Button componentId="gsb.fields.save" type="primary" loading={saving} onClick={save}>
                Save as a new version
              </Button>
              <Button
                componentId="gsb.fields.cancel"
                disabled={saving}
                onClick={() => {
                  setEdit(undefined);
                  setProblems([]);
                }}
              >
                Cancel
              </Button>
            </>
          ) : (
            <Button
              componentId="gsb.fields.edit"
              icon={<PencilIcon />}
              disabled={disabled}
              onClick={() => setEdit(view)}
            >
              Edit fields
            </Button>
          )}
        </div>
      </div>
      {table('measures')}
      <Typography.Title level={4} withoutMargins>
        Dimensions ({shown.dimensions.length})
      </Typography.Title>
      {table('dimensions')}
      {problems.length > 0 && (
        <Alert
          componentId="gsb.fields.problems"
          type="error"
          closable={false}
          message="Fix these before you save"
          description={problems.join(' ')}
        />
      )}
      {edit && (
        <FieldBuilder
          projectId={projectId}
          view={edit}
          onAdd={(kind, f) =>
            setEdit((v) =>
              v
                ? kind === 'measure'
                  ? { ...v, measures: [...v.measures, f] }
                  : { ...v, dimensions: [...v.dimensions, f] }
                : v
            )
          }
        />
      )}
    </section>
  );
}
