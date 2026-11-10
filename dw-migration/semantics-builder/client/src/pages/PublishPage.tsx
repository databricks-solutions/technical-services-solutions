import { useOutletContext, useParams } from 'react-router';
import { PagesPanel } from '../components/PagesPanel';
import { PromotePanel } from '../components/PromotePanel';
import { PROJECTS_CHANGED } from '../api';
import type { ProjectsResource } from './SubProjectLayout';

/** Publish: promote to Unity Catalog, restore by promoting an older version, owner and grants, drift. */
export function PublishPage() {
  const { projectId = '' } = useParams();
  const projects = useOutletContext<ProjectsResource>();
  const sub = projects.data
    ?.flatMap((p) => p.subProjects.map((s) => ({ ...s, project: p.name })))
    .find((s) => s.id === projectId);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
      <PromotePanel
        projectId={projectId}
        onPromoted={() => {
          projects.reload();
          window.dispatchEvent(new Event(PROJECTS_CHANGED));
        }}
      />
      <PagesPanel projectId={projectId} title={sub ? `${sub.project} ${sub.name}` : 'semantics'} />
    </div>
  );
}
