import dagre from '@dagrejs/dagre';
import {
  Button,
  CloseIcon,
  FileCodeIcon,
  FolderIcon,
  Modal,
  PlusIcon,
  SimpleSelect,
  SimpleSelectOption,
  Tag,
  Typography,
  WorkflowsIcon,
  ZoomInIcon,
  ZoomOutIcon,
  ZoomToFitIcon,
} from '@databricks/design-system';
import {
  Background,
  BackgroundVariant,
  type Edge,
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
import { type ReactNode, memo, useEffect, useMemo, useState } from 'react';

import { type GroupBy, type LEdge, type LNode, type Model, SHARED, groupLabel, groupOf, shortName, techList } from './data';
import { KindIcon, levelLabel, roleLabel } from './ui';

export const W = 260;
export const H = 56;
export const GAP = 80;
const PAD = 24;
const HEAD = 40;
const edgeKey = (e: { from: string; to: string; kind?: string }) => `${e.from}|${e.to}|${e.kind ?? ''}`;

type Pt = { x: number; y: number };
type Link = { from: string; to: string };
type Box = { key: string; x: number; y: number; w: number; h: number; count: number };

// ---------- layout ----------

/** Shelf-pack blocks into rows about 1.6x wider than tall. */
export function pack<T extends { w: number; h: number }>(blocks: T[]): (T & Pt)[] {
  const area = blocks.reduce((s, c) => s + (c.w + GAP) * (c.h + GAP), 0);
  const rowWidth = Math.max(Math.max(...blocks.map((c) => c.w)), Math.sqrt(area) * 1.6);
  let x = 0;
  let y = 0;
  let rowH = 0;
  return blocks.map((c) => {
    if (x > 0 && x + c.w > rowWidth) {
      x = 0;
      y += rowH + GAP;
      rowH = 0;
    }
    const placed = { ...c, x, y };
    x += c.w + GAP;
    rowH = Math.max(rowH, c.h);
    return placed;
  });
}

/** dagre per connected component, then pack the components so they do not stack into one column. */
export function layoutComponents(ids: string[], edges: Link[], size: (id: string) => { w: number; h: number } = () => ({ w: W, h: H })) {
  const parent = new Map(ids.map((id) => [id, id]));
  const find = (x: string): string => {
    while (parent.get(x) !== x) {
      parent.set(x, parent.get(parent.get(x)!)!);
      x = parent.get(x)!;
    }
    return x;
  };
  edges.forEach((e) => parent.has(e.from) && parent.has(e.to) && parent.set(find(e.from), find(e.to)));
  const comps = new Map<string, string[]>();
  ids.forEach((id) => comps.set(find(id), [...(comps.get(find(id)) ?? []), id]));
  const blocks = [...comps.values()].map((members) => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 120 });
    g.setDefaultEdgeLabel(() => ({}));
    const set = new Set(members);
    members.forEach((id) => g.setNode(id, { width: size(id).w, height: size(id).h }));
    edges.forEach((e) => set.has(e.from) && set.has(e.to) && g.setEdge(e.from, e.to));
    dagre.layout(g);
    const local = new Map(members.map((id) => [id, { x: g.node(id).x - size(id).w / 2, y: g.node(id).y - size(id).h / 2 }]));
    const w = Math.max(...members.map((id) => local.get(id)!.x + size(id).w));
    const h = Math.max(...members.map((id) => local.get(id)!.y + size(id).h));
    return { local, w, h };
  });
  blocks.sort((a, b) => b.local.size - a.local.size);
  const pos = new Map<string, Pt>();
  const placed = pack(blocks);
  placed.forEach((c) => c.local.forEach((p, id) => pos.set(id, { x: p.x + c.x, y: p.y + c.y })));
  return { pos, w: Math.max(...placed.map((c) => c.x + c.w)), h: Math.max(...placed.map((c) => c.y + c.h)) };
}

