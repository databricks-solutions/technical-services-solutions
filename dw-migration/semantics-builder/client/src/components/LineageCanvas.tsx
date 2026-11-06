import { useMemo, useState } from 'react';
import {
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import type { Edge, Node, NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Button,
  ChevronDownIcon,
  ChevronRightIcon,
  Input,
  TableIcon,
  Tag,
  Typography,
  WarningIcon,
  ZoomInIcon,
  ZoomOutIcon,
  ZoomToFitIcon,
} from '@databricks/design-system';
import { useThemePreference } from '../theme';

export type CanvasColumn = {
  name: string;
  /** Data type, or a short tag such as "measure". */
  type?: string;
  highlight?: boolean;
};

// React Flow node data must be a plain object type, so these are type aliases, not interfaces.
export type CanvasNode = {
  id: string;
  title: string;
  subtitle: string;
  kind: 'fact' | 'table' | 'view';
  columns: CanvasColumn[];
  warning?: string;
  /** Grid position: column (left to right) and row. */
  col: number;
  row: number;
};

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  dashed?: boolean;
  warn?: boolean;
  highlight?: boolean;
}

type Data = CanvasNode & { onSelect?: (id: string) => void; selected?: boolean };
const PAGE = 8;
const NODE_W = 240;
const COL_GAP = 190;
const ROW_GAP = 110;

