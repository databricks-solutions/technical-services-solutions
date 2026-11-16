import {
  Empty,
  Input,
  SearchIcon,
  SegmentedControlButton,
  SegmentedControlGroup,
  SimpleSelect,
  SimpleSelectOption,
  Switch,
  Table,
  TableCell,
  TableHeader,
  TableIcon,
  TableRow,
  Typography,
  WorkflowsIcon,
  ZoomInIcon,
  ZoomOutIcon,
  ZoomToFitIcon,
  Button,
} from '@databricks/design-system';
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  type Edge,
  type EdgeProps,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import { memo, useEffect, useMemo, useState } from 'react';

import { type Model, type ProcessInfo, shortName } from './data';
import { H, W, layoutComponents, onGraphKey } from './Graph';
import { LevelTag, plural } from './ui';

type ProcData = { p: ProcessInfo; selected: boolean };
type HubData = { name: string; count: number; selected: boolean };

const ProcNode = memo(({ data }: NodeProps<Node<ProcData>>) => (
  <div className={`lbl-card is-process${data.selected ? ' is-focal' : ''}`} title={data.p.name}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <span className="lbl-card-icon">
      <WorkflowsIcon aria-hidden />
    </span>
    <span className="lbl-card-text">
      <span className="lbl-card-name">{shortName(data.p.name)}</span>
      <span className="lbl-card-sub">
        {`${plural(data.p.objects.length, 'object')} · ${data.p.tech.join(', ')}${data.p.cycle !== null ? ' · in a cycle' : ''}`}
      </span>
    </span>
    <LevelTag level={data.p.maxComplexity} />
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>
));

const HubNode = memo(({ data }: NodeProps<Node<HubData>>) => (
  <div className={`lbl-card is-hub${data.selected ? ' is-focal' : ''}`} title={data.name}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <span className="lbl-card-icon">
      <TableIcon aria-hidden />
    </span>
    <span className="lbl-card-text">
      <span className="lbl-card-name">{data.name}</span>
      <span className="lbl-card-sub">{`Shared by ${data.count} processes`}</span>
    </span>
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>
));

const nodeTypes = { proc: ProcNode, hub: HubNode };

/** An edge that closes a dependency cycle runs right to left. Route it under the graph so it
 *  never hides behind the cards. */
function BackEdge({ sourceX, sourceY, targetX, targetY, data, markerEnd, label, style }: EdgeProps<Edge<{ below: number }>>) {
  const y = data?.below ?? Math.max(sourceY, targetY) + 60;
  const path = `M ${sourceX} ${sourceY} H ${sourceX + 24} V ${y} H ${targetX - 24} V ${targetY} H ${targetX}`;
  return <BaseEdge path={path} markerEnd={markerEnd} style={style} label={label} labelX={(sourceX + targetX) / 2} labelY={y} labelBgPadding={[4, 2]} />;
}

const edgeTypes = { back: BackEdge };

interface Filters {
  q: string;
  tech: string;
  hubs: boolean;
  connectedOnly: boolean;
  cyclesOnly: boolean;
  all: boolean;
  cap?: number;
}

/** Above this many processes the map shows the most connected ones first, so labels stay readable. */
export const MAP_CAP = 15;
const MIN_ZOOM = 0.5;

/** Shared tables and process links per process, used to rank "most connected". */
export function degrees(model: Model) {
  const deg = new Map<string, number>();
  const add = (p: string) => deg.set(p, (deg.get(p) ?? 0) + 1);
  model.ins.hubs.forEach((h) => [...h.writers, ...h.readers].forEach(add));
  model.ins.processEdges.forEach((e) => (add(e.from), add(e.to)));
  return deg;
}

