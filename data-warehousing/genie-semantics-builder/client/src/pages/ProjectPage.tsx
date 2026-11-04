import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Button, Card, PlusIcon, Stepper, Typography } from '@databricks/design-system';
import type { ProjectSummary, SubProjectStage, SubProjectSummary } from '../../../shared/brief';
import { useResource } from '../api';
import { DataState } from '../components/DataState';
import { NewProjectModal, STAGE, subPath } from './ProjectsPage';

const ORDER: SubProjectStage[] = ['intent', 'sources', 'design', 'validated'];
const STEPS = ['Intent', 'Sources', 'Design', 'Validated'];

function SubProjectCard({ parentId, sub }: { parentId: string; sub: SubProjectSummary }) {
  const navigate = useNavigate();
  const at = ORDER.indexOf(sub.stage);
  return (
    <Card
      componentId="gsb.project.sub_card"
      onClick={() => void navigate(subPath(parentId, sub.id, STAGE[sub.stage].module))}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <Typography.Title level={4} withoutMargins>
            {sub.name}
          </Typography.Title>
          <Typography.Text color="secondary">{sub.description ?? 'No goal yet.'}</Typography.Text>
        </div>
        <Stepper
          currentStepIndex={sub.stage === 'validated' ? ORDER.length : at}
          steps={STEPS.map((title, i) => ({
            title,
            status: i < at || sub.stage === 'validated' ? 'completed' : undefined,
          }))}
          localizeStepNumber={(n) => String(n)}
          responsive={false}
        />
        <Typography.Text color="secondary">
          {sub.sources} source{sub.sources === 1 ? '' : 's'}, last activity{' '}
          {new Date(sub.lastActivity).toLocaleString()}
        </Typography.Text>
      </div>
    </Card>
  );
}

export function ProjectPage() {
  const { parentId = '' } = useParams();
  const navigate = useNavigate();
  const projects = useResource<ProjectSummary[]>('/api/projects');
  const [creating, setCreating] = useState(false);
  const project = projects.data?.find((p) => p.id === parentId);
  const status = projects.status === 'ready' && !project ? 'error' : projects.status;
  const newButton = (
    <Button componentId="gsb.project.new_sub" type="primary" icon={<PlusIcon />} onClick={() => setCreating(true)}>
      New sub-project
    </Button>
  );

  return (
    <DataState status={status} message={projects.error ?? 'Project not found.'} onRetry={projects.reload}>
      {project && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
            <div>
              <Typography.Title level={2} withoutMargins>
                {project.name}
              </Typography.Title>
              <Typography.Text color="secondary">{project.description ?? 'No business goal yet.'}</Typography.Text>
            </div>
            {newButton}
          </div>
          {project.subProjects.length ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 16 }}>
              {project.subProjects.map((s) => (
                <SubProjectCard key={s.id} parentId={project.id} sub={s} />
              ))}
            </div>
          ) : (
            <DataState
              status="empty"
              message="A sub-project builds one metric view, for example Revenue or Returns. The AI guides you from intent to a validated design."
              emptyAction={newButton}
            />
          )}
          {creating && (
            <NewProjectModal
              title="New sub-project"
              okText="Create sub-project"
              endpoint={`/api/projects/${project.id}/subprojects`}
              goalHint="Which questions should this metric view answer? For example: net revenue by month and region."
              onClose={() => setCreating(false)}
              onCreated={(s) => void navigate(subPath(project.id, s.id, 'intake'))}
            />
          )}
        </div>
      )}
    </DataState>
  );
}
