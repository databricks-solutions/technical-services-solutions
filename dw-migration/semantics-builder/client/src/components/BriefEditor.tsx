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
import { semanticBriefSchema } from '../../../shared/brief';
import type { SemanticBrief } from '../../../shared/brief';

type Measure = SemanticBrief['measures'][number];
type Named = SemanticBrief['dimensions'][number];
type Term = SemanticBrief['glossary'][number];

const AGGREGATIONS: Measure['aggregation'][] = [
  'sum',
  'count',
  'count_distinct',
  'avg',
  'min',
  'max',
  'ratio',
  'other',
];
const GRAINS: SemanticBrief['timeGrains'] = ['day', 'week', 'month', 'quarter', 'year'];
const lines = (v: string) =>
  v
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean);

function Lines({
  id,
  label,
  value,
  onChange,
  help,
}: {
  id: string;
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  help?: string;
}) {
  const [text, setText] = useState(value.join('\n'));
  return (
    <div>
      <FormUI.Label htmlFor={id}>{label}</FormUI.Label>
      {help && <FormUI.Hint>{help}</FormUI.Hint>}
      <Input.TextArea
        componentId={`gsb.brief_editor.${id}`}
        id={id}
        value={text}
        autoSize={{ minRows: 2, maxRows: 8 }}
        onChange={(e) => {
          setText(e.target.value);
          onChange(lines(e.target.value));
        }}
      />
    </div>
  );
}