/** With a group-by, each group is a container laid out on its own; child positions are relative. */
function layout(ids: string[], edges: Link[], keyOf: ((id: string) => string) | null) {
  if (!keyOf) return { pos: layoutComponents(ids, edges).pos, boxes: [] as Box[] };
  const groups = new Map<string, string[]>();
  ids.forEach((id) => groups.set(keyOf(id), [...(groups.get(keyOf(id)) ?? []), id]));
  const blocks = [...groups.entries()].map(([key, members]) => {
    const set = new Set(members);
    const inner = layoutComponents(members, edges.filter((e) => set.has(e.from) && set.has(e.to)));
    return { key, inner, count: members.length, w: inner.w + 2 * PAD, h: inner.h + HEAD + PAD };
  });
  blocks.sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
  const pos = new Map<string, Pt>();
  const boxes: Box[] = pack(blocks).map((b) => {
    b.inner.pos.forEach((p, id) => pos.set(id, { x: p.x + PAD, y: p.y + HEAD }));
    return { key: b.key, x: b.x, y: b.y, w: b.w, h: b.h, count: b.count };
  });
  return { pos, boxes };
}

// ---------- node types ----------

type CardData = {
  node: LNode;
  sub: string;
  focal: boolean;
  dim: boolean;
  hiddenUp: number;
  hiddenDown: number;
  onExpand: (id: string, side: 'up' | 'down') => void;
};

const ExpandButton = ({ side, n, onClick }: { side: 'up' | 'down'; n: number; onClick: () => void }) => (
  <span className={`lbl-expand ${side === 'up' ? 'left' : 'right'}`}>
    <Button
      componentId={`sts-lb-lineage.graph.expand-${side}`}
      size="small"
      icon={<PlusIcon />}
      aria-label={`Show ${n} more ${side === 'up' ? 'upstream' : 'downstream'}`}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
    />
  </span>
);

const Card = memo(({ data, selected }: NodeProps<Node<CardData>>) => (
  <div className={`lbl-card${data.focal ? ' is-focal' : ''}${selected ? ' is-selected' : ''}${data.dim ? ' is-dim' : ''}`}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    {data.hiddenUp > 0 && <ExpandButton side="up" n={data.hiddenUp} onClick={() => data.onExpand(data.node.id, 'up')} />}
    <span className="lbl-card-icon">
      <KindIcon kind={data.node.kind} />
    </span>
    <span className="lbl-card-text">
      <span className="lbl-card-name" title={data.node.name}>
        {data.node.name}
      </span>
      <span className="lbl-card-sub">{data.sub}</span>
    </span>
    {data.hiddenDown > 0 && <ExpandButton side="down" n={data.hiddenDown} onClick={() => data.onExpand(data.node.id, 'down')} />}
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>
));

type StubData = { label: string; title: string; count: number };
const StubNode = memo(({ data }: NodeProps<Node<StubData>>) => (
  <div className="lbl-card is-stub" title={data.title}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <span className="lbl-card-icon">
      <WorkflowsIcon aria-hidden />
    </span>
    <span className="lbl-card-text">
      <span className="lbl-card-name">{data.label}</span>
      <span className="lbl-card-sub">{`Other process · ${data.count} links`}</span>
    </span>
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>
));

type GroupData = { label: string; title: string; count: number; isProcess: boolean };
const GroupBoxNode = memo(({ data }: NodeProps<Node<GroupData>>) => (
  <div className="lbl-group" title={data.title}>
    <div className="lbl-group-head">
      {data.isProcess ? <WorkflowsIcon aria-hidden /> : <FolderIcon aria-hidden />}
      <span className="lbl-card-name">{data.label}</span>
      <span className="lbl-card-sub">{`${data.count}`}</span>
    </div>
  </div>
));

type MoreData = { label: string };
const MoreNode = memo(({ data }: NodeProps<Node<MoreData>>) => (
  <div className="lbl-card is-stub is-more" role="button" aria-label={data.label}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <span className="lbl-card-icon">
      <PlusIcon aria-hidden />
    </span>
    <span className="lbl-card-text">
      <span className="lbl-card-name">{data.label}</span>
      <span className="lbl-card-sub">Click to show them</span>
    </span>
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>
));

const nodeTypes = { card: Card, group: GroupBoxNode, stub: StubNode, more: MoreNode };

