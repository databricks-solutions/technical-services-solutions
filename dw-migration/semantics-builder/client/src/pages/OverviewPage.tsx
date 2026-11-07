import type { ReactNode } from 'react';
import { useNavigate, useOutletContext, useParams } from 'react-router';
import { ArrowRightIcon, Button, Typography } from '@databricks/design-system';
import type { ProjectDetail } from '../../../shared/brief';
import type { LibraryRow } from '../../../shared/promote';
import type { ReadinessView } from '../../../shared/readiness';
import { useResource } from '../api';
import { NEXT } from '../journey';
import { subPath } from './ProjectsPage';
import type { ProjectsResource } from './SubProjectLayout';

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt style={{ fontWeight: 600 }}>{label}</dt>
      <dd style={{ margin: 0 }}>{children}</dd>
    </>
  );
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

/** The facts of the sub-project that the tabs do not show at a glance, and the one next step. */
export function OverviewPage() {
  const { parentId = '', projectId = '' } = useParams();
  const navigate = useNavigate();
  const projects = useOutletContext<ProjectsResource>();
  const sub = projects.data?.find((p) => p.id === parentId)?.subProjects.find((s) => s.id === projectId);
  const readiness = useResource<ReadinessView>(`/api/projects/${projectId}/readiness`).data;
  const brief = useResource<ProjectDetail>(`/api/projects/${projectId}`).data?.brief;
  const row = useResource<LibraryRow[]>('/api/library').data?.find((r) => r.projectId === projectId);
  if (!sub) return null;
  const next = NEXT[sub.stage];
  const open = readiness?.recommendations.filter((r) => r.status === 'proposed' || r.status === 'failed').length;
  const ahead = row?.promoted ? row.latest.version - row.promoted.version : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 960 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: 16,
          borderRadius: 8,
          background: 'var(--db-surface-subtle)',
        }}
      >
        <div>
          <Typography.Text bold>Next: </Typography.Text>
          <Typography.Text>{next.text}</Typography.Text>
        </div>
        <Button
          componentId="gsb.overview.next"
          type="primary"
          endIcon={<ArrowRightIcon />}
          onClick={() => void navigate(subPath(parentId, projectId, next.module))}
        >
          {next.action}
        </Button>
      </div>
      <dl
        aria-label="Status"
        style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '10px 24px', margin: 0 }}
      >
        <Fact label="Sources">
          {plural(sub.sources, 'table')}
          {readiness?.score && `, readiness ${readiness.score.score} of 100 (80 is ready)`}
          {open ? `, ${plural(open, 'open fix')}` : ''}
        </Fact>
        <Fact label="Brief">
          {brief
            ? `Version ${brief.version}, ${brief.status === 'confirmed' ? 'confirmed' : 'draft to confirm'}`
            : 'None yet'}
        </Fact>
        <Fact label="Design">
          {row
            ? `Version ${row.latest.version}, ${row.latest.status === 'validated' ? 'validated' : 'not validated'}`
            : 'None yet'}
        </Fact>
        <Fact label="Unity Catalog">
          {row?.promoted ? (
            <>
              <code>{row.target}</code>, version {row.promoted.version}
              {ahead > 0 ? `, ${plural(ahead, 'newer version')} not promoted` : ', up to date'}
            </>
          ) : row?.target ? (
            <>
              Target <code>{row.target}</code>, not promoted yet
            </>
          ) : (
            'Not published'
          )}
        </Fact>
        <Fact label="Health">
          {row?.health
            ? `${{ ok: 'OK', warning: 'Warnings', error: 'Errors' }[row.health.status]}, checked ${new Date(row.health.at).toLocaleString()}`
            : 'Not checked'}
        </Fact>
        <Fact label="Last activity">{new Date(sub.lastActivity).toLocaleString()}</Fact>
      </dl>
    </div>
  );
}