function MapCanvas({
  model,
  filters,
  onOpenProcess,
  onOpenObject,
}: {
  model: Model;
  filters: Filters;
  onOpenProcess: (name: string) => void;
  onOpenObject: (id: string) => void;
}) {
  const flow = useReactFlow();
  const [sel, setSel] = useState<string | null>(null);

  const { nodes, edges, count, total, hidden } = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    const linked = new Set<string>();
    model.ins.hubs.forEach((h) => [...h.writers, ...h.readers].forEach((p) => linked.add(p)));
    const matching = model.ins.processes.filter(
      (p) =>
        (!q || p.name.toLowerCase().includes(q)) &&
        (filters.tech === 'all' || p.tech.includes(filters.tech)) &&
        (!filters.connectedOnly || linked.has(p.name)) &&
        (!filters.cyclesOnly || p.cycle !== null),
    );
    const deg = degrees(model);
    const procs =
      filters.all || matching.length <= (filters.cap ?? MAP_CAP)
        ? matching
        : [...matching].sort((a, b) => (deg.get(b.name) ?? 0) - (deg.get(a.name) ?? 0)).slice(0, filters.cap ?? MAP_CAP);
    const hidden = filters.connectedOnly ? model.ins.processes.filter((p) => !linked.has(p.name) && p.objects.length > 0).length : 0;
    const keep = new Set(procs.map((p) => p.name));
    const links: { from: string; to: string; label?: string }[] = [];
    const hubIds: string[] = [];
    if (filters.hubs) {
      for (const h of model.ins.hubs) {
        const ws = h.writers.filter((w) => keep.has(w));
        const rs = h.readers.filter((r) => keep.has(r));
        if (ws.length + rs.length < 1) continue;
        hubIds.push(h.id);
        ws.forEach((w) => links.push({ from: `p:${w}`, to: `h:${h.id}` }));
        rs.forEach((r) => links.push({ from: `h:${h.id}`, to: `p:${r}` }));
      }
    } else {
      for (const e of model.ins.processEdges) {
        if (keep.has(e.from) && keep.has(e.to)) links.push({ from: `p:${e.from}`, to: `p:${e.to}`, label: plural(e.tables.length, 'table') });
      }
    }
    const ids = [...procs.map((p) => `p:${p.name}`), ...hubIds.map((h) => `h:${h}`)];
    const { pos } = layoutComponents(ids, links, () => ({ w: W + 60, h: H + 8 }));
    const active = (id: string) => sel !== null && id === sel;
    const nodes: Node[] = [
      ...procs.map((p) => ({
        id: `p:${p.name}`,
        type: 'proc',
        ariaLabel: `Process ${p.name}, ${p.objects.length} objects. Press Enter for details.`,
        position: pos.get(`p:${p.name}`)!,
        data: { p, selected: active(`p:${p.name}`) },
      })),
      ...hubIds.map((h) => ({
        id: `h:${h}`,
        type: 'hub',
        ariaLabel: `Shared table ${model.byId.get(h)?.name ?? h}. Press Enter for details.`,
        position: pos.get(`h:${h}`)!,
        data: { name: model.byId.get(h)?.name ?? h, count: model.hubById.get(h)!.processCount, selected: active(`h:${h}`) },
      })),
    ];
    const bottom = Math.max(0, ...[...pos.values()].map((v) => v.y)) + H + 8;
    let backs = 0;
    const edges: Edge[] = links.map((l) => {
      const back = (pos.get(l.to)?.x ?? 0) < (pos.get(l.from)?.x ?? 0);
      return {
        id: `${l.from}>${l.to}`,
        source: l.from,
        target: l.to,
        type: back ? 'back' : undefined,
        data: back ? { below: bottom + 30 + 16 * backs++ } : undefined,
        label: back ? (l.label ? `${l.label}, loops back` : 'loops back') : l.label,
        className: `lbl-edge${back ? ' is-back' : ''}${sel && (l.from === sel || l.to === sel) ? ' is-active' : ''}`,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      };
    });
    return { nodes, edges, count: procs.length, total: matching.length, hidden };
  }, [model, filters, sel]);

  useEffect(() => {
    const t = setTimeout(() => flow.fitView({ padding: 0.15, maxZoom: 1, minZoom: MIN_ZOOM, duration: 200 }), 0);
    return () => clearTimeout(t);
  }, [filters, flow]);

  if (count === 0)
    return (
      <Empty
        title="No processes match"
        description={filters.cyclesOnly ? 'No process is in a dependency cycle.' : 'Change the search or the filters.'}
      />
    );
  return (
    <ReactFlow
      onKeyDownCapture={onGraphKey}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      onlyRenderVisibleElements
      zoomOnDoubleClick={false}
      minZoom={0.05}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => {
        setSel(n.id);
        if (n.type === 'proc') onOpenProcess(n.id.slice(2));
        else onOpenObject(n.id.slice(2));
      }}
      onPaneClick={() => setSel(null)}
    >
      <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
      <Panel position="top-left" className="lbl-legend" aria-label="Legend">
        <span className="lbl-legend-item">
          <WorkflowsIcon aria-hidden /> Process (objects, technology, highest complexity)
        </span>
        {filters.hubs ? (
          <span className="lbl-legend-item">
            <TableIcon aria-hidden /> Shared table (dashed): written or read by several processes
          </span>
        ) : (
          <span className="lbl-legend-item">Edge label: tables one process writes and the other reads</span>
        )}
        <span className="lbl-legend-item">Arrows: data flows from writer to reader. Dashed red: closes a dependency cycle</span>
      </Panel>
      <Panel position="bottom-left" className="lbl-graph-tools">
        <Button componentId="sts-lb-lineage.map.zoom-in" icon={<ZoomInIcon />} aria-label="Zoom in" onClick={() => flow.zoomIn()} />
        <Button componentId="sts-lb-lineage.map.zoom-out" icon={<ZoomOutIcon />} aria-label="Zoom out" onClick={() => flow.zoomOut()} />
        <Button
          componentId="sts-lb-lineage.map.fit"
          icon={<ZoomToFitIcon />}
          aria-label="Fit to screen"
          onClick={() => flow.fitView({ padding: 0.15, maxZoom: 1, minZoom: MIN_ZOOM })}
        />
        <Typography.Hint>
          {`${count < total ? `${count} most connected of ${total} processes` : plural(count, 'process', 'processes')}${hidden ? `, ${hidden} self-contained hidden` : ''}. Drag to pan. Click a process for its details and lineage graph.`}
        </Typography.Hint>
      </Panel>
    </ReactFlow>
  );
}

