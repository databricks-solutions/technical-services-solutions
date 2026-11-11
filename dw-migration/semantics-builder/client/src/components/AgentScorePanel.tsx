import { useEffect } from 'react';
import type { MouseEvent } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Table, TableCell, TableHeader, TableRow, Tag, Typography } from '@databricks/design-system';
import type { AgentScore } from '../../../shared/genie';
import { useResource } from '../api';
import { subPath } from '../pages/ProjectsPage';

const STATUS = {
  pass: { color: 'teal', label: 'Pass' },
  warn: { color: 'lemon', label: 'Warning' },
  fail: { color: 'coral', label: 'Fail' },
} as const;

/** The score of the Genie agent from the design and the space settings, with the page to open for each gap. */
export function AgentScorePanel({ projectId, refreshKey }: { projectId: string; refreshKey: string }) {
  const { parentId = '' } = useParams();
  const navigate = useNavigate();
  const res = useResource<AgentScore | null>(`/api/projects/${projectId}/genie/score`);
  const { refresh } = res;
  // The score changes when the space is created or updated.
  useEffect(() => refresh(), [refreshKey, refresh]);
  const s = res.data;
  if (!s) return null;
  const open = (path: string) => (e: MouseEvent) => {
    e.preventDefault();
    void navigate(subPath(parentId, projectId, path));
  };
  return (
    <section
      aria-label="Genie agent score"
      style={{
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
        <Typography.Title level={4} withoutMargins>
          Genie agent score
        </Typography.Title>
        <Typography.Title level={3} withoutMargins>
          {s.score}
        </Typography.Title>
        <Tag componentId="gsb.agent.score" color={s.score >= 80 ? 'teal' : s.score >= 50 ? 'lemon' : 'coral'}>
          {s.score >= 80 ? 'Ready' : 'Not ready'}
        </Tag>
      </div>
      <Typography.Text color="secondary">
        Rule-based, from the design, the brief, the tests and the space settings. 80 or more is ready. A pass counts one
        point, a warning half a point.
      </Typography.Text>
      <Table aria-label="Genie agent checks">
        <TableRow isHeader>
          <TableHeader componentId="gsb.agent.h_check">Check</TableHeader>
          <TableHeader componentId="gsb.agent.h_result">Result</TableHeader>
          <TableHeader componentId="gsb.agent.h_detail">Detail</TableHeader>
          <TableHeader componentId="gsb.agent.h_fix">Fix</TableHeader>
        </TableRow>
        {s.checks.map((c) => (
          <TableRow key={c.id}>
            <TableCell>{c.label}</TableCell>
            <TableCell>
              <Tag componentId="gsb.agent.check" color={STATUS[c.status].color}>
                {STATUS[c.status].label}
              </Tag>
            </TableCell>
            <TableCell>{c.detail}</TableCell>
            <TableCell>
              {c.fix && c.status !== 'pass' && (
                <Typography.Link
                  componentId="gsb.agent.fix"
                  href={subPath(parentId, projectId, c.fix.path)}
                  onClick={open(c.fix.path)}
                >
                  {c.fix.label}
                </Typography.Link>
              )}
            </TableCell>
          </TableRow>
        ))}
      </Table>
    </section>
  );
}
