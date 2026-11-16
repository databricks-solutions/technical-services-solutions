import type { MouseEvent } from 'react';
import { useNavigate } from 'react-router';
import { Button, Table, TableCell, TableHeader, TableRow, Tag, Typography } from '@databricks/design-system';
import type { Gate, GoldenView } from '../../../shared/agent';
import { useResource } from '../api';
import { subPath } from '../pages/ProjectsPage';
import { DataState } from './DataState';

function GateRow({ gate, onFix }: { gate: Gate; onFix?: (e: MouseEvent) => void }) {
  return (
    <TableRow>
      <TableCell>{gate.label}</TableCell>
      <TableCell>
        <Tag componentId="gsb.golden.gate" color={gate.pass ? 'teal' : 'coral'}>
          {gate.pass ? 'Pass' : 'Not yet'}
        </Tag>
      </TableCell>
      <TableCell>{gate.detail}</TableCell>
      <TableCell>
        {onFix && !gate.pass && (
          <Typography.Link componentId="gsb.golden.fix" href="#" onClick={onFix}>
            Open
          </Typography.Link>
        )}
      </TableCell>
    </TableRow>
  );
}

/**
 * The golden project path: each sub-project in the Genie agent has certified tables, an approved and promoted view,
 * and Genie accuracy at the target; and the agent is up to date.
 */
export function GoldenPanel({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const res = useResource<GoldenView>(`/api/projects/${projectId}/golden`);
  const g = res.data;
  const open = (sub: string, path: string) => (e: MouseEvent) => {
    e.preventDefault();
    void navigate(subPath(projectId, sub, path));
  };
  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      {g && (
        <section
          aria-label="Golden project"
          style={{
            border: '1px solid var(--db-border-base)',
            borderRadius: 8,
            padding: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography.Title level={3} withoutMargins>
              Golden project
            </Typography.Title>
            <Tag componentId="gsb.golden.status" color={g.golden ? 'teal' : 'default'}>
              {g.golden ? 'Golden' : 'Not golden yet'}
            </Tag>
            <Button componentId="gsb.golden.refresh" size="small" onClick={res.reload}>
              Check again
            </Button>
          </div>
          <Typography.Text color="secondary">
            A golden project goes from certified data to a trusted Genie agent, with a check and a review at each step.
            The gates apply to each sub-project in the Genie agent (before the agent exists: each promoted one). The app
            reads the certification tags as you.
          </Typography.Text>
          {g.subProjects.length === 0 && <Typography.Text>Promote the view of a sub-project first.</Typography.Text>}
          {g.subProjects.map((s) => (
            <Table key={s.projectId} aria-label={`Gates of ${s.name}`}>
              <TableRow isHeader>
                <TableHeader componentId="gsb.golden.h_gate">{s.name}</TableHeader>
                <TableHeader componentId="gsb.golden.h_status">Status</TableHeader>
                <TableHeader componentId="gsb.golden.h_detail">Detail</TableHeader>
                <TableHeader componentId="gsb.golden.h_fix"> </TableHeader>
              </TableRow>
              {s.gates.map((gate) => (
                <GateRow key={gate.id} gate={gate} onFix={gate.fix ? open(s.projectId, gate.fix) : undefined} />
              ))}
            </Table>
          ))}
          <Table aria-label="Project gate">
            <TableRow isHeader>
              <TableHeader componentId="gsb.golden.h_project">Project</TableHeader>
              <TableHeader componentId="gsb.golden.h_pstatus">Status</TableHeader>
              <TableHeader componentId="gsb.golden.h_pdetail">Detail</TableHeader>
              <TableHeader componentId="gsb.golden.h_pfix"> </TableHeader>
            </TableRow>
            <GateRow gate={g.agent} />
          </Table>
        </section>
      )}
    </DataState>
  );
}