const PREVIEW_FILTERS = { q: '', tech: 'all', hubs: true, connectedOnly: true, cyclesOnly: false, all: false };

/** Small, read-only map for the Overview page. */
export function ProcessMapPreview({
  model,
  cap,
  onOpenProcess,
  onOpenObject,
}: {
  model: Model;
  cap: number;
  onOpenProcess: (name: string) => void;
  onOpenObject: (id: string) => void;
}) {
  const filters = useMemo(() => ({ ...PREVIEW_FILTERS, cap }), [cap]);
  return (
    <div className="lbl-canvas is-preview">
      <ReactFlowProvider>
        <MapCanvas model={model} filters={filters} onOpenProcess={onOpenProcess} onOpenObject={onOpenObject} />
      </ReactFlowProvider>
    </div>
  );
}

function Coupling({ model, onOpenProcess }: { model: Model; onOpenProcess: (name: string) => void }) {
  const N = 20;
  const degree = new Map<string, number>();
  for (const e of model.ins.processEdges) {
    degree.set(e.from, (degree.get(e.from) ?? 0) + e.tables.length);
    degree.set(e.to, (degree.get(e.to) ?? 0) + e.tables.length);
  }
  const top = [...degree.entries()].sort((a, b) => b[1] - a[1]).slice(0, N).map(([p]) => p);
  if (top.length === 0)
    return <Empty title="No coupling" description="No process reads a table that another process writes." />;
  const cell = new Map(model.ins.processEdges.map((e) => [`${e.from}|${e.to}`, e.tables.length]));
  const max = Math.max(...cell.values());
  return (
    <div className="lbl-matrix">
      <Typography.Paragraph>
        {`Rows write tables that columns read. Numbers are shared tables. Top ${top.length} processes by coupling.`}
      </Typography.Paragraph>
      <Table size="small" scrollable>
        <TableRow isHeader>
          <TableHeader componentId="sts-lb-lineage.coupling.writer">Writer \ reader</TableHeader>
          {top.map((c) => (
            <TableHeader key={c} componentId="sts-lb-lineage.coupling.col">
              <span title={c}>{shortName(c)}</span>
            </TableHeader>
          ))}
        </TableRow>
        {top.map((r) => (
          <TableRow key={r}>
            <TableCell>
              <Typography.Link componentId="sts-lb-lineage.coupling.row" onClick={() => onOpenProcess(r)}>
                {shortName(r)}
              </Typography.Link>
            </TableCell>
            {top.map((c) => {
              const v = cell.get(`${r}|${c}`) ?? 0;
              return (
                <TableCell key={c} align="right">
                  <span className={v ? (v >= max / 2 ? 'lbl-heat-2' : 'lbl-heat-1') : 'lbl-heat-0'}>{v || '-'}</span>
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </Table>
    </div>
  );
}

export function ProcessMap({
  model,
  onOpenProcess,
  onOpenObject,
  initialCycles = false,
}: {
  model: Model;
  initialCycles?: boolean;
  onOpenProcess: (name: string) => void;
  onOpenObject: (id: string) => void;
}) {
  const [view, setView] = useState<'map' | 'coupling'>('map');
  const [q, setQ] = useState('');
  const [tech, setTech] = useState('all');
  const [hubs, setHubs] = useState(true);
  const [connectedOnly, setConnectedOnly] = useState(true);
  const [cyclesOnly, setCyclesOnly] = useState(initialCycles);
  const [all, setAll] = useState(false);
  const techs = Object.keys(model.ins.summary.technologies);
  const filters = useMemo(() => ({ q, tech, hubs, connectedOnly, cyclesOnly, all }), [q, tech, hubs, connectedOnly, cyclesOnly, all]);
  const linked = useMemo(() => new Set(model.ins.hubs.flatMap((h) => [...h.writers, ...h.readers])), [model]);
  const selfContained = model.ins.processes.filter((p) => !linked.has(p.name) && p.objects.length > 0).length;
  const inCycle = model.ins.processes.filter((p) => p.cycle !== null).length;

  return (
    <div className="lbl-tab">
      <div className="lbl-toolbar">
        <SegmentedControlGroup componentId="sts-lb-lineage.map.view" name="map-view" value={view} onChange={(e) => setView(e.target.value)}>
          <SegmentedControlButton value="map">Process map</SegmentedControlButton>
          <SegmentedControlButton value="coupling">Coupling matrix</SegmentedControlButton>
        </SegmentedControlGroup>
        {view === 'map' && (
          <>
            <div className="lbl-search">
              <Input
                componentId="sts-lb-lineage.map.search"
                prefix={<SearchIcon />}
                placeholder="Search processes"
                aria-label="Search processes"
                allowClear
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <SimpleSelect componentId="sts-lb-lineage.map.tech" id="sts-lb-lineage-map-tech" label="Technology" value={tech} onChange={(e) => setTech(e.target.value)} width={180}>
              <SimpleSelectOption value="all">All technologies</SimpleSelectOption>
              {techs.map((t) => (
                <SimpleSelectOption key={t} value={t}>
                  {t}
                </SimpleSelectOption>
              ))}
            </SimpleSelect>
            <Switch
              componentId="sts-lb-lineage.map.hubs"
              label="Shared tables as nodes"
              checked={hubs}
              onChange={(v) => setHubs(v)}
            />
            <Switch
              componentId="sts-lb-lineage.map.connected"
              label={`Hide self-contained processes (${selfContained})`}
              checked={connectedOnly}
              disabled={selfContained === 0}
              onChange={(v) => setConnectedOnly(v)}
            />
            {inCycle > 0 && (
              <Switch
                componentId="sts-lb-lineage.map.cycles"
                label={`Only processes in a cycle (${inCycle})`}
                checked={cyclesOnly}
                onChange={(v) => setCyclesOnly(v)}
              />
            )}
            {model.ins.processes.length > MAP_CAP && (
              <Switch
                componentId="sts-lb-lineage.map.all"
                label={`Show all processes (${model.ins.processes.length})`}
                checked={all}
                onChange={(v) => setAll(v)}
              />
            )}
          </>
        )}
      </div>
      {view === 'map' ? (
        <div className="lbl-canvas is-page">
          <ReactFlowProvider>
            <MapCanvas model={model} filters={filters} onOpenProcess={onOpenProcess} onOpenObject={onOpenObject} />
          </ReactFlowProvider>
        </div>
      ) : (
        <Coupling model={model} onOpenProcess={onOpenProcess} />
      )}
    </div>
  );
}
