import { useNavigate, useOutletContext, useParams } from 'react-router';
import { ArrowRightIcon, Button, Typography } from '@databricks/design-system';
import { AboutPanel } from '../components/AboutPanel';
import { NEXT } from '../journey';
import { subPath } from './ProjectsPage';
import type { ProjectsResource } from './SubProjectLayout';

/** The next step of the sub-project, and the About box with the status of each step. */
export function OverviewPage() {
  const { parentId = '', projectId = '' } = useParams();
  const navigate = useNavigate();
  const projects = useOutletContext<ProjectsResource>();
  const sub = projects.data?.find((p) => p.id === parentId)?.subProjects.find((s) => s.id === projectId);
  if (!sub) return null;
  const next = NEXT[sub.stage];

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div style={{ flex: '1 1 560px', display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
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
        <Typography.Text color="secondary">
          The About box shows the status of each step. Select a label in it to open that step.
        </Typography.Text>
      </div>
      <div style={{ flex: '0 0 300px' }}>
        <AboutPanel parentId={parentId} sub={sub} />
      </div>
    </div>
  );
}
