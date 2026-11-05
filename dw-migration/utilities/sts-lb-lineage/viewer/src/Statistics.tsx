import { Button, DownloadIcon, MetricCard, Table, TableCell, TableHeader, TableRow, Typography } from '@databricks/design-system';

import { LEVELS, type Model, downloadCsv } from './data';
import type { Route } from './url';
import { LevelTag, fmt } from './ui';

/** Count with a proportional bar; the number is always shown, so the bar is never the only signal. */
function Bar({ value, max }: { value: number; max: number }) {
  return (
    <span className="lbl-bar-cell">
      <span className="lbl-bar" style={{ width: `${max ? Math.max(2, (value / max) * 100) : 0}%` }} aria-hidden />
      <span className="lbl-bar-num">{fmt(value)}</span>
    </span>
  );
}

function Ranked({
  title,
  hint,
  rows,
  label,
  onOpen,
  componentId,
}: {
  title: string;
  hint?: string;
  rows: { key: string; name: string; count: number }[];
  label: string;
  onOpen?: (key: string) => void;
  componentId: string;
}) {
  const max = Math.max(0, ...rows.map((r) => r.count));
  return (
    <section>
      <Typography.Title level={3}>{title}</Typography.Title>
      {hint && <Typography.Paragraph>{hint}</Typography.Paragraph>}
      {rows.length === 0 ? (
        <Typography.Hint>Not present in this scan.</Typography.Hint>
      ) : (
        <Table size="small">
          <TableRow isHeader>
            <TableHeader componentId={`${componentId}.name`}>{label}</TableHeader>
            <TableHeader componentId={`${componentId}.count`}>Count</TableHeader>
          </TableRow>
          {rows.map((r) => (
            <TableRow key={r.key}>
              <TableCell>
                {onOpen ? (
                  <Typography.Link componentId={`${componentId}.open`} onClick={() => onOpen(r.key)}>
                    {r.name}
                  </Typography.Link>
                ) : (
                  r.name
                )}
              </TableCell>
              <TableCell>
                <Bar value={r.count} max={max} />
              </TableCell>
            </TableRow>
          ))}
        </Table>
      )}
    </section>
  );
}

