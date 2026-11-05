import {
  Alert,
  Checkbox,
  Empty,
  FolderIcon,
  InfoTooltip,
  Input,
  Pagination,
  SearchIcon,
  SegmentedControlButton,
  SegmentedControlGroup,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
  WorkflowsIcon,
} from '@databricks/design-system';
import { useEffect, useMemo, useState } from 'react';

import {
  GROUP_BY_LABEL,
  type GroupBy,
  type LNode,
  type Model,
  SHARED,
  groupLabel,
  groupOf,
  schemaOf,
  shortName,
  techList,
  walk,
} from './data';
import { GraphView } from './Graph';
import { KindIcon, LevelTag, kindLabel, roleLabel } from './ui';

const PAGE_SIZE = 50;
const NARROW = { maxWidth: 110 };
const MID = { maxWidth: 160 };
const WIDE = { minWidth: 240 };
type SortKey = 'name' | 'up' | 'down';
const KEYS = ['process', 'tech', 'role', 'schema', 'complexity'] as const;
type Key = (typeof KEYS)[number];

export interface Selector {
  text: string[];
  filters: Partial<Record<Key, string[]>>;
  graph: { name: string; up: number; down: number }[];
}

/** dbt-like selector: `key:value` filters, `+name+` / `2+name+1` graph scopes, free text. */
export function parseSelector(q: string): Selector {
  const sel: Selector = { text: [], filters: {}, graph: [] };
  for (const tok of q.match(/"[^"]+"|\S+/g) ?? []) {
    const t = tok.replace(/^"|"$/g, '');
    const kv = t.match(/^(\w+):(.+)$/);
    if (kv && (KEYS as readonly string[]).includes(kv[1].toLowerCase())) {
      const k = kv[1].toLowerCase() as Key;
      (sel.filters[k] ??= []).push(kv[2].toLowerCase());
      continue;
    }
    const g = t.match(/^(\d*\+)?(.+?)(\+\d*)?$/);
    if (g && (g[1] || g[3])) {
      const depth = (s: string | undefined) => (!s ? 0 : s.replace('+', '') === '' ? Infinity : Number(s.replace('+', '')));
      sel.graph.push({ name: g[2].toLowerCase(), up: depth(g[1]), down: depth(g[3]) });
      continue;
    }
    sel.text.push(t.toLowerCase());
  }
  return sel;
}

function complexityOf(model: Model, n: LNode): string[] {
  if (n.kind === 'job') return [model.programs.get(n.name)?.complexity ?? 'UNKNOWN'];
  return (model.programsOf.get(n.id) ?? []).map(({ program }) => program.complexity ?? 'UNKNOWN');
}

export function matches(model: Model, sel: Selector, n: LNode): boolean {
  if (sel.text.some((t) => !n.name.toLowerCase().includes(t))) return false;
  const f = sel.filters;
  const any = (vals: string[] | undefined, test: (v: string) => boolean) => !vals || vals.some(test);
  return (
    any(f.process, (v) => (n.process ?? '').toLowerCase().includes(v)) &&
    any(f.tech, (v) => techList(model, n.id).some((t) => t.toLowerCase() === v)) &&
    any(f.role, (v) => (v === 'shared' ? n.process === SHARED : n.role === v)) &&
    any(f.schema, (v) => schemaOf(n).toLowerCase() === v) &&
    any(f.complexity, (v) => complexityOf(model, n).some((c) => c.toLowerCase() === v))
  );
}

