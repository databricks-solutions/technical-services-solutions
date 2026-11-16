import type { MouseEvent, ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { Typography } from '@databricks/design-system';
import type { ProjectDetail, ProjectSummary } from '../../../shared/brief';
import type { PagesView } from '../../../shared/pages';
import type { LibraryRow } from '../../../shared/promote';
import type { ReadinessView } from '../../../shared/readiness';
import { useResource } from '../api';
import { subPath } from '../pages/ProjectsPage';

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

type Go = { href: string; onClick: (e: MouseEvent) => void };

function Fact({ label, id, link, children }: { label: string; id: string; link: Go; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <dt>
        <Typography.Link componentId={`gsb.about.${id}`} href={link.href} onClick={link.onClick}>
          {label}
        </Typography.Link>
      </dt>
      <dd style={{ margin: 0 }}>
        <Typography.Text>{children}</Typography.Text>
      </dd>
    </div>
  );
}

/** The status of a sub-project at a glance, on Overview. Each label opens the place where you change it. */
export function AboutPanel({ parentId, sub }: { parentId: string; sub: ProjectSummary['subProjects'][number] }) {
  const navigate = useNavigate();
  const readiness = useResource<ReadinessView>(`/api/projects/${sub.id}/readiness`);
  const detail = useResource<ProjectDetail>(`/api/projects/${sub.id}`);
  const library = useResource<LibraryRow[]>('/api/library');
  const pages = useResource<PagesView>(`/api/projects/${sub.id}/pages`);

  const brief = detail.data?.brief;
  const row = library.data?.find((r) => r.projectId === sub.id);
  const open = readiness.data?.recommendations.filter((r) => r.status === 'proposed' || r.status === 'failed').length;
  const ahead = row?.promoted ? row.latest.version - row.promoted.version : 0;
  const included = pages.data?.pages.filter((p) => p.include).length ?? 0;

  const go = (to: string) => ({
    href: subPath(parentId, sub.id, to),
    onClick: (e: MouseEvent) => {
      e.preventDefault();
      void navigate(subPath(parentId, sub.id, to));
    },
  });

  return (
    <aside
      aria-label="About"
      style={{
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
        padding: 16,
        position: 'sticky',
        top: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <Typography.Title level={4} withoutMargins>
        About
      </Typography.Title>
      <dl style={{ display: 'flex', flexDirection: 'column', gap: 12, margin: 0 }}>
        <Fact label="Sources" id="sources" link={go('sources')}>
          {plural(sub.sources, 'table')}
          {readiness.data?.score && `, readiness ${readiness.data.score.score} of 100`}
          {open ? `, ${plural(open, 'open fix', 'open fixes')}` : ''}
        </Fact>
        <Fact label="Brief" id="brief" link={go('intake')}>
          {brief ? `Version ${brief.version}, ${brief.status === 'confirmed' ? 'confirmed' : 'draft'}` : 'None yet'}
        </Fact>
        <Fact label="Design" id="design" link={go('designer')}>
          {row
            ? `Version ${row.latest.version}, ${row.latest.status === 'validated' ? 'validated' : 'not validated'}`
            : 'None yet'}
        </Fact>
        <Fact label="Unity Catalog" id="unity_catalog" link={go('publish?section=promotion')}>
          {row?.promoted ? (
            <>
              <span style={{ wordBreak: 'break-all' }}>{row.target}</span>, version {row.promoted.version}
              {ahead > 0 ? `, ${plural(ahead, 'newer version')} not promoted` : ', up to date'}
            </>
          ) : row?.target ? (
            'Target set, not promoted yet'
          ) : (
            'Not published'
          )}
        </Fact>
        <Fact label="Health" id="health" link={go('publish?section=drift')}>
          {row?.health
            ? `${{ ok: 'OK', warning: 'Warnings', error: 'Errors' }[row.health.status]}, ${new Date(row.health.at).toLocaleDateString()}`
            : 'Not checked'}
        </Fact>
        <Fact label="Pages" id="pages" link={go('publish?section=pages')}>
          {pages.data
            ? `${plural(included, 'Page')}, ${pages.data.domain ? `domain ${pages.data.domain}` : 'no domain'}`
            : 'Not available'}
        </Fact>
        <Fact label="Last activity" id="last_activity" link={go('overview')}>
          {new Date(sub.lastActivity).toLocaleString()}
        </Fact>
      </dl>
    </aside>
  );
}