/** Rows of fields, each with a remove button, and one button to add a row. */
function Rows<T>({
  label,
  rows,
  blank,
  onChange,
  render,
}: {
  label: string;
  rows: T[];
  blank: T;
  onChange: (rows: T[]) => void;
  render: (row: T, set: (row: T) => void, i: number) => React.ReactNode;
}) {
  return (
    <fieldset style={{ border: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <legend>
        <Typography.Text bold>{label}</Typography.Text>
      </legend>
      {rows.map((r, i) => (
        // Rows have no stable id; the inputs are controlled, so an index key cannot leave stale text.
        // eslint-disable-next-line react/no-array-index-key
        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          {render(r, (next) => onChange(rows.map((x, j) => (j === i ? next : x))), i)}
          <Button
            componentId="gsb.brief_editor.remove_row"
            icon={<TrashIcon />}
            aria-label={`Remove row ${i + 1} of ${label}`}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
          />
        </div>
      ))}
      <div>
        <Button
          componentId="gsb.brief_editor.add_row"
          size="small"
          icon={<PlusIcon />}
          onClick={() => onChange([...rows, blank])}
        >
          Add
        </Button>
      </div>
    </fieldset>
  );
}

const EMPTY: SemanticBrief = {
  title: '',
  businessGoal: '',
  audience: [],
  keyQuestions: [],
  measures: [],
  dimensions: [],
  timeGrains: [],
  candidateSources: [],
  glossary: [],
  assumptions: [],
  openQuestions: [],
};

/** Write or edit every section of the brief by hand. Checked with the same schema as a model draft. */
export function BriefEditor({
  initial,
  saving,
  onSave,
  onCancel,
}: {
  initial: Partial<SemanticBrief>;
  saving: boolean;
  onSave: (brief: SemanticBrief) => void;
  onCancel: () => void;
}) {
  const [b, setB] = useState<SemanticBrief>({ ...EMPTY, ...initial });
  const [problems, setProblems] = useState<string[]>([]);
  const set = <K extends keyof SemanticBrief>(k: K, v: SemanticBrief[K]) => setB((x) => ({ ...x, [k]: v }));

  const save = () => {
    const clean: SemanticBrief = {
      ...b,
      measures: b.measures.filter((m) => m.name.trim()),
      dimensions: b.dimensions.filter((d) => d.name.trim()),
      glossary: b.glossary.filter((g) => g.term.trim()),
    };
    const parsed = semanticBriefSchema.safeParse(clean);
    if (!parsed.success) {
      setProblems(parsed.error.issues.map((i) => `${i.path.join('.') || 'brief'}: ${i.message}`));
      return;
    }
    setProblems([]);
    onSave(parsed.data);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 880 }}>
      <div>
        <FormUI.Label htmlFor="be-title" required>
          Title
        </FormUI.Label>
        <Input
          componentId="gsb.brief_editor.title"
          id="be-title"
          value={b.title}
          onChange={(e) => set('title', e.target.value)}
        />
      </div>
      <div>
        <FormUI.Label htmlFor="be-goal" required>
          Business goal
        </FormUI.Label>
        <Input.TextArea
          componentId="gsb.brief_editor.goal"
          id="be-goal"
          value={b.businessGoal}
          autoSize={{ minRows: 2, maxRows: 6 }}
          onChange={(e) => set('businessGoal', e.target.value)}
        />
      </div>
      <Lines
        id="be-audience"
        label="Audience"
        help="One per line."
        value={b.audience}
        onChange={(v) => set('audience', v)}
      />
      <Lines
        id="be-questions"
        label="Key questions"
        help="One per line. At least one."
        value={b.keyQuestions}
        onChange={(v) => set('keyQuestions', v)}
      />
      <Rows<Measure>
        label="Measures"
        rows={b.measures}
        blank={{ name: '', aggregation: 'sum', description: '' }}
        onChange={(v) => set('measures', v)}
        render={(m, put, i) => (
          <>
            <Input
              componentId="gsb.brief_editor.measure_name"
              aria-label={`Measure ${i + 1} name`}
              placeholder="Name, for example Net Revenue"
              value={m.name}
              onChange={(e) => put({ ...m, name: e.target.value })}
              style={{ width: 220 }}
            />
            <SimpleSelect
              componentId="gsb.brief_editor.measure_agg"
              id={`be-agg-${i}`}
              aria-label={`Measure ${i + 1} aggregation`}
              value={m.aggregation}
              onChange={(e) => put({ ...m, aggregation: e.target.value as Measure['aggregation'] })}
            >
              {AGGREGATIONS.map((a) => (
                <SimpleSelectOption key={a} value={a}>
                  {a.replace('_', ' ')}
                </SimpleSelectOption>
              ))}
            </SimpleSelect>
            <Input
              componentId="gsb.brief_editor.measure_desc"
              aria-label={`Measure ${i + 1} description`}
              placeholder="What it means"
              value={m.description}
              onChange={(e) => put({ ...m, description: e.target.value })}
            />
          </>
        )}
      />
      <Rows<Named>
        label="Dimensions"
        rows={b.dimensions}
        blank={{ name: '', description: '' }}
        onChange={(v) => set('dimensions', v)}
        render={(d, put, i) => (
          <>
            <Input
              componentId="gsb.brief_editor.dim_name"
              aria-label={`Dimension ${i + 1} name`}
              placeholder="Name, for example Customer Region"
              value={d.name}
              onChange={(e) => put({ ...d, name: e.target.value })}
              style={{ width: 220 }}
            />
            <Input
              componentId="gsb.brief_editor.dim_desc"
              aria-label={`Dimension ${i + 1} description`}
              placeholder="What it means"
              value={d.description}
              onChange={(e) => put({ ...d, description: e.target.value })}
            />
          </>
        )}
      />
      <div
        role="group"
        aria-label="Time grains"
        style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}
      >
        <Typography.Text bold>Time grains</Typography.Text>
        {GRAINS.map((g) => (
          <Checkbox
            key={g}
            componentId="gsb.brief_editor.grain"
            isChecked={b.timeGrains.includes(g)}
            onChange={(on) => set('timeGrains', on ? [...b.timeGrains, g] : b.timeGrains.filter((x) => x !== g))}
          >
            {g}
          </Checkbox>
        ))}
      </div>
      <Lines
        id="be-sources"
        label="Candidate sources"
        help="catalog.schema.table, one per line."
        value={b.candidateSources}
        onChange={(v) => set('candidateSources', v)}
      />
      <Rows<Term>
        label="Glossary"
        rows={b.glossary}
        blank={{ term: '', definition: '' }}
        onChange={(v) => set('glossary', v)}
        render={(g, put, i) => (
          <>
            <Input
              componentId="gsb.brief_editor.term"
              aria-label={`Term ${i + 1}`}
              placeholder="Term"
              value={g.term}
              onChange={(e) => put({ ...g, term: e.target.value })}
              style={{ width: 220 }}
            />
            <Input
              componentId="gsb.brief_editor.definition"
              aria-label={`Definition of term ${i + 1}`}
              placeholder="Definition"
              value={g.definition}
              onChange={(e) => put({ ...g, definition: e.target.value })}
            />
          </>
        )}
      />
      <Lines
        id="be-assumptions"
        label="Assumptions"
        help="One per line."
        value={b.assumptions}
        onChange={(v) => set('assumptions', v)}
      />
      <Lines
        id="be-open"
        label="Open questions"
        help="One per line."
        value={b.openQuestions}
        onChange={(v) => set('openQuestions', v)}
      />
      {problems.length > 0 && (
        <Alert
          componentId="gsb.brief_editor.problems"
          type="error"
          closable={false}
          message="Fix these before you save"
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          }
        />
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <Button componentId="gsb.brief_editor.save" type="primary" loading={saving} onClick={save}>
          Save as a new version
        </Button>
        <Button componentId="gsb.brief_editor.cancel" disabled={saving} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