export function Objects({
  model,
  q,
  setQ,
  onOpen,
  onOpenProcess,
}: {
  model: Model;
  q: string;
  setQ: (q: string) => void;
  onOpen: (id: string) => void;
  onOpenProcess: (name: string) => void;
}) {
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const [kinds, setKinds] = useState<Set<string>>(new Set(['table', 'job']));
  const [techs, setTechs] = useState<Set<string>>(new Set());
  const [connectedOnly, setConnectedOnly] = useState(true);
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'down', dir: 'desc' });
  const [page, setPage] = useState(1);
  const [view, setView] = useState<'list' | 'graph'>('list');
  const [groupBy, setGroupBy] = useState<GroupBy>('process');
  const [groupFilter, setGroupFilter] = useState<Set<string>>(new Set());

  const sel = useMemo(() => parseSelector(q), [q]);
  const { scope, missing } = useMemo(() => {
    if (!sel.graph.length) return { scope: null as Set<string> | null, missing: [] as string[] };
    const byName = new Map(model.doc.nodes.map((n) => [n.name.toLowerCase(), n.id]));
    const out = new Set<string>();
    const missing: string[] = [];
    for (const g of sel.graph) {
      const id = byName.get(g.name);
      if (!id) {
        missing.push(g.name);
        continue;
      }
      walk(model, [id], 'up', g.up).forEach((_, k) => out.add(k));
      walk(model, [id], 'down', g.down).forEach((_, k) => out.add(k));
    }
    return { scope: out, missing };
  }, [model, sel]);

  const allTechs = useMemo(() => Object.keys(model.ins.summary.technologies), [model]);

  const { rows, groupCounts } = useMemo(() => {
    const upN = (id: string) => model.up.get(id)?.length ?? 0;
    const downN = (id: string) => model.down.get(id)?.length ?? 0;
    const base = model.doc.nodes.filter(
      (n) =>
        kinds.has(n.kind) &&
        (!scope || scope.has(n.id)) &&
        (!connectedOnly || upN(n.id) + downN(n.id) > 0 || scope?.has(n.id)) &&
        (techs.size === 0 || techList(model, n.id).some((t) => techs.has(t))) &&
        matches(model, sel, n),
    );
    const key = (n: LNode) => groupOf(model, groupBy, n.id);
    const counts = new Map<string, number>();
    base.forEach((n) => counts.set(key(n), (counts.get(key(n)) ?? 0) + 1));
    const list = base.filter((n) => groupFilter.size === 0 || groupFilter.has(key(n)));
    const val = (n: LNode) => (sort.key === 'name' ? n.name.toLowerCase() : sort.key === 'up' ? upN(n.id) : downN(n.id));
    list.sort((a, b) => {
      const ga = key(a);
      const gb = key(b);
      if (ga !== gb) return counts.get(gb)! - counts.get(ga)! || ga.localeCompare(gb);
      const [x, y] = [val(a), val(b)];
      const c = x < y ? -1 : x > y ? 1 : a.name.localeCompare(b.name);
      return sort.dir === 'asc' ? c : -c;
    });
    return { rows: list, groupCounts: [...counts.entries()].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0])) };
  }, [model, kinds, techs, connectedOnly, sort, groupBy, groupFilter, sel, scope]);

  useEffect(() => setPage(1), [q, kinds, techs, connectedOnly, groupBy, groupFilter]);
  useEffect(() => setGroupFilter(new Set()), [groupBy]);

  const items = useMemo(() => {
    const out: ({ kind: 'group'; key: string; count: number } | { kind: 'row'; node: LNode })[] = [];
    const counts = new Map(groupCounts);
    let last: string | null = null;
    for (const n of rows) {
      const k = groupBy === 'none' ? null : groupOf(model, groupBy, n.id);
      if (k !== null && k !== last) out.push({ kind: 'group', key: k, count: counts.get(k) ?? 0 });
      last = k;
      out.push({ kind: 'row', node: n });
    }
    return out;
  }, [rows, groupBy, groupCounts, model]);

  const ids = useMemo(() => rows.map((n) => n.id), [rows]);
  const toggle = (set: Set<string>, v: string, on: boolean, apply: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (on) next.add(v);
    else next.delete(v);
    apply(next);
  };
  const sortHeader = (key: SortKey, label: string, align?: 'right') => (
    <TableHeader
      componentId={`sts-lb-lineage.table.sort-${key}`}
      sortable
      align={align}
      style={key === 'name' ? WIDE : NARROW}
      sortDirection={sort.key === key ? sort.dir : 'none'}
      onToggleSort={() => setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))}
    >
      {label}
    </TableHeader>
  );
  const pageItems = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="lbl-objects">
      <div className="lbl-filters" aria-label="Filters">
        <Typography.Title level={4}>Type</Typography.Title>
        {(['table', 'job'] as const).map((k) => (
          <Checkbox key={k} componentId={`sts-lb-lineage.filter.kind-${k}`} isChecked={kinds.has(k)} onChange={(on) => toggle(kinds, k, on, setKinds)}>
            {kindLabel(k) + 's'}
          </Checkbox>
        ))}
        <Typography.Title level={4}>Source technology</Typography.Title>
        {allTechs.map((t) => (
          <Checkbox key={t} componentId="sts-lb-lineage.filter.tech" isChecked={techs.has(t)} onChange={(on) => toggle(techs, t, on, setTechs)}>
            {t}
          </Checkbox>
        ))}
        {(groupBy === 'process' || groupBy === 'schema') && (
          <>
            <Typography.Title level={4}>{GROUP_BY_LABEL[groupBy]}</Typography.Title>
            <div className="lbl-group-filter">
              {groupCounts.map(([g, n]) => (
                <Checkbox key={g} componentId="sts-lb-lineage.filter.group" isChecked={groupFilter.has(g)} onChange={(on) => toggle(groupFilter, g, on, setGroupFilter)}>
                  <span className="lbl-ellipsis" title={g}>{`${groupLabel(groupBy, g)} (${n})`}</span>
                </Checkbox>
              ))}
            </div>
          </>
        )}
        <Typography.Title level={4}>Display</Typography.Title>
        <Checkbox componentId="sts-lb-lineage.filter.connected" isChecked={connectedOnly} onChange={(on) => setConnectedOnly(on)}>
          Only objects with lineage
        </Checkbox>
      </div>

      <div className="lbl-objects-main">
        <div className="lbl-toolbar">
          <SegmentedControlGroup componentId="sts-lb-lineage.view" name="view" value={view} onChange={(e) => setView(e.target.value)}>
            <SegmentedControlButton value="list">List</SegmentedControlButton>
            <SegmentedControlButton value="graph">Graph</SegmentedControlButton>
          </SegmentedControlGroup>
          <SimpleSelect componentId="sts-lb-lineage.group-by" id="sts-lb-lineage-group-by" label="Group by" value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)} width={190}>
            {(Object.keys(GROUP_BY_LABEL) as GroupBy[]).map((g) => (
              <SimpleSelectOption key={g} value={g}>
                {GROUP_BY_LABEL[g]}
              </SimpleSelectOption>
            ))}
          </SimpleSelect>
          <div className="lbl-selector">
            <Input
              componentId="sts-lb-lineage.selector"
              prefix={<SearchIcon />}
              placeholder="Search by name, or filter: role:source  process:wf_x  +TABLE+"
              aria-label="Search or selector"
              allowClear
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                if (e.target.value === '') setQ('');
              }}
              onPressEnter={() => setQ(draft)}
              onBlur={() => draft !== q && setQ(draft)}
            />
          </div>
          <span className="lbl-nowrap">
            <Typography.Text color="secondary">{`${rows.length} results`}</Typography.Text>
          </span>
        </div>
        <div className="lbl-row lbl-examples">
          <Typography.Hint>Try:</Typography.Hint>
          {[
            ['Sources to ingest', 'role:source'],
            ['Shared tables', 'role:shared'],
            ['Terminal outputs', 'role:terminal'],
            ['High complexity jobs', 'complexity:high'],
          ].map(([label, sel]) => (
            <Typography.Link key={sel} componentId="sts-lb-lineage.selector.example" onClick={() => setQ(sel)}>
              {label}
            </Typography.Link>
          ))}
          <InfoTooltip
            componentId="sts-lb-lineage.selector.help"
            iconTitle="Selector syntax"
            content="Press Enter to apply. Combine filters with spaces: process:<name>, tech:<INFA>, role:source|intermediate|terminal|orphan|shared, schema:<name>, complexity:low|medium|high|very_high. Graph scope: +NAME (all upstream), NAME+ (all downstream), 2+NAME+1 (2 hops up, 1 down). Any other word filters by name."
          />
        </div>
        {missing.length > 0 && (
          <Alert componentId="sts-lb-lineage.selector.missing" type="warning" closable={false} message={`Not found: ${missing.join(', ')}. Graph scopes need the exact object name.`} />
        )}

        {rows.length === 0 ? (
          <Empty title="No matching objects" description="Change the selector or the filters." />
        ) : view === 'graph' ? (
          <GraphView model={model} scope={ids} groupBy={groupBy} onOpenDetails={onOpen} onOpenProcess={onOpenProcess} />
        ) : (
          <Table
            scrollable
            pagination={
              <Pagination componentId="sts-lb-lineage.table.pagination" currentPageIndex={page} pageSize={PAGE_SIZE} numTotal={items.length} onChange={(p) => setPage(p)} hideOnSinglePage />
            }
          >
            <TableRow isHeader>
              {sortHeader('name', 'Name')}
              <TableHeader componentId="sts-lb-lineage.table.role" style={MID}>Role</TableHeader>
              <TableHeader componentId="sts-lb-lineage.table.tech" style={MID}>Technology</TableHeader>
              <TableHeader componentId="sts-lb-lineage.table.process">Parent process</TableHeader>
              <TableHeader componentId="sts-lb-lineage.table.cx" style={NARROW}>Complexity</TableHeader>
              {sortHeader('up', 'Upstream', 'right')}
              {sortHeader('down', 'Downstream', 'right')}
            </TableRow>
            {pageItems.map((it) =>
              it.kind === 'group' ? (
                <TableRow key={`grp:${it.key}`}>
                  <TableCell style={WIDE}>
                    <span className="lbl-name" title={it.key}>
                      {groupBy === 'process' ? <WorkflowsIcon aria-hidden /> : <FolderIcon aria-hidden />}
                      {groupBy === 'process' && model.procByName.has(it.key) ? (
                        <Typography.Link componentId="sts-lb-lineage.table.group-open" onClick={() => onOpenProcess(it.key)}>
                          {groupLabel(groupBy, it.key)}
                        </Typography.Link>
                      ) : (
                        <Typography.Text bold>{groupLabel(groupBy, it.key)}</Typography.Text>
                      )}
                      <Tag componentId="sts-lb-lineage.table.group-count">{`${it.count}`}</Tag>
                    </span>
                  </TableCell>
                  <TableCell style={MID} />
                  <TableCell style={MID} />
                  <TableCell />
                  <TableCell style={NARROW} />
                  <TableCell style={NARROW} />
                  <TableCell style={NARROW} />
                </TableRow>
              ) : (
                <Row key={it.node.id} model={model} n={it.node} onOpen={onOpen} />
              ),
            )}
          </Table>
        )}
      </div>
    </div>
  );
}

