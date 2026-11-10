import type { MouseEvent } from 'react';
import { useOutletContext, useParams } from 'react-router';
import { NavList, Typography } from '@databricks/design-system';
import type { PagesView } from '../../../shared/pages';
import type { PromotionView } from '../../../shared/promote';
import { DriftPanel } from '../components/DriftPanel';
import { GovernPanel } from '../components/GovernPanel';
import { PagesPanel } from '../components/PagesPanel';
import { PromotePanel } from '../components/PromotePanel';
import { PROJECTS_CHANGED, useResource } from '../api';
import { useTab } from '../useTab';
import type { ProjectsResource } from './SubProjectLayout';

const SECTIONS = ['promotion', 'governance', 'drift', 'pages'] as const;
type Section = (typeof SECTIONS)[number];

/** Publish: one task at a time, chosen in the left pane. Promote, owner and grants, drift, and Pages for Discover. */
export function PublishPage() {
  const { projectId = '' } = useParams();
  const projects = useOutletContext<ProjectsResource>();
  const [section, setSection] = useTab(SECTIONS, 'promotion', 'section');
  const promotion = useResource<PromotionView>(`/api/projects/${projectId}/promotion`);
  const pages = useResource<PagesView>(`/api/projects/${projectId}/pages`).data;
  const sub = projects.data
    ?.flatMap((p) => p.subProjects.map((s) => ({ ...s, project: p.name })))
    .find((s) => s.id === projectId);
  const last = promotion.data?.promotions.find((p) => p.status === 'succeeded');
  const included = pages?.pages.filter((p) => p.include).length;

  const items: { id: Section; label: string; hint: string }[] = [
    { id: 'promotion', label: 'Promotion', hint: last ? `Version ${last.version} in Unity Catalog` : 'Not promoted' },
    { id: 'governance', label: 'Governance', hint: last ? 'Owner and read access' : 'After the first promotion' },
    { id: 'drift', label: 'Drift', hint: last ? 'Changes made outside the app' : 'After the first promotion' },
    { id: 'pages', label: 'Pages', hint: included === undefined ? 'For Discover' : `${included} for Discover` },
  ];
  const go = (id: Section) => (e: MouseEvent) => {
    e.preventDefault();
    setSection(id);
  };
  const notYet = (
    <Typography.Text color="secondary">
      Promote the view first. Then you set the owner and who can read it, and check it for drift (changes made outside
      the app, or in the source tables).
    </Typography.Text>
  );

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div style={{ flex: '0 0 200px' }}>
        <NavList.Root aria-label="Publish tasks">
          <NavList.Group>
            <NavList.GroupContent>
              <NavList.List>
                {items.map((i) => (
                  <NavList.Item key={i.id}>
                    <NavList.Link
                      href={`?section=${i.id}`}
                      active={section === i.id}
                      label={i.label}
                      onClick={go(i.id)}
                    />
                    <div style={{ padding: '0 12px 6px' }}>
                      <Typography.Text color="secondary" size="sm">
                        {i.hint}
                      </Typography.Text>
                    </div>
                  </NavList.Item>
                ))}
              </NavList.List>
            </NavList.GroupContent>
          </NavList.Group>
        </NavList.Root>
      </div>
      <div style={{ flex: '1 1 480px', minWidth: 0 }}>
        {section === 'promotion' && (
          <PromotePanel
            projectId={projectId}
            onPromoted={() => {
              projects.reload();
              promotion.refresh();
              window.dispatchEvent(new Event(PROJECTS_CHANGED));
            }}
          />
        )}
        {section === 'governance' && (last ? <GovernPanel key={last.id} projectId={projectId} /> : notYet)}
        {section === 'drift' && (last ? <DriftPanel key={last.id} projectId={projectId} /> : notYet)}
        {section === 'pages' && (
          <PagesPanel projectId={projectId} title={sub ? `${sub.project} ${sub.name}` : 'semantics'} />
        )}
      </div>
    </div>
  );
}
