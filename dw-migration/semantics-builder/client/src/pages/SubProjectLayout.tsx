import type { MouseEvent } from 'react';
import { Outlet, useLocation, useNavigate, useOutletContext, useParams } from 'react-router';
import { Tabs, Tag, Typography } from '@databricks/design-system';
import type { ProjectSummary } from '../../../shared/brief';
import type { useResource } from '../api';
import { MARK_TEXT, MODULES, Mark, SR_ONLY, STAGE, markOf } from '../journey';
import type { ModuleSlug } from '../journey';
import { subPath } from './ProjectsPage';

export type ProjectsResource = ReturnType<typeof useResource<ProjectSummary[]>>;

/** A sub-project: breadcrumb, name, stage and next step, then one tab per module. Each tab is a route. */
export function SubProjectLayout() {
  const { parentId = '', projectId = '' } = useParams();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const projects = useOutletContext<ProjectsResource>();
  const project = projects.data?.find((p) => p.id === parentId);
  const sub = project?.subProjects.find((s) => s.id === projectId);
  const slug = pathname.split('/').pop() ?? 'overview';
  // Modeling patterns is a step inside the Metric Designer, not a tab of its own.
  const active: ModuleSlug =
    slug === 'patterns' ? 'designer' : (MODULES.find((m) => m.slug === slug)?.slug ?? 'overview');
  const go = (path: string) => (e: MouseEvent) => {
    e.preventDefault();
    void navigate(path);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <nav aria-label="Breadcrumb">
        <Typography.Text color="secondary" size="sm">
          <Typography.Link componentId="gsb.crumb.projects" href="/" onClick={go('/')}>
            Projects
          </Typography.Link>
          {' / '}
          <Typography.Link
            componentId="gsb.crumb.project"
            href={`/projects/${parentId}`}
            onClick={go(`/projects/${parentId}`)}
          >
            {project?.name ?? 'Project'}
          </Typography.Link>
          {' / '}
          <span aria-current="page">{sub?.name ?? 'Sub-project'}</span>
        </Typography.Text>
      </nav>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Typography.Title level={2} withoutMargins>
          {sub?.name ?? 'Sub-project'}
        </Typography.Title>
        {sub && (
          <Tag componentId="gsb.sub.stage" color={STAGE[sub.stage].color}>
            {STAGE[sub.stage].label}
          </Tag>
        )}
      </div>
      {sub?.description && <Typography.Text color="secondary">{sub.description}</Typography.Text>}
      <Tabs.Root
        componentId="gsb.sub.tabs"
        value={active}
        onValueChange={(v) => void navigate(subPath(parentId, projectId, v))}
      >
        <Tabs.List>
          {MODULES.map((m) => {
            const mark = sub ? markOf(m.slug, sub.stage) : 'open';
            return (
              <Tabs.Trigger key={m.slug} value={m.slug}>
                <span title={m.hint} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {m.label}
                  <Mark mark={mark} />
                  <span style={SR_ONLY}>{MARK_TEXT[mark]}</span>
                </span>
              </Tabs.Trigger>
            );
          })}
        </Tabs.List>
      </Tabs.Root>
      <section aria-label={MODULES.find((m) => m.slug === active)?.label} style={{ paddingTop: 4 }}>
        <Outlet context={projects} />
      </section>
    </div>
  );
}