/** Nodes shown per hop and side before the rest fold into a "+N more" node. */
const LAYER_CAP = 25;
/** Larger scoped graphs are cut to this many objects so the browser stays responsive. */
const MAX_GRAPH = 1500;
type More = { ids: string[]; parent: string; side: 'up' | 'down'; hop: number };

/** Breadth-first walk that keeps at most `cap` new nodes per hop; overflow stays reachable. */
function cappedWalk(m: Model, start: string, side: 'up' | 'down', depth: number, cap: number) {
  const keep = new Set([start]);
  const more = new Map<string, More>();
  let frontier = [start];
  for (let d = 1; d <= depth && frontier.length; d++) {
    const cands: string[] = [];
    const parentOf = new Map<string, string>();
    for (const id of frontier) {
      for (const e of (side === 'down' ? m.down : m.up).get(id) ?? []) {
        const other = side === 'down' ? e.to : e.from;
        if (!keep.has(other) && !parentOf.has(other)) {
          parentOf.set(other, id);
          cands.push(other);
        }
      }
    }
    const shown = cands.slice(0, cap);
    const rest = cands.slice(cap);
    if (rest.length) more.set(`more:${side}:${d}`, { ids: rest, parent: parentOf.get(rest[0])!, side, hop: d });
    shown.forEach((id) => keep.add(id));
    frontier = shown;
  }
  return { keep, more };
}

function neighbors(model: Model, id: string, side: 'up' | 'down') {
  return side === 'up' ? (model.up.get(id) ?? []).map((e) => e.from) : (model.down.get(id) ?? []).map((e) => e.to);
}

const DEPTHS = ['1', '2', '3', 'all'];
const depthNum = (d: string) => (d === 'all' ? Infinity : Number(d));

export const nodeSub = (model: Model, n: LNode) => {
  const prog = model.programs.get(n.name);
  const parts = [n.kind === 'job' ? 'Job' : roleLabel(n.role), techList(model, n.id).join(', ')];
  if (prog?.complexity) parts.push(levelLabel(prog.complexity));
  return parts.filter(Boolean).join(' · ');
};

// ---------- canvas ----------

interface CanvasProps {
  model: Model;
  groupBy: GroupBy;
  focusId?: string | null;
  scope?: string[];
  /** Show neighbors outside the scope as one stub per process instead of hiding them. */
  boundary?: boolean;
  /** Nodes outside this set are dimmed (path highlight). */
  emphasis?: Set<string>;
  onOpenDetails: (id: string) => void;
  onOpenProcess?: (name: string) => void;
  extraTools?: ReactNode;
}

