import {
  Button,
  DownloadIcon,
  Empty,
  Input,
  SearchIcon,
  SegmentedControlButton,
  SegmentedControlGroup,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
  WorkflowsIcon,
} from '@databricks/design-system';
import { useMemo, useState } from 'react';

import { type Model, SHARED, downloadCsv, pathBetween, shortName, walk } from './data';
import { GraphView } from './Graph';
import type { Route } from './url';
import { KindIcon, LevelTag, plural, roleLabel } from './ui';

const MAX_ROWS = 200;

/** "proc:<name>" or a node id -> the node ids it stands for. */
function startIds(model: Model, target: string, side: 'up' | 'down'): string[] {
  if (!target.startsWith('proc:')) return model.byId.has(target) ? [target] : [];
  const name = target.slice(5);
  const p = model.procByName.get(name);
  if (!p) return [];
  const hubs = model.ins.hubs.filter((h) => (side === 'down' ? h.writers : h.readers).includes(name)).map((h) => h.id);
  return [...p.objects, ...hubs];
}

const targetLabel = (model: Model, t: string) => (t.startsWith('proc:') ? shortName(t.slice(5)) : model.byId.get(t)?.name ?? t);

/** Processes first, then tables and jobs; "proc:<name>" or a node id. */
export function searchTargets(model: Model, q: string): string[] {
  const s = q.trim().toLowerCase();
  if (s.length < 2) return [];
  const procs = model.ins.processes.filter((p) => p.name.toLowerCase().includes(s)).slice(0, 5).map((p) => `proc:${p.name}`);
  const objs = model.doc.nodes.filter((n) => n.name.toLowerCase().includes(s)).slice(0, 8).map((n) => n.id);
  return [...procs, ...objs];
}

function Hits({ model, hits, label, onPick }: { model: Model; hits: string[]; label: string; onPick: (h: string) => void }) {
  if (!hits.length) return null;
  return (
    <ul className="lbl-hits" aria-label={`${label} suggestions`}>
      {hits.map((h) => (
        <li key={h}>
          {h.startsWith('proc:') ? <WorkflowsIcon aria-hidden /> : <KindIcon kind={model.byId.get(h)!.kind} />}
          <Typography.Link componentId="sts-lb-lineage.search.hit" onClick={() => onPick(h)}>
            {h.startsWith('proc:') ? `Process ${shortName(h.slice(5))}` : model.byId.get(h)!.name}
          </Typography.Link>
        </li>
      ))}
    </ul>
  );
}

/** Header search: jump to any process, table, or job. */
export function QuickFind({ model, onPick }: { model: Model; onPick: (target: string) => void }) {
  const [q, setQ] = useState('');
  const hits = useMemo(() => searchTargets(model, q), [model, q]);
  return (
    <div className="lbl-picker lbl-quickfind">
      <Input
        componentId="sts-lb-lineage.quickfind"
        prefix={<SearchIcon />}
        placeholder="Find a process, table, or job"
        aria-label="Find a process, table, or job"
        allowClear
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onPressEnter={() => hits[0] && (onPick(hits[0]), setQ(''))}
      />
      <div className="lbl-hits-float">
        <Hits
          model={model}
          hits={hits}
          label="Find"
          onPick={(h) => {
            setQ('');
            onPick(h);
          }}
        />
      </div>
    </div>
  );
}

function Picker({ model, label, value, onChange }: { model: Model; label: string; value?: string; onChange: (v?: string) => void }) {
  const [q, setQ] = useState('');
  const hits = useMemo(() => searchTargets(model, q), [model, q]);
  if (value)
    return (
      <div className="lbl-row">
        <Typography.Text bold>{label}</Typography.Text>
        <Tag componentId="sts-lb-lineage.impact.target" closable onClose={() => onChange(undefined)}>
          {`${value.startsWith('proc:') ? 'Process' : 'Object'}: ${targetLabel(model, value)}`}
        </Tag>
      </div>
    );
  return (
    <div className="lbl-picker">
      <Input
        componentId={`sts-lb-lineage.impact.pick-${label.toLowerCase()}`}
        prefix={<SearchIcon />}
        placeholder={`${label}: type 2+ letters of a table, job, or process`}
        aria-label={label}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <Hits
        model={model}
        hits={hits}
        label={label}
        onPick={(h) => {
          setQ('');
          onChange(h);
        }}
      />
    </div>
  );
}

