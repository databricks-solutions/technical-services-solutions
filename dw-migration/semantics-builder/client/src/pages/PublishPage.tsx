import { useOutletContext, useParams } from 'react-router';
import { PromotePanel } from '../components/PromotePanel';
import { PROJECTS_CHANGED } from '../api';
import type { ProjectsResource } from './SubProjectLayout';

/** Publish: promote to Unity Catalog, restore by promoting an older version, owner and grants, drift. */
export function PublishPage() {
  const { projectId = '' } = useParams();
  const projects = useOutletContext<ProjectsResource>();
  return (
    <PromotePanel
      projectId={projectId}
      onPromoted={() => {
        projects.reload();
        window.dispatchEvent(new Event(PROJECTS_CHANGED));
      }}
    />
  );
}
