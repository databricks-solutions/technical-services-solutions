import { MetricCard, Table, TableCell, TableHeader, TableRow, Typography } from '@databricks/design-system';
import { useMemo } from 'react';

import { LEVELS, type Model, schemaOf, shortName } from './data';
import type { Route } from './url';
import { LevelTag, ROLE_HELP, fmt, plural, roleLabel } from './ui';

const TRUST: { key: string; label: string; help: string }[] = [
  { key: 'statementGrainEdges', label: 'Statement-level edges', help: 'Derived from one SQL statement. High confidence.' },
  { key: 'jobGrainEdges', label: 'Job-level edges', help: 'All inputs x all outputs of a job. May over-link multi-flow jobs.' },
  { key: 'unqualifiedTables', label: 'Unqualified table names', help: 'No schema prefix. May be aliases, variables, or ETL instance names.' },
  { key: 'tempTables', label: 'Temporary tables', help: '@ or # names, kept to preserve chains.' },
  { key: 'programsWithoutLineage', label: 'Programs without lineage', help: 'Scanned, but no read or write relations found.' },
  { key: 'offSchemaComplexity', label: 'Off-schema complexity values', help: 'The analyzer emitted a level outside its schema (for example COMPLEX).' },
];

export function Overview({ model, go }: { model: Model; go: (r: Partial<Route>) => void }) {
  const s = model.ins.summary;
  const st = model.ins.statistics;
  const procs = model.ins.processes;

  const sourcesBySchema = useMemo(() => {
    const m = new Map<string, { tables: number; readers: Set<string> }>();
    for (const n of model.doc.nodes) {
      if (n.role !== 'source') continue;
      const k = schemaOf(n);
      const v = m.get(k) ?? { tables: 0, readers: new Set<string>() };
      v.tables += 1;
      for (const { program } of model.programsOf.get(n.id) ?? []) {
        const pr = model.processOfProgram.get(program.name);
        if (pr) v.readers.add(pr);
      }
      m.set(k, v);
    }
    return [...m.entries()].sort((a, b) => b[1].tables - a[1].tables).slice(0, 10);
  }, [model]);

  const rank = (lv: string) => LEVELS.indexOf(lv as (typeof LEVELS)[number]);
  const connected = [...procs]
    .filter((p) => p.upstream.length + p.downstream.length > 0)
    .sort((a, b) => b.upstream.length + b.downstream.length - (a.upstream.length + a.downstream.length) || rank(b.maxComplexity) - rank(a.maxComplexity))
    .slice(0, 10);

  return (
    <div className="lbl-tab lbl-overview">
      <div className="lbl-metrics">
        <MetricCard fullHeight pinButtonToBottom componentId="sts-lb-lineage.ov.processes" label="Processes" metric={fmt(s.processes)} comparison="Top-level workflows, sequences, and scripts" buttonText="Process map" onButtonClick={() => go({ tab: 'processes' })} />
        <MetricCard fullHeight pinButtonToBottom componentId="sts-lb-lineage.ov.programs" label="Programs" metric={fmt(s.programs)} comparison={Object.entries(s.technologies).map(([t, n]) => `${t} ${n}`).join(' · ')} buttonText="Statistics" onButtonClick={() => go({ tab: 'statistics' })} />
        <MetricCard fullHeight pinButtonToBottom componentId="sts-lb-lineage.ov.tables" label="Tables" metric={fmt(s.tables)} comparison={`${fmt(s.roles.source)} sources · ${fmt(s.roles.terminal)} outputs`} buttonText="Objects" onButtonClick={() => go({ tab: 'objects', q: undefined })} />
        <MetricCard fullHeight pinButtonToBottom componentId="sts-lb-lineage.ov.hubs" label="Shared tables" metric={fmt(s.hubs)} comparison="Read or written by more than one process" buttonText="Show them" onButtonClick={() => go({ tab: 'objects', q: 'role:shared' })} />
        <MetricCard fullHeight pinButtonToBottom componentId="sts-lb-lineage.ov.links" label="Process dependencies" metric={fmt(st.crossProcessLinks)} comparison={`${plural(st.selfContainedProcesses, 'process', 'processes')} share no tables`} />
        <MetricCard fullHeight pinButtonToBottom componentId="sts-lb-lineage.ov.cycles" label="Dependency cycles" metric={fmt(s.cycles)} comparison={s.cycles ? 'Processes that feed each other' : 'No process feeds itself'} />
      </div>

      <div className="lbl-grid">
        <section>
          <Typography.Title level={3}>Object roles</Typography.Title>
          <Table size="small">
            <TableRow isHeader>
              <TableHeader componentId="sts-lb-lineage.ov.r">Role</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.r-n" align="right" style={{ maxWidth: 100 }}>Tables</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.r-h">What it means</TableHeader>
            </TableRow>
            {(['source', 'intermediate', 'terminal', 'orphan'] as const).map((r) => (
              <TableRow key={r}>
                <TableCell>
                  <Typography.Link componentId="sts-lb-lineage.ov.role" onClick={() => go({ tab: 'objects', q: `role:${r}` })}>
                    {roleLabel(r)}
                  </Typography.Link>
                </TableCell>
                <TableCell align="right" style={{ maxWidth: 100 }}>{fmt(s.roles[r] ?? 0)}</TableCell>
                <TableCell multiline>{ROLE_HELP[r]}</TableCell>
              </TableRow>
            ))}
          </Table>
          <Typography.Title level={4}>Sources to ingest, by schema</Typography.Title>
          <Table size="small">
            <TableRow isHeader>
              <TableHeader componentId="sts-lb-lineage.ov.s">Schema</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.s-n" align="right">Tables</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.s-p" align="right">Reading processes</TableHeader>
            </TableRow>
            {sourcesBySchema.map(([k, v]) => (
              <TableRow key={k}>
                <TableCell>
                  <Typography.Link componentId="sts-lb-lineage.ov.schema" onClick={() => go({ tab: 'objects', q: `role:source schema:${k}` })}>
                    {k}
                  </Typography.Link>
                </TableCell>
                <TableCell align="right">{fmt(v.tables)}</TableCell>
                <TableCell align="right">{fmt(v.readers.size)}</TableCell>
              </TableRow>
            ))}
          </Table>
        </section>

        <section>
          <Typography.Title level={3}>Most shared tables</Typography.Title>
          <Typography.Paragraph>Contracts between processes: each one links the processes that write and read it.</Typography.Paragraph>
          <Table size="small">
            <TableRow isHeader>
              <TableHeader componentId="sts-lb-lineage.ov.h">Table</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.h-n" align="right">Processes</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.h-w" align="right">Writers</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.h-r" align="right">Readers</TableHeader>
            </TableRow>
            {model.ins.hubs.slice(0, 10).map((h) => (
              <TableRow key={h.id}>
                <TableCell>
                  <Typography.Link componentId="sts-lb-lineage.ov.hub" onClick={() => go({ obj: h.id })}>
                    {model.byId.get(h.id)?.name}
                  </Typography.Link>
                </TableCell>
                <TableCell align="right">{h.processCount}</TableCell>
                <TableCell align="right">{h.writers.length}</TableCell>
                <TableCell align="right">{h.readers.length}</TableCell>
              </TableRow>
            ))}
          </Table>
        </section>

        <section>
          <Typography.Title level={3}>Most connected processes</Typography.Title>
          <Typography.Paragraph>Processes with the most dependencies on other processes.</Typography.Paragraph>
          <Table size="small">
            <TableRow isHeader>
              <TableHeader componentId="sts-lb-lineage.ov.c">Process</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.c-u" align="right">Depends on</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.c-d" align="right">Feeds</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.c-l">Highest complexity</TableHeader>
            </TableRow>
            {connected.map((p) => (
              <TableRow key={p.name}>
                <TableCell>
                  <Typography.Link componentId="sts-lb-lineage.ov.cproc" onClick={() => go({ proc: p.name })}>
                    <span title={p.name}>{shortName(p.name)}</span>
                  </Typography.Link>
                </TableCell>
                <TableCell align="right">{p.upstream.length}</TableCell>
                <TableCell align="right">{p.downstream.length}</TableCell>
                <TableCell>
                  <LevelTag level={p.maxComplexity} />
                </TableCell>
              </TableRow>
            ))}
          </Table>
          {connected.length === 0 && <Typography.Hint>No process depends on another one.</Typography.Hint>}
        </section>

        <section>
          <Typography.Title level={3}>How far to trust this map</Typography.Title>
          <Table size="small">
            <TableRow isHeader>
              <TableHeader componentId="sts-lb-lineage.ov.t">Check</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.t-n" align="right" style={{ maxWidth: 100 }}>Count</TableHeader>
              <TableHeader componentId="sts-lb-lineage.ov.t-h">Meaning</TableHeader>
            </TableRow>
            {TRUST.map((t) => (
              <TableRow key={t.key}>
                <TableCell>{t.label}</TableCell>
                <TableCell align="right" style={{ maxWidth: 100 }}>{fmt(model.ins.trust[t.key] ?? 0)}</TableCell>
                <TableCell multiline>{t.help}</TableCell>
              </TableRow>
            ))}
          </Table>
        </section>
      </div>
    </div>
  );
}
