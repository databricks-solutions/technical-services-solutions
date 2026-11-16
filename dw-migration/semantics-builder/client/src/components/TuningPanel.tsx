import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import { describeChange } from '../../../shared/genie';
import type { Tuning, TuningView } from '../../../shared/genie';
import { api, useResource } from '../api';
import { SqlBlock } from './SqlBlock';

const POLL_MS = 10_000;
export const ACCURACY_TARGET = 85;

const ASSESSMENT: Record<string, { color: 'teal' | 'coral' | 'lemon'; label: string }> = {
  GOOD: { color: 'teal', label: 'Correct' },
  BAD: { color: 'coral', label: 'Wrong' },
  NEEDS_REVIEW: { color: 'lemon', label: 'Needs review' },
};
const TUNING: Record<Tuning['status'], { color: 'teal' | 'coral' | 'lemon' | 'default'; label: string }> = {
  proposed: { color: 'lemon', label: 'Suggested' },
  trying: { color: 'lemon', label: 'On trial' },
  kept: { color: 'teal', label: 'Kept' },
  reverted: { color: 'default', label: 'Reverted' },
  dismissed: { color: 'default', label: 'Dismissed' },
  failed: { color: 'coral', label: 'Failed' },
};
const pct = (c: number, n: number) => (n ? Math.round((100 * c) / n) : 0);

/**
 * Optimize the Genie agent: run the benchmarks, ask the AI for one change to a wrong answer, examine and try it.
 * The app keeps the change only when more answers are correct; else it restores the settings.
 */