export function Statistics({ model, go }: { model: Model; go: (r: Partial<Route>) => void }) {
  const s = model.ins.summary;
  const st = model.ins.statistics;
  const c = st.code;
  const name = (id: string) => model.byId.get(id)?.name ?? id;
  const techMax = Math.max(...Object.values(s.technologies));
  const levels = [...LEVELS, 'UNKNOWN'].filter((lv) => s.complexity[lv]);
  const levelMax = Math.max(0, ...levels.map((lv) => s.complexity[lv]));

  return (
    <div className="lbl-tab">
      <div className="lbl-metrics">
        <MetricCard componentId="sts-lb-lineage.st.lines" label="Lines of code" metric={c.lines ? fmt(c.lines) : '-'} comparison="SQL scripts with a line count" />
        <MetricCard componentId="sts-lb-lineage.st.statements" label="SQL statements" metric={fmt((c.statements ?? 0) + (c.embeddedSql ?? 0))} comparison={`${fmt(c.embeddedSql ?? 0)} embedded in ETL jobs`} />
        <MetricCard componentId="sts-lb-lineage.st.dynamic" label="Dynamic SQL" metric={fmt(c.dynamicSql ?? 0)} comparison="Statements built at run time" />
        <MetricCard componentId="sts-lb-lineage.st.loops" label="Loops and cursors" metric={fmt(c.loops ?? 0)} comparison={`${fmt(c.conditionals ?? 0)} conditional blocks`} />
        <MetricCard componentId="sts-lb-lineage.st.params" label="Job parameters" metric={fmt(c.parameters ?? 0)} comparison="Declared on ETL jobs" />
        <MetricCard componentId="sts-lb-lineage.st.size" label="Objects per process" metric={`${st.processSize.median}`} comparison={`Median · min ${st.processSize.min} · max ${st.processSize.max}`} />
      </div>

      <div className="lbl-grid">
        <section>
          <Typography.Title level={3}>Programs by technology</Typography.Title>
          <Table size="small">
            <TableRow isHeader>
              <TableHeader componentId="sts-lb-lineage.st.tech">Technology</TableHeader>
              <TableHeader componentId="sts-lb-lineage.st.tech-n">Programs</TableHeader>
            </TableRow>
            {Object.entries(s.technologies)
              .sort((a, b) => b[1] - a[1])
              .map(([t, n]) => (
                <TableRow key={t}>
                  <TableCell>{t}</TableCell>
                  <TableCell>
                    <Bar value={n} max={techMax} />
                  </TableCell>
                </TableRow>
              ))}
          </Table>
          <Typography.Title level={4}>Complexity level reported by the analyzer</Typography.Title>
          <Table size="small">
            <TableRow isHeader>
              <TableHeader componentId="sts-lb-lineage.st.lv">Level</TableHeader>
              <TableHeader componentId="sts-lb-lineage.st.lv-n">Programs</TableHeader>
            </TableRow>
            {levels.map((lv) => (
              <TableRow key={lv}>
                <TableCell>
                  <LevelTag level={lv} />
                </TableCell>
                <TableCell>
                  <Bar value={s.complexity[lv]} max={levelMax} />
                </TableCell>
              </TableRow>
            ))}
          </Table>
        </section>

        <Ranked
          title="Program types"
          componentId="sts-lb-lineage.st.types"
          label="Type"
          rows={Object.entries(st.programTypes).map(([k, v]) => ({ key: k, name: k, count: v }))}
        />
        <Ranked
          title="Most used transformations"
          hint="Component counts across all ETL jobs."
          componentId="sts-lb-lineage.st.trans"
          label="Transformation"
          rows={st.transformations.map((t) => ({ key: t.name, name: t.name, count: t.count }))}
        />
        <Ranked
          title="Most used functions"
          componentId="sts-lb-lineage.st.func"
          label="Function"
          rows={st.functions.map((t) => ({ key: t.name, name: t.name, count: t.count }))}
        />
        <Ranked
          title="Most read tables"
          hint="Tables that feed the most other tables."
          componentId="sts-lb-lineage.st.fanout"
          label="Table"
          rows={st.fanOut.map((t) => ({ key: t.id, name: name(t.id), count: t.count }))}
          onOpen={(id) => go({ obj: id })}
        />
        <Ranked
          title="Most fed tables"
          hint="Tables built from the most other tables."
          componentId="sts-lb-lineage.st.fanin"
          label="Table"
          rows={st.fanIn.map((t) => ({ key: t.id, name: name(t.id), count: t.count }))}
          onOpen={(id) => go({ obj: id })}
        />
        <Ranked
          title="Tables by schema"
          componentId="sts-lb-lineage.st.schema"
          label="Schema"
          rows={st.schemas.map((t) => ({ key: t.name, name: t.name, count: t.count }))}
          onOpen={(k) => go({ tab: 'objects', q: `schema:${k}` })}
        />
      </div>
      <div className="lbl-row">
        <Button
          componentId="sts-lb-lineage.st.export"
          icon={<DownloadIcon />}
          onClick={() =>
            downloadCsv(
              'process_summary.csv',
              ['process', 'tech', 'programs', 'objects', 'max_complexity', 'depends_on', 'feeds', 'in_cycle'],
              model.ins.processes.map((p) => [
                p.name,
                p.tech.join('|'),
                p.programs.length,
                p.objects.length,
                p.maxComplexity,
                p.upstream.length,
                p.downstream.length,
                p.cycle === null ? 'no' : 'yes',
              ]),
            )
          }
        >
          Download process summary (CSV)
        </Button>
      </div>
    </div>
  );
}