function Canvas({ model, groupBy, focusId = null, scope, boundary, emphasis, onOpenDetails, onOpenProcess, extraTools }: CanvasProps) {
  const [focus, setFocus] = useState<string | null>(focusId);
  const [depthUp, setDepthUp] = useState('1');
  const [depthDown, setDepthDown] = useState('1');
  const [visible, setVisible] = useState<Set<string>>(new Set());
  const [more, setMore] = useState<Map<string, More>>(new Map());
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<LEdge | null>(null);
  const flow = useReactFlow();

  useEffect(() => {
    if (focus) {
      const ups = cappedWalk(model, focus, 'up', depthNum(depthUp), LAYER_CAP);
      const downs = cappedWalk(model, focus, 'down', depthNum(depthDown), LAYER_CAP);
      setVisible(new Set([...ups.keep, ...downs.keep]));
      setMore(new Map([...ups.more, ...downs.more]));
    } else {
      setVisible(new Set((scope ?? []).slice(0, MAX_GRAPH)));
      setMore(new Map());
    }
    setSelNode(null);
    setSelEdge(null);
  }, [focus, model, scope, depthUp, depthDown]);

  const expand = (id: string, side: 'up' | 'down') => setVisible((v) => new Set([...v, ...neighbors(model, id, side)]));

  const { nodes, edges } = useMemo(() => {
    const shown = model.doc.edges.filter((e) => visible.has(e.from) && visible.has(e.to));
    // boundary stubs: one node per outside process, linked to the inside object
    const stubs = new Map<string, number>();
    const stubLinks = new Map<string, Link & { kind: string }>();
    if (boundary && !focus) {
      for (const id of visible) {
        for (const [side, list] of [['down', model.down.get(id)], ['up', model.up.get(id)]] as const) {
          for (const e of list ?? []) {
            const other = side === 'down' ? e.to : e.from;
            if (visible.has(other)) continue;
            const proc = model.byId.get(other)?.process ?? '(no process)';
            const sid = `stub:${proc === SHARED ? 'Shared tables' : proc}`;
            const link = side === 'down' ? { from: id, to: sid, kind: 'stub' } : { from: sid, to: id, kind: 'stub' };
            if (!stubLinks.has(edgeKey(link))) {
              stubLinks.set(edgeKey(link), link);
              stubs.set(sid, (stubs.get(sid) ?? 0) + 1);
            }
          }
        }
      }
    }
    const moreLinks = [...more.entries()].map(([mid, m]) =>
      m.side === 'up' ? { from: mid, to: m.parent, kind: 'more' } : { from: m.parent, to: mid, kind: 'more' },
    );
    const ids = [...visible, ...stubs.keys(), ...more.keys()];
    const links: Link[] = [...shown, ...stubLinks.values(), ...moreLinks];
    const keyOf =
      groupBy === 'none'
        ? null
        : (id: string) =>
            id.startsWith('stub:') ? 'Connected processes' : id.startsWith('more:') ? 'More' : groupOf(model, groupBy, id);
    const { pos, boxes } = layout(ids, links, keyOf);
    const hl = selNode ?? focus;
    const groupNodes: Node<GroupData>[] = boxes.map((b) => ({
      id: `grp:${b.key}`,
      type: 'group',
      position: { x: b.x, y: b.y },
      style: { width: b.w, height: b.h },
      selectable: false,
      data: { label: groupLabel(groupBy, b.key), title: b.key, count: b.count, isProcess: groupBy === 'process' },
    }));
    const parent = (id: string) => (keyOf ? { parentId: `grp:${keyOf(id)}` } : {});
    const cards: Node<CardData>[] = [...visible].map((id) => ({
      id,
      type: 'card',
      position: pos.get(id)!,
      ...parent(id),
      selected: id === selNode,
      data: {
        node: model.byId.get(id)!,
        sub: nodeSub(model, model.byId.get(id)!),
        focal: id === focus,
        dim: !!emphasis && !emphasis.has(id),
        hiddenUp: boundary && !focus ? 0 : neighbors(model, id, 'up').filter((x) => !visible.has(x)).length,
        hiddenDown: boundary && !focus ? 0 : neighbors(model, id, 'down').filter((x) => !visible.has(x)).length,
        onExpand: expand,
      },
    }));
    const stubNodes: Node<StubData>[] = [...stubs.entries()].map(([sid, count]) => ({
      id: sid,
      type: 'stub',
      position: pos.get(sid)!,
      ...parent(sid),
      data: { label: shortName(sid.slice(5)), title: sid.slice(5), count },
    }));
    const moreNodes: Node<MoreData>[] = [...more.entries()].map(([mid, m]) => ({
      id: mid,
      type: 'more',
      position: pos.get(mid)!,
      ...parent(mid),
      data: { label: `${m.ids.length} more ${m.side === 'up' ? 'upstream' : 'downstream'} at hop ${m.hop}` },
    }));
    const edges: Edge[] = [
      ...moreLinks.map((l) => ({
        id: edgeKey(l),
        source: l.from,
        target: l.to,
        className: 'lbl-edge is-stub',
        zIndex: 1,
      })),
      ...shown.map((e) => {
        const active = e.from === hl || e.to === hl || (selEdge && edgeKey(selEdge) === edgeKey(e));
        const dim = emphasis && !(emphasis.has(e.from) && emphasis.has(e.to));
        return {
          id: edgeKey(e),
          source: e.from,
          target: e.to,
          className: `lbl-edge${active ? ' is-active' : ''}${e.kind === 'orchestration' ? ' is-orch' : ''}${dim ? ' is-dim' : ''}`,
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          zIndex: 1,
          data: e as unknown as Record<string, unknown>,
        };
      }),
      ...[...stubLinks.values()].map((l) => ({
        id: edgeKey(l),
        source: l.from,
        target: l.to,
        className: 'lbl-edge is-stub',
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        zIndex: 1,
      })),
    ];
    return { nodes: [...groupNodes, ...cards, ...stubNodes, ...moreNodes] as Node[], edges };
  }, [model, visible, more, focus, selNode, selEdge, groupBy, boundary, emphasis]);

  useEffect(() => {
    const t = setTimeout(() => flow.fitView({ padding: 0.2, maxZoom: 1, duration: 200 }), 0);
    return () => clearTimeout(t);
  }, [visible, flow, groupBy]);

  const depthSelect = (label: string, value: string, set: (v: string) => void) => (
    <SimpleSelect
      componentId={`sts-lb-lineage.graph.depth-${label.toLowerCase()}`}
      id={`sts-lb-lineage-depth-${label.toLowerCase()}`}
      label={label}
      value={value}
      onChange={(e) => set(e.target.value)}
      width={150}
    >
      {DEPTHS.map((d) => (
        <SimpleSelectOption key={d} value={d}>
          {d === 'all' ? `${label}: all` : `${label}: ${d} hop${d === '1' ? '' : 's'}`}
        </SimpleSelectOption>
      ))}
    </SimpleSelect>
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      onlyRenderVisibleElements
      zoomOnDoubleClick={false}
      minZoom={0.05}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, n) => {
        if (n.type === 'group') return;
        if (n.type === 'stub') return onOpenProcess?.(n.id.slice(5));
        if (n.type === 'more') {
          const m = more.get(n.id);
          if (!m) return;
          setVisible((v) => new Set([...v, ...m.ids]));
          setMore((old) => {
            const next = new Map(old);
            next.delete(n.id);
            return next;
          });
          return;
        }
        setSelNode(n.id);
        setSelEdge(null);
      }}
      onNodeDoubleClick={(_, n) => n.type === 'card' && setFocus(n.id)}
      onEdgeClick={(_, e) => {
        if (!e.data) return;
        setSelEdge(e.data as unknown as LEdge);
        setSelNode(null);
      }}
      onPaneClick={() => {
        setSelNode(null);
        setSelEdge(null);
      }}
    >
      <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
      <Panel position="bottom-left" className="lbl-graph-tools">
        <Button componentId="sts-lb-lineage.graph.zoom-in" icon={<ZoomInIcon />} aria-label="Zoom in" onClick={() => flow.zoomIn()} />
        <Button componentId="sts-lb-lineage.graph.zoom-out" icon={<ZoomOutIcon />} aria-label="Zoom out" onClick={() => flow.zoomOut()} />
        <Button
          componentId="sts-lb-lineage.graph.fit"
          icon={<ZoomToFitIcon />}
          aria-label="Fit to screen"
          onClick={() => flow.fitView({ padding: 0.2, maxZoom: 1 })}
        />
        {focus && depthSelect('Upstream', depthUp, setDepthUp)}
        {focus && depthSelect('Downstream', depthDown, setDepthDown)}
        {scope && focus && (
          <Button componentId="sts-lb-lineage.graph.show-all" onClick={() => setFocus(null)}>
            Back to scope
          </Button>
        )}
        {extraTools}
        <Typography.Hint>
          {(scope?.length ?? 0) > MAX_GRAPH && !focus
            ? `Showing the first ${MAX_GRAPH} of ${scope!.length} objects. Double-click an object to focus, or narrow the scope.`
            : `${visible.size} objects. Double-click to focus. Click an edge to see the program.`}
        </Typography.Hint>
      </Panel>
      {(selNode || selEdge) && (
        <Panel position="top-right" className="lbl-panel">
          <div className="lbl-panel-head">
            <Typography.Title level={4}>{selEdge ? 'Relationship' : model.byId.get(selNode!)?.name}</Typography.Title>
            <Button
              componentId="sts-lb-lineage.graph.panel-close"
              type="tertiary"
              size="small"
              icon={<CloseIcon />}
              aria-label="Close panel"
              onClick={() => {
                setSelNode(null);
                setSelEdge(null);
              }}
            />
          </div>
          {selEdge ? (
            <EdgeInfo model={model} edge={selEdge} onOpenProcess={onOpenProcess} />
          ) : (
            <NodeInfo model={model} id={selNode!} onOpenDetails={onOpenDetails} onFocus={setFocus} onOpenProcess={onOpenProcess} />
          )}
        </Panel>
      )}
    </ReactFlow>
  );
}