function Row({ model, n, onOpen }: { model: Model; n: LNode; onOpen: (id: string) => void }) {
  const cx = n.kind === 'job' ? model.programs.get(n.name)?.complexity : undefined;
  return (
    <TableRow>
      <TableCell style={WIDE}>
        <span className="lbl-name lbl-indent">
          <KindIcon kind={n.kind} />
          <Typography.Link componentId="sts-lb-lineage.table.open" onClick={() => onOpen(n.id)}>
            {n.name}
          </Typography.Link>
          {n.tags.includes('temp') && <Tag componentId="sts-lb-lineage.tag.temp">temp</Tag>}
        </span>
      </TableCell>
      <TableCell style={MID}>{roleLabel(n.role) + (n.process === SHARED ? ' · shared' : '')}</TableCell>
      <TableCell style={MID}>{techList(model, n.id).join(', ')}</TableCell>
      <TableCell>
        <span title={n.process}>{n.process ? shortName(n.process) : '-'}</span>
      </TableCell>
      <TableCell style={NARROW}>{cx ? <LevelTag level={cx} /> : '-'}</TableCell>
      <TableCell align="right" style={NARROW}>
        {model.up.get(n.id)?.length ?? 0}
      </TableCell>
      <TableCell align="right" style={NARROW}>
        {model.down.get(n.id)?.length ?? 0}
      </TableCell>
    </TableRow>
  );
}