/** A compact node like Catalog Explorer lineage: name and count; open it to search and page its columns. */
function AssetNode({ data }: NodeProps<Node<Data>>) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const cols = data.columns.filter((c) => c.name.toLowerCase().includes(q.toLowerCase()));
  const pages = Math.max(1, Math.ceil(cols.length / PAGE));
  const shown = cols.slice(page * PAGE, page * PAGE + PAGE);
  const view = data.kind === 'view';
  return (
    <div
      style={{
        width: NODE_W,
        borderRadius: view && !open ? 24 : 8,
        border: `1px solid ${data.warning ? 'var(--db-alert-border-warning)' : data.selected || view ? 'var(--db-accent-text)' : 'var(--db-border-strong)'}`,
        borderLeft: data.kind === 'fact' ? '4px solid var(--db-accent-text)' : undefined,
        background: view ? 'var(--db-accent-surface-subtle)' : 'var(--db-surface-base)',
        boxShadow: data.selected ? '0 0 0 2px var(--db-accent-text)' : undefined,
        padding: '8px 10px',
        fontSize: 12,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: 'var(--db-border-strong)' }} />
      <Handle type="source" position={Position.Right} style={{ background: 'var(--db-border-strong)' }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <button
          type="button"
          className="nodrag"
          aria-expanded={open}
          aria-label={`${open ? 'Close' : 'Open'} ${data.title}`}
          onClick={() => setOpen(!open)}
          style={{ background: 'none', border: 0, padding: 0, color: 'inherit', cursor: 'pointer', display: 'flex' }}
        >
          {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </button>
        {data.warning ? (
          <span title={data.warning} style={{ color: 'var(--db-alert-text-warning)', display: 'flex' }}>
            <WarningIcon />
          </span>
        ) : (
          <TableIcon />
        )}
        <button
          type="button"
          className="nodrag"
          title={data.subtitle}
          onClick={() => data.onSelect?.(data.id)}
          style={{
            flex: 1,
            minWidth: 0,
            background: 'none',
            border: 0,
            padding: 0,
            color: 'inherit',
            cursor: 'pointer',
            textAlign: 'left',
            fontWeight: 600,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {data.title}
        </button>
        <Tag componentId="gsb.canvas.count">{data.columns.length}</Tag>
      </div>
      <div
        style={{ color: 'var(--db-text-subtle)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {data.subtitle}
      </div>
      {open && (
        <div className="nodrag nowheel" style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
          {data.columns.length > PAGE && (
            <Input
              componentId="gsb.canvas.search"
              size="small"
              placeholder="Search columns"
              aria-label={`Search the columns of ${data.title}`}
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(0);
              }}
            />
          )}
          {shown.map((c) => (
            <div
              key={c.name}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: 6,
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                fontWeight: c.highlight ? 700 : undefined,
                color: c.highlight ? 'var(--db-accent-text)' : undefined,
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</span>
              {c.type && <span style={{ color: 'var(--db-text-subtle)' }}>{c.type}</span>}
            </div>
          ))}
          {!shown.length && <Typography.Text color="secondary">No column</Typography.Text>}
          {pages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Button
                componentId="gsb.canvas.prev"
                size="small"
                type="link"
                disabled={page === 0}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </Button>
              <span>
                {page + 1} / {pages}
              </span>
              <Button
                componentId="gsb.canvas.next"
                size="small"
                type="link"
                disabled={page >= pages - 1}
                onClick={() => setPage(page + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const nodeTypes = { asset: AssetNode };

function Zoom() {
  const flow = useReactFlow();
  return (
    <Panel position="bottom-left">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Button
          componentId="gsb.canvas.zoom_in"
          size="small"
          icon={<ZoomInIcon />}
          aria-label="Zoom in"
          onClick={() => void flow.zoomIn()}
        />
        <Button
          componentId="gsb.canvas.zoom_out"
          size="small"
          icon={<ZoomOutIcon />}
          aria-label="Zoom out"
          onClick={() => void flow.zoomOut()}
        />
        <Button
          componentId="gsb.canvas.fit"
          size="small"
          icon={<ZoomToFitIcon />}
          aria-label="Fit to the screen"
          onClick={() => void flow.fitView({ padding: 0.15, maxZoom: 1 })}
        />
      </div>
    </Panel>
  );
}

/**
 * A fixed-height lineage canvas: pan, zoom, minimap and compact nodes, so a large model does not grow the page.
 * Positions come from the caller's grid (col, row). Built on React Flow (MIT, webkid GmbH).
 */
export function LineageCanvas({
  label,
  nodes,
  edges,
  selected,
  onSelect,
  height = 480,
}: {
  label: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  selected?: string;
  onSelect?: (id: string) => void;
  height?: number;
}) {
  const { preference } = useThemePreference();
  const flowNodes = useMemo<Node<Data>[]>(
    () =>
      nodes.map((n) => ({
        id: n.id,
        type: 'asset',
        position: { x: n.col * (NODE_W + COL_GAP), y: n.row * ROW_GAP },
        data: { ...n, onSelect, selected: n.id === selected },
        draggable: true,
        connectable: false,
      })),
    [nodes, onSelect, selected]
  );
  // React Flow stores each node's measured size and dragged position through onNodesChange; the minimap needs the
  // size. New props keep the user's positions.
  const [state, setState] = useState(flowNodes);
  const [source, setSource] = useState(flowNodes);
  if (source !== flowNodes) {
    setSource(flowNodes);
    setState((prev) =>
      flowNodes.map((n) => {
        const p = prev.find((x) => x.id === n.id);
        return p ? { ...n, position: p.position, measured: p.measured } : n;
      })
    );
  }
  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        labelStyle: { fontSize: 11, fill: 'var(--db-text-subtle)' },
        labelBgStyle: { fill: 'var(--db-surface-base)' },
        style: {
          stroke: e.highlight
            ? 'var(--db-accent-text)'
            : e.warn
              ? 'var(--db-alert-border-warning)'
              : 'var(--db-text-subtle)',
          strokeWidth: e.highlight ? 2 : 1.25,
          strokeDasharray: e.dashed ? '6 4' : undefined,
        },
      })),
    [edges]
  );
  return (
    <div
      role="group"
      aria-label={label}
      style={{ height, border: '1px solid var(--db-border-base)', borderRadius: 8, overflow: 'hidden' }}
    >
      <ReactFlowProvider>
        <ReactFlow
          nodes={state}
          edges={flowEdges}
          onNodesChange={(changes) => setState((s) => applyNodeChanges(changes, s))}
          nodeTypes={nodeTypes}
          colorMode={preference}
          fitView
          fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
          minZoom={0.2}
          maxZoom={2}
          nodesConnectable={false}
          proOptions={{ hideAttribution: false }}
        >
          <Background variant={BackgroundVariant.Dots} gap={14} size={1} />
          <MiniMap
            pannable
            zoomable
            ariaLabel={`Minimap of ${label}`}
            nodeColor={(n) => ((n.data as Data).kind === 'view' ? '#2272b4' : '#8a96a3')}
            maskColor="rgba(128, 128, 128, 0.15)"
            style={{ width: 140, height: 90 }}
          />
          <Zoom />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}