function EdgeInfo({ model, edge, onOpenProcess }: { model: Model; edge: LEdge; onOpenProcess?: (p: string) => void }) {
  return (
    <div className="lbl-panel-body">
      <Typography.Text>{`${model.byId.get(edge.from)?.name} → ${model.byId.get(edge.to)?.name}`}</Typography.Text>
      <div className="lbl-row">
        <Tag componentId="sts-lb-lineage.graph.edge-kind">{edge.kind === 'orchestration' ? 'Orchestration' : 'Data flow'}</Tag>
        {edge.kind === 'data' && <Tag componentId="sts-lb-lineage.graph.edge-grain">{`${edge.grain} grain`}</Tag>}
        <Tag componentId="sts-lb-lineage.graph.edge-tech">{edge.tech}</Tag>
      </div>
      <Typography.Title level={4}>Via</Typography.Title>
      {edge.via.map((v) => {
        const p = model.programs.get(v);
        const proc = model.processOfProgram.get(v);
        return (
          <div key={v} className="lbl-via" title={v}>
            <FileCodeIcon aria-hidden />
            <span>
              <Typography.Text bold>{shortName(v)}</Typography.Text>
              {p && (
                <Typography.Hint>{`${p.complexity ? levelLabel(p.complexity) + ' · ' : ''}reads ${p.reads.length} · writes ${p.writes.length}`}</Typography.Hint>
              )}
              {proc && onOpenProcess && (
                <Typography.Link componentId="sts-lb-lineage.graph.edge-process" onClick={() => onOpenProcess(proc)}>
                  {`Process: ${shortName(proc)}`}
                </Typography.Link>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function NodeInfo({
  model,
  id,
  onOpenDetails,
  onFocus,
  onOpenProcess,
}: {
  model: Model;
  id: string;
  onOpenDetails: (id: string) => void;
  onFocus: (id: string) => void;
  onOpenProcess?: (p: string) => void;
}) {
  const n = model.byId.get(id)!;
  return (
    <div className="lbl-panel-body">
      <Typography.Text>{`${roleLabel(n.role)} · upstream ${model.up.get(id)?.length ?? 0} · downstream ${model.down.get(id)?.length ?? 0}`}</Typography.Text>
      <div className="lbl-row">
        <Button componentId="sts-lb-lineage.graph.center" onClick={() => onFocus(id)}>
          Focus here
        </Button>
        <Button componentId="sts-lb-lineage.graph.details" onClick={() => onOpenDetails(id)}>
          Open details
        </Button>
        {n.process && model.procByName.has(n.process) && onOpenProcess && (
          <Button componentId="sts-lb-lineage.graph.process" onClick={() => onOpenProcess(n.process!)}>
            Open process
          </Button>
        )}
      </div>
    </div>
  );
}

export function LineageModal({
  title,
  onClose,
  ...canvas
}: CanvasProps & { title: string; onClose: () => void }) {
  return (
    <Modal componentId="sts-lb-lineage.graph" visible size="extraWide" verticalSizing="maxed_out" title={title} onCancel={onClose} footer={null}>
      <div className="lbl-canvas">
        <ReactFlowProvider>
          <Canvas {...canvas} />
        </ReactFlowProvider>
      </div>
    </Modal>
  );
}

export function GraphView(props: CanvasProps) {
  return (
    <div className="lbl-canvas is-page">
      <ReactFlowProvider>
        <Canvas {...props} />
      </ReactFlowProvider>
    </div>
  );
}
