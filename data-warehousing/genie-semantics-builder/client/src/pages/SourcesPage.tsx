import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  Alert,
  ArrowRightIcon,
  Button,
  Checkbox,
  Modal,
  PlusIcon,
  Progress,
  SparkleIcon,
  Spinner,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tabs,
  Tag,
  TrashIcon,
  Typography,
} from '@databricks/design-system';
import type {
  AreaScore,
  CheckStatus,
  ReadinessView,
  Recommendation,
  RelatedTable,
  SourceReadiness,
} from '../../../shared/readiness';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';
import { OntologyGraph } from '../components/OntologyGraph';
import { FixPermission, PermissionsPanel } from '../components/PermissionsPanel';
import { MONO } from '../components/SqlBlock';
import { TableSelector } from '../components/TableSelector';

type TagColor = 'teal' | 'lemon' | 'coral' | 'default';

const CHECK_TAG: Record<CheckStatus, { color: TagColor; label: string }> = {
  pass: { color: 'teal', label: 'Pass' },
  warn: { color: 'lemon', label: 'Warning' },
  fail: { color: 'coral', label: 'Fail' },
};

const STATUS_TAG: Record<Recommendation['status'], { color: TagColor; label: string }> = {
  proposed: { color: 'default', label: 'Proposed' },
  approved: { color: 'lemon', label: 'Running' },
  applied: { color: 'teal', label: 'Applied' },
  rejected: { color: 'default', label: 'Rejected' },
  failed: { color: 'coral', label: 'Failed' },
};

const band = (score: number): [TagColor, string] =>
  score >= 80 ? ['teal', 'Ready'] : score >= 50 ? ['lemon', 'Needs work'] : ['coral', 'Not ready'];

const FILL: Record<TagColor, string> = {
  teal: 'var(--db-alert-icon-color-success)',
  lemon: 'var(--db-alert-icon-color-warning)',
  coral: 'var(--db-alert-icon-color-error)',
  default: 'var(--db-alert-icon-color-info)',
};

const isOpen = (r: Recommendation) => r.status === 'proposed' || r.status === 'failed';

function ScoreTag({ score }: { score: number | null }) {
  if (score === null) return <Tag componentId="gsb.sources.score">Not scored</Tag>;
  const [color, label] = band(score);
  return (
    <Tag componentId="gsb.sources.score" color={color}>
      {score} - {label}
    </Tag>
  );
}

function Sql({ statements }: { statements: string[] }) {
  return (
    <pre
      style={{
        ...MONO,
        margin: 0,
        padding: 12,
        maxHeight: 240,
        overflow: 'auto',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        border: '1px solid var(--db-border-base)',
        borderRadius: 4,
      }}
    >
      {statements.map((s) => `${s};`).join('\n')}
    </pre>
  );
}