export function TuningPanel({ projectId, onSettled }: { projectId: string; onSettled: () => void }) {
  const res = useResource<TuningView>(`/api/projects/${projectId}/genie/tuning`);
  const { refresh } = res;
  const v = res.data;
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const [examine, setExamine] = useState<{ tuning: Tuning; config: string }>();
  const running = !!v?.runs.some((r) => r.status === 'running');
  const wasRunning = useRef(false);

  // A run takes about 10 seconds for each question. Poll while one runs; the server reads it from Genie.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [running, refresh]);
  useEffect(() => {
    if (wasRunning.current && !running) onSettled();
    wasRunning.current = running;
  }, [running, onSettled]);

  const call = <T,>(key: string, path: string, body: unknown, then: (r: T) => void) => {
    setBusy(key);
    setError(undefined);
    api<T>(`/api/projects/${projectId}/genie/${path}`, body).then(
      (r) => {
        setBusy(undefined);
        then(r);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };
  if (!v) return null;
  const latest = v.runs.find((r) => r.status === 'done' && r.current);
  const open = v.tunings.find((t) => t.status === 'proposed');

  return (
    <section
      aria-label="Optimize with benchmarks"
      style={{
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <Typography.Title level={4} withoutMargins>
        Optimize with benchmarks
      </Typography.Title>
      <Typography.Text color="secondary">
        Genie answers each benchmark (a test with an expected value), and Genie grades the answer. For a wrong answer,
        the AI suggests one change to the space settings. You examine it. The app updates the space and runs the
        benchmarks again, and keeps the change only if more answers are correct. The app keeps the counts and the grade
        of each question, never the result values. The target is {ACCURACY_TARGET}%.
      </Typography.Text>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Button
          componentId="gsb.tune.run"
          loading={busy === 'run'}
          disabled={!!busy || running || !v.benchmarks || !v.spaceCurrent}
          onClick={() => call<TuningView>('run', 'eval', {}, res.setData)}
        >
          Run the benchmarks ({v.benchmarks})
        </Button>
        {latest && (
          <Tag
            componentId="gsb.tune.accuracy"
            color={pct(latest.numCorrect, latest.numQuestions) >= ACCURACY_TARGET ? 'teal' : 'coral'}
          >
            Accuracy {pct(latest.numCorrect, latest.numQuestions)}% ({latest.numCorrect} of {latest.numQuestions})
          </Tag>
        )}
        {running && (
          <div role="status">
            <Typography.Text color="secondary">
              Genie is answering the benchmarks. This takes some minutes.
            </Typography.Text>
          </div>
        )}
      </div>
      {!v.benchmarks && (
        <Typography.Text>Add tests with an expected value. Each one becomes a benchmark.</Typography.Text>
      )}
      {!!v.benchmarks && !v.spaceCurrent && !running && (
        <Typography.Text>The space does not have the settings of this design. Update the space first.</Typography.Text>
      )}

      {latest && (
        <Table aria-label="Benchmark results">
          <TableRow isHeader>
            <TableHeader componentId="gsb.tune.h_question">Benchmark</TableHeader>
            <TableHeader componentId="gsb.tune.h_result">Genie</TableHeader>
            <TableHeader componentId="gsb.tune.h_action"> </TableHeader>
          </TableRow>
          {latest.results.map((r) => (
            <TableRow key={r.question}>
              <TableCell>{r.question}</TableCell>
              <TableCell>
                <Tag componentId="gsb.tune.assessment" color={ASSESSMENT[r.assessment]?.color ?? 'lemon'}>
                  {ASSESSMENT[r.assessment]?.label ?? r.assessment}
                </Tag>
              </TableCell>
              <TableCell>
                {r.assessment !== 'GOOD' && !open && (
                  <Button
                    componentId="gsb.tune.suggest"
                    size="small"
                    loading={busy === r.question}
                    disabled={!!busy || running}
                    onClick={() =>
                      call<{ tuning: Tuning; config: string }>(
                        r.question,
                        'tuning/suggest',
                        { question: r.question },
                        (x) => {
                          refresh();
                          setExamine(x);
                        }
                      )
                    }
                  >
                    Suggest a change
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </Table>
      )}
      {latest && latest.results.every((r) => r.assessment === 'GOOD') && (
        <Typography.Text>Genie answered each benchmark correctly. Add harder benchmarks to find gaps.</Typography.Text>
      )}

      {open && (
        <Alert
          componentId="gsb.tune.open"
          type="info"
          closable={false}
          message={`AI suggestion for "${open.question}": ${describeChange(open.change)}`}
          description={
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Typography.Text>{open.rationale}</Typography.Text>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button
                  componentId="gsb.tune.examine"
                  type="primary"
                  disabled={!!busy || running}
                  onClick={() =>
                    void api<{ tuning: Tuning; config: string }>(
                      `/api/projects/${projectId}/genie/tuning/${open.id}`
                    ).then(setExamine, (err: unknown) => setError((err as Error).message))
                  }
                >
                  Examine and try
                </Button>
                <Button
                  componentId="gsb.tune.dismiss"
                  disabled={!!busy}
                  onClick={() => call<TuningView>('dismiss', `tuning/${open.id}/dismiss`, {}, res.setData)}
                >
                  Dismiss
                </Button>
              </div>
            </div>
          }
        />
      )}

      {v.tunings.some((t) => t.status !== 'proposed') && (
        <Table aria-label="Changes">
          <TableRow isHeader>
            <TableHeader componentId="gsb.tune.h_change">Change</TableHeader>
            <TableHeader componentId="gsb.tune.h_status">Status</TableHeader>
            <TableHeader componentId="gsb.tune.h_score">Correct answers</TableHeader>
          </TableRow>
          {v.tunings
            .filter((t) => t.status !== 'proposed')
            .map((t) => (
              <TableRow key={t.id}>
                <TableCell>
                  {describeChange(t.change)}
                  {t.error ? ` (${t.error})` : ''}
                </TableCell>
                <TableCell>
                  <Tag componentId="gsb.tune.status" color={TUNING[t.status].color}>
                    {TUNING[t.status].label}
                  </Tag>
                </TableCell>
                <TableCell>
                  {t.beforeCorrect !== null && t.numQuestions !== null
                    ? `${t.beforeCorrect} -> ${t.afterCorrect ?? '...'} of ${t.numQuestions}`
                    : ''}
                </TableCell>
              </TableRow>
            ))}
        </Table>
      )}
      {error && <Alert componentId="gsb.tune.error" type="error" closable={false} message={error} />}

      <Modal
        componentId="gsb.tune.modal"
        title="Try the change"
        visible={!!examine}
        okText="Update the space and run the benchmarks"
        cancelText="Cancel"
        okButtonProps={{ loading: busy === 'apply' }}
        onCancel={() => setExamine(undefined)}
        onOk={() =>
          examine &&
          call<TuningView>('apply', `tuning/${examine.tuning.id}/apply`, { config: examine.config }, (next) => {
            setExamine(undefined);
            res.setData(next);
          })
        }
      >
        {examine && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Typography.Text bold>{describeChange(examine.tuning.change)}</Typography.Text>
            <Typography.Text>{examine.tuning.rationale}</Typography.Text>
            <Alert
              componentId="gsb.tune.warning"
              type="warning"
              closable={false}
              message="This replaces the settings of the Genie space, as you, and runs all benchmarks."
              description="If fewer or the same number of answers are correct, the app puts the settings back."
            />
            <SqlBlock label="Genie space settings with the change (JSON)" sql={examine.config} />
          </div>
        )}
      </Modal>
    </section>
  );
}