export function Impact({
  model,
  route,
  go,
  onOpen,
  onOpenProcess,
}: {
  model: Model;
  route: Route;
  go: (r: Partial<Route>) => void;
  onOpen: (id: string) => void;
  onOpenProcess: (name: string) => void;
}) {
  const mode = route.mode ?? 'down';
  const result = useMemo(() => {
    if (!route.target) return null;
    if (mode === 'path') {
      if (!route.to) return null;
      const nodes = pathBetween(model, startIds(model, route.target, 'down'), startIds(model, route.to, 'up'));
      return { hops: new Map([...nodes].map((n) => [n, 0])), start: new Set<string>() };
    }
    const start = startIds(model, route.target, mode);
    const hops = walk(model, start, mode);
    return { hops, start: new Set(start) };
  }, [model, route.target, route.to, mode]);

  const objects = useMemo(() => {
    if (!result) return [];
    return [...result.hops.entries()]
      .filter(([id]) => !result.start.has(id))
      .map(([id, h]) => ({ n: model.byId.get(id)!, h }))
      .sort((a, b) => a.h - b.h || a.n.name.localeCompare(b.n.name));
  }, [model, result]);

  const processes = useMemo(() => {
    const m = new Map<string, { objects: number; hops: number }>();
    const own = route.target?.startsWith('proc:') ? route.target.slice(5) : null;
    const add = (p: string, h: number) => {
      if (p === own || !model.procByName.has(p)) return;
      const v = m.get(p) ?? { objects: 0, hops: h };
      v.objects += 1;
      v.hops = Math.min(v.hops, h);
      m.set(p, v);
    };
    for (const { n, h } of objects) {
      if (n.process && n.process !== SHARED) add(n.process, h);
      const hub = model.hubById.get(n.id);
      if (hub) (mode === 'up' ? hub.writers : hub.readers).forEach((p) => add(p, h));
    }
    return [...m.entries()].map(([name, v]) => ({ p: model.procByName.get(name)!, ...v })).sort((a, b) => a.hops - b.hops || a.p.name.localeCompare(b.p.name));
  }, [model, objects, mode, route.target]);

  const scope = useMemo(() => (result ? [...result.hops.keys()] : []), [result]);
  const verb = mode === 'down' ? 'Affected' : mode === 'up' ? 'Upstream' : 'On the path';

  return (
    <div className="lbl-tab">
      <div className="lbl-toolbar">
        <SegmentedControlGroup componentId="sts-lb-lineage.impact.mode" name="impact-mode" value={mode} onChange={(e) => go({ mode: e.target.value })}>
          <SegmentedControlButton value="down">Downstream impact</SegmentedControlButton>
          <SegmentedControlButton value="up">Upstream sources</SegmentedControlButton>
          <SegmentedControlButton value="path">Path between</SegmentedControlButton>
        </SegmentedControlGroup>
      </div>
      <Typography.Paragraph>
        {mode === 'down'
          ? 'What breaks if this object or process changes or moves: every downstream table, job, and process.'
          : mode === 'up'
            ? 'Everything this object or process depends on: the sources and processes that must exist first.'
            : 'Only the objects on some path between two objects or processes.'}
      </Typography.Paragraph>
      <div className="lbl-pickers">
        <Picker model={model} label={mode === 'path' ? 'From' : 'Target'} value={route.target} onChange={(v) => go({ target: v })} />
        {mode === 'path' && <Picker model={model} label="To" value={route.to} onChange={(v) => go({ to: v })} />}
      </div>

      {!result ? (
        <Empty title="Pick a target" description="Search for a table, job, or process to analyze." />
      ) : scope.length === 0 || (mode !== 'path' && objects.length === 0) ? (
        <Empty title="Nothing found" description={mode === 'path' ? 'No path connects these two.' : 'No lineage in this direction.'} />
      ) : (
        <>
          <div className="lbl-row">
            <Tag componentId="sts-lb-lineage.impact.n-proc">{plural(processes.length, 'process', 'processes')}</Tag>
            <Tag componentId="sts-lb-lineage.impact.n-obj">{plural(objects.length, 'object')}</Tag>
            <Button
              componentId="sts-lb-lineage.impact.export"
              icon={<DownloadIcon />}
              onClick={() =>
                downloadCsv(
                  `impact_${mode}_${targetLabel(model, route.target!).replace(/\W+/g, '_')}.csv`,
                  ['object', 'kind', 'role', 'process', 'hops'],
                  objects.map(({ n, h }) => [n.name, n.kind, roleLabel(n.role), n.process ?? '', h]),
                )
              }
            >
              Download report (CSV)
            </Button>
          </div>
          <div className="lbl-grid">
            <section>
              <Typography.Title level={4}>{`${verb} processes`}</Typography.Title>
              <Table size="small">
                <TableRow isHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.p">Process</TableHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.p-c">Highest</TableHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.p-o" align="right">Objects</TableHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.p-h" align="right">Hops</TableHeader>
                </TableRow>
                {processes.slice(0, MAX_ROWS).map(({ p, objects: n, hops }) => (
                  <TableRow key={p.name}>
                    <TableCell>
                      <Typography.Link componentId="sts-lb-lineage.impact.proc" onClick={() => onOpenProcess(p.name)}>
                        <span title={p.name}>{shortName(p.name)}</span>
                      </Typography.Link>
                    </TableCell>
                    <TableCell>
                      <LevelTag level={p.maxComplexity} />
                    </TableCell>
                    <TableCell align="right">{n}</TableCell>
                    <TableCell align="right">{hops}</TableCell>
                  </TableRow>
                ))}
              </Table>
            </section>
            <section>
              <Typography.Title level={4}>{`${verb} objects`}</Typography.Title>
              <Table size="small">
                <TableRow isHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.o">Object</TableHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.o-r">Role</TableHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.o-p">Process</TableHeader>
                  <TableHeader componentId="sts-lb-lineage.impact.o-h" align="right">Hops</TableHeader>
                </TableRow>
                {objects.slice(0, MAX_ROWS).map(({ n, h }) => (
                  <TableRow key={n.id}>
                    <TableCell>
                      <span className="lbl-name">
                        <KindIcon kind={n.kind} />
                        <Typography.Link componentId="sts-lb-lineage.impact.obj" onClick={() => onOpen(n.id)}>
                          {n.name}
                        </Typography.Link>
                      </span>
                    </TableCell>
                    <TableCell>{roleLabel(n.role) + (n.process === SHARED ? ' · shared' : '')}</TableCell>
                    <TableCell>
                      <span title={n.process}>{n.process ? shortName(n.process) : '-'}</span>
                    </TableCell>
                    <TableCell align="right">{h}</TableCell>
                  </TableRow>
                ))}
              </Table>
              {objects.length > MAX_ROWS && <Typography.Hint>{`Showing ${MAX_ROWS} of ${objects.length}. Download the CSV for all.`}</Typography.Hint>}
            </section>
          </div>
          <GraphView model={model} scope={scope} groupBy="process" onOpenDetails={onOpen} onOpenProcess={onOpenProcess} />
        </>
      )}
    </div>
  );
}