function Areas({ areas }: { areas: AreaScore[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {areas.map((a) => (
        <div
          key={a.id}
          style={{ display: 'grid', gridTemplateColumns: '180px 1fr 48px', gap: 12, alignItems: 'center' }}
        >
          <div>
            <Typography.Text bold>{a.label}</Typography.Text>
            <br />
            <Typography.Text color="secondary" size="sm">
              {a.weight}% of the score
            </Typography.Text>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <Progress.Root
              value={a.score}
              aria-label={`${a.label}: ${a.score} of 100`}
              style={{ ['--db-progress-fill' as string]: FILL[band(a.score)[0]] }}
            >
              <Progress.Indicator />
            </Progress.Root>
            <Typography.Text color="secondary" size="sm">
              {a.detail}
            </Typography.Text>
          </div>
          <Typography.Text bold>{a.score}</Typography.Text>
        </div>
      ))}
    </div>
  );
}

function ScoreSummary({ view }: { view: ReadinessView }) {
  if (!view.score)
    return (
      <Alert
        componentId="gsb.sources.no_score"
        type="info"
        closable={false}
        message="Assess the sources to see the semantic readiness score."
        description="The score shows how well the tables describe themselves to Genie and metric views: documentation, keys and relationships, data types, naming and how much of the brief they cover."
      />
    );
  const [color, label] = band(view.score.score);
  return (
    <section
      aria-labelledby="gsb-score"
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(160px, 200px) 1fr',
        gap: 24,
        padding: 16,
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Typography.Text id="gsb-score" color="secondary">
          Semantic readiness
        </Typography.Text>
        <span style={{ fontSize: 48, fontWeight: 600, lineHeight: '56px' }}>{view.score.score}</span>
        <div>
          <Tag componentId="gsb.sources.score_band" color={color}>
            {label}
          </Tag>
        </div>
        <Typography.Text color="secondary" size="sm">
          Rule-based, from table metadata. 80 or more is ready.
        </Typography.Text>
      </div>
      <Areas areas={view.score.areas} />
    </section>
  );
}

function FixCard({
  fix,
  busy,
  onApply,
  onReject,
}: {
  fix: Recommendation;
  busy: boolean;
  onApply: () => void;
  onReject: () => void;
}) {
  const open = isOpen(fix);
  return (
    <article
      aria-label={fix.title}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 16,
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Typography.Text bold>{fix.title}</Typography.Text>
        {open && fix.scoreGain > 0 && (
          <Tag componentId="gsb.sources.fix_gain" color="teal">
            +{fix.scoreGain} points
          </Tag>
        )}
        <Tag componentId="gsb.sources.fix_status" color={STATUS_TAG[fix.status].color}>
          {STATUS_TAG[fix.status].label}
        </Tag>
      </div>
      <Typography.Text color="secondary">{fix.rationale}</Typography.Text>
      {open && <Sql statements={fix.statements} />}
      {fix.error && <Alert componentId="gsb.sources.fix_error" type="error" closable={false} message={fix.error} />}
      {fix.decidedBy && !open && (
        <Typography.Text color="secondary" size="sm">
          {STATUS_TAG[fix.status].label} by {fix.decidedBy}
          {fix.decidedAt ? ` on ${new Date(fix.decidedAt).toLocaleString()}` : ''}
        </Typography.Text>
      )}
      {open && (
        <div style={{ display: 'flex', gap: 8 }}>
          <Button componentId="gsb.sources.fix_review" type="primary" disabled={busy} onClick={onApply}>
            {fix.status === 'failed' ? 'Review and retry' : 'Review and apply'}
          </Button>
          <Button componentId="gsb.sources.fix_reject" disabled={busy} onClick={onReject}>
            Reject
          </Button>
        </div>
      )}
    </article>
  );
}

function SourceDetail({ source, busy, onRemove }: { source: SourceReadiness; busy: boolean; onRemove: () => void }) {
  const report = source.report;
  return (
    <section
      aria-label={source.fullName}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        padding: 16,
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Typography.Title level={4} withoutMargins>
          {report?.assessment?.entity ?? source.fullName.split('.').pop()}
        </Typography.Title>
        <Typography.Text color="secondary">{source.fullName}</Typography.Text>
        <Tag componentId="gsb.sources.role">
          {source.role === 'unknown' ? 'Role not known' : source.role === 'fact' ? 'Fact' : 'Dimension'}
        </Tag>
        {report ? <ScoreTag score={report.score} /> : <Tag componentId="gsb.sources.score">Not assessed</Tag>}
        <div style={{ marginLeft: 'auto' }}>
          <Button
            componentId="gsb.sources.remove"
            size="small"
            icon={<TrashIcon />}
            disabled={busy}
            onClick={onRemove}
            aria-label={`Remove ${source.fullName} from the sources`}
          >
            Remove
          </Button>
        </div>
      </div>
      {report && report.areas.length > 0 && <Areas areas={report.areas} />}
      {report?.assessment && (
        <Alert
          componentId="gsb.sources.ai_notice"
          type="info"
          closable={false}
          message="AI review. Check the findings against your knowledge of the data."
          description={
            <>
              <Typography.Paragraph>{report.assessment.summary}</Typography.Paragraph>
              {report.assessment.findings.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {report.assessment.findings.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              )}
              {!!report.assessment.coverage?.length && (
                <Typography.Paragraph withoutMargins>
                  Sources for the brief: {report.assessment.coverage.map((c) => `${c.item} (${c.column})`).join(', ')}
                </Typography.Paragraph>
              )}
            </>
          }
        />
      )}
      {report && (
        <Table>
          <TableRow isHeader>
            <TableHeader componentId="gsb.sources.check_col_check">Check</TableHeader>
            <TableHeader componentId="gsb.sources.check_col_result">Result</TableHeader>
            <TableHeader componentId="gsb.sources.check_col_detail">Detail</TableHeader>
          </TableRow>
          {report.checks.map((c) => (
            <TableRow key={c.id}>
              <TableCell>{c.label}</TableCell>
              <TableCell>
                <Tag componentId="gsb.sources.check_status" color={CHECK_TAG[c.status].color}>
                  {CHECK_TAG[c.status].label}
                </Tag>
              </TableCell>
              <TableCell>{c.detail}</TableCell>
            </TableRow>
          ))}
        </Table>
      )}
    </section>
  );
}

function AddTablesModal({
  projectId,
  onAdd,
  onClose,
}: {
  projectId: string;
  onAdd: (tables: string[]) => Promise<void>;
  onClose: () => void;
}) {
  return (
    <Modal componentId="gsb.sources.add_modal" title="Add tables" visible footer={null} onCancel={onClose}>
      <TableSelector projectId={projectId} addLabel={(n) => `Add ${n} table${n === 1 ? '' : 's'}`} onAdd={onAdd} />
    </Modal>
  );
}

function RelatedModal({
  projectId,
  onAdd,
  onClose,
}: {
  projectId: string;
  onAdd: (tables: string[]) => Promise<void>;
  onClose: () => void;
}) {
  const related = useResource<RelatedTable[]>(`/api/projects/${projectId}/sources/related`);
  const [picked, setPicked] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  return (
    <Modal
      componentId="gsb.sources.related_modal"
      title="Bring related tables"
      visible
      okText={picked.length ? `Add ${picked.length} table${picked.length === 1 ? '' : 's'}` : 'Add tables'}
      okButtonProps={{ disabled: !picked.length, loading: saving }}
      cancelText="Cancel"
      onCancel={onClose}
      onOk={() => {
        setSaving(true);
        void onAdd(picked).finally(() => setSaving(false));
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Typography.Text color="secondary">
          Tables in the same schemas that join to your sources, from declared foreign keys and matching key names. Add a
          table, then look again to follow the next join.
        </Typography.Text>
        <DataState
          status={related.status === 'ready' && !related.data?.length ? 'empty' : related.status}
          message={related.error ?? 'No related tables found in the source schemas.'}
          onRetry={related.reload}
        >
          <div role="group" aria-label="Related tables" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {related.data?.map((r) => (
              <Checkbox
                key={r.table}
                componentId="gsb.sources.related_table"
                isChecked={picked.includes(r.table)}
                onChange={(on) => setPicked((p) => (on ? [...p, r.table] : p.filter((t) => t !== r.table)))}
              >
                <span>
                  <Typography.Text bold>{r.table}</Typography.Text>
                  <br />
                  <Typography.Text color="secondary" size="sm">
                    {r.reasons.join('; ')}
                  </Typography.Text>
                </span>
              </Checkbox>
            ))}
          </div>
        </DataState>
      </div>
    </Modal>
  );
}

export function SourcesPage() {
  const { projectId = '', parentId = '' } = useParams();
  const navigate = useNavigate();
  const view = useResource<ReadinessView>(`/api/projects/${projectId}/readiness`);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const [reviewing, setReviewing] = useState<Recommendation>();
  const [adding, setAdding] = useState<'pick' | 'related'>();

  const post = (key: string, path: string, body: unknown = {}) => {
    setBusy(key);
    setError(undefined);
    return api<ReadinessView>(path, body).then(
      (v) => {
        setBusy(undefined);
        view.setData(v);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };
  const addTables = (tables: string[]) =>
    post('add', `/api/projects/${projectId}/sources`, { tables }).then(() => setAdding(undefined));
  const intake = `/projects/${parentId}/sub/${projectId}/intake`;

  // A new sub-project starts here: choose the tables, then the assessment runs at once.
  if (view.status === 'ready' && view.data && !view.data.sources.length)
    return (
      <section aria-labelledby="gsb-setup" style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 960 }}>
        <Typography.Title level={3} id="gsb-setup" withoutMargins>
          Choose the tables to model
        </Typography.Title>
        <Typography.Text color="secondary">
          Pick the tables for this metric view: usually one fact table, such as orders or sales, and the tables it joins
          to. The app checks how they relate, then assesses them. You do not need to know your metrics yet: after this
          step the AI suggests what you can build from these tables.
        </Typography.Text>
        {error && <Alert componentId="gsb.sources.error" type="error" closable={false} message={error} />}
        <TableSelector
          projectId={projectId}
          addLabel={(n) => `Add ${n} table${n === 1 ? '' : 's'} and assess`}
          onAdd={(tables) =>
            post('add', `/api/projects/${projectId}/sources`, { tables }).then(() =>
              post('run', `/api/projects/${projectId}/readiness/run`)
            )
          }
        />
        {busy === 'run' && (
          <div role="status" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Spinner label="Assessing" />
            <Typography.Text color="secondary">Assessing the tables. This can take a minute.</Typography.Text>
          </div>
        )}
      </section>
    );

  const data = view.data;
  const status = view.status;
  const assessed = data?.sources.some((s) => s.report) ?? false;
  const fixes = [...(data?.recommendations ?? [])].sort(
    (a, b) => Number(isOpen(b)) - Number(isOpen(a)) || b.scoreGain - a.scoreGain
  );
  const openFixes = fixes.filter(isOpen);
  const potential = Math.min(100, (data?.score?.score ?? 0) + openFixes.reduce((s, r) => s + r.scoreGain, 0));
  const addButtons = (
    <>
      <Button componentId="gsb.sources.add" icon={<PlusIcon />} disabled={!!busy} onClick={() => setAdding('pick')}>
        Add tables
      </Button>
      <Button
        componentId="gsb.sources.related"
        icon={<SparkleIcon />}
        disabled={!!busy || !data?.sources.length}
        onClick={() => setAdding('related')}
      >
        Bring related tables
      </Button>
    </>
  );

  return (
    <>
      <DataState status={status} message={view.error} onRetry={view.reload}>
        {data && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <Button
                componentId="gsb.sources.run"
                type="primary"
                loading={busy === 'run'}
                disabled={!!busy}
                onClick={() => void post('run', `/api/projects/${projectId}/readiness/run`)}
              >
                {assessed ? 'Assess again' : 'Assess sources'}
              </Button>
              {addButtons}
              <Typography.Text color="secondary">
                {data.sources.length} source{data.sources.length === 1 ? '' : 's'}. The assessment reads metadata with
                your permissions. Nothing changes until you approve a fix.
              </Typography.Text>
              {assessed && (
                <div style={{ marginLeft: 'auto' }}>
                  <Button
                    componentId="gsb.sources.next"
                    type="primary"
                    endIcon={<ArrowRightIcon />}
                    disabled={!!busy}
                    onClick={() => void navigate(intake)}
                  >
                    Next: Intent & Context
                  </Button>
                </div>
              )}
            </div>
            {busy === 'run' && (
              <div role="status" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Spinner label="Assessing" />
                <Typography.Text color="secondary">
                  Checking {data.sources.length} tables. This can take a minute.
                </Typography.Text>
              </div>
            )}
            {error && <Alert componentId="gsb.sources.error" type="error" closable={false} message={error} />}

            <ScoreSummary view={data} />

            <Tabs.Root componentId="gsb.sources.tabs" defaultValue="plan">
              <Tabs.List>
                <Tabs.Trigger value="plan">Improvement plan ({openFixes.length})</Tabs.Trigger>
                <Tabs.Trigger value="ontology">Ontology</Tabs.Trigger>
                <Tabs.Trigger value="tables">Tables ({data.sources.length})</Tabs.Trigger>
                <Tabs.Trigger value="permissions">Permissions</Tabs.Trigger>
              </Tabs.List>

              <Tabs.Content value="plan">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 16 }}>
                  {openFixes.length > 0 ? (
                    <Typography.Text color="secondary">
                      Ranked by the points each fix adds. Applying all open fixes brings the score to about {potential}.
                      Declare primary keys before the foreign keys that reference them.
                    </Typography.Text>
                  ) : (
                    <Typography.Text color="secondary">
                      {assessed
                        ? 'No open fixes. Types and naming are fixed in the metric view: cast columns and give fields business names.'
                        : 'Assess the sources to get a ranked plan.'}
                    </Typography.Text>
                  )}
                  {fixes.map((r) => (
                    <FixCard
                      key={r.id}
                      fix={r}
                      busy={!!busy}
                      onApply={() => setReviewing(r)}
                      onReject={() => void post(r.id, `/api/projects/${projectId}/recommendations/${r.id}/reject`)}
                    />
                  ))}
                </div>
              </Tabs.Content>

              <Tabs.Content value="ontology">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 16 }}>
                  <Typography.Text color="secondary">
                    Business entities and how they join. Solid lines are declared foreign keys. Dashed lines are joins
                    suggested by the key names; declare them to document the model.
                  </Typography.Text>
                  {assessed ? <OntologyGraph ontology={data.ontology} /> : null}
                  {data.ontology.unmapped.length > 0 && (
                    <Alert
                      componentId="gsb.sources.unmapped"
                      type="warning"
                      closable={false}
                      message="Brief items with no source column"
                      description={`${data.ontology.unmapped.join(', ')}. Bring related tables that hold them, or update the brief.`}
                    />
                  )}
                  {data.ontology.unlinked.length > 0 && (
                    <Alert
                      componentId="gsb.sources.unlinked"
                      type="warning"
                      closable={false}
                      message="Tables with no join"
                      description={`${data.ontology.unlinked.join(', ')}. A metric view needs a join path from the fact table.`}
                    />
                  )}
                  {!assessed && (
                    <Typography.Text color="secondary">Assess the sources to map the entities.</Typography.Text>
                  )}
                </div>
              </Tabs.Content>

              <Tabs.Content value="tables">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 16 }}>
                  {data.sources.map((s) => (
                    <SourceDetail
                      key={s.sourceId}
                      source={s}
                      busy={!!busy}
                      onRemove={() => void post(s.sourceId, `/api/projects/${projectId}/sources/${s.sourceId}/remove`)}
                    />
                  ))}
                </div>
              </Tabs.Content>
              <Tabs.Content value="permissions">
                <div style={{ paddingTop: 16 }}>
                  <PermissionsPanel projectId={projectId} />
                </div>
              </Tabs.Content>
            </Tabs.Root>

            <Modal
              componentId="gsb.sources.apply_modal"
              title={reviewing ? `Apply: ${reviewing.title}` : ''}
              visible={!!reviewing}
              okText="Run SQL"
              cancelText="Cancel"
              okButtonProps={{ loading: !!reviewing && busy === reviewing.id }}
              onCancel={() => setReviewing(undefined)}
              onOk={() => {
                if (!reviewing) return;
                void post(reviewing.id, `/api/projects/${projectId}/recommendations/${reviewing.id}/apply`, {
                  statements: reviewing.statements,
                }).then(() => setReviewing(undefined));
              }}
            >
              {reviewing && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <Alert
                    componentId="gsb.sources.apply_warning"
                    type="warning"
                    closable={false}
                    message="This SQL runs as you on the SQL warehouse and changes Unity Catalog metadata. It does not change table data."
                  />
                  {reviewing.sourceName && <FixPermission projectId={projectId} table={reviewing.sourceName} />}
                  <Sql statements={reviewing.statements} />
                </div>
              )}
            </Modal>
          </div>
        )}
      </DataState>
      {adding === 'pick' && (
        <AddTablesModal projectId={projectId} onAdd={addTables} onClose={() => setAdding(undefined)} />
      )}
      {adding === 'related' && (
        <RelatedModal projectId={projectId} onAdd={addTables} onClose={() => setAdding(undefined)} />
      )}
    </>
  );
}
