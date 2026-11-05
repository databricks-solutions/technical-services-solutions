import {
  Button,
  Drawer,
  Empty,
  FileCodeIcon,
  KeyValueList,
  KeyValueListItem,
  ShareNodesIcon,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tabs,
  Tag,
  Typography,
  WorkflowsIcon,
} from '@databricks/design-system';

import { type LEdge, type LNode, type LProgram, type Model, SHARED, fmtBytes, shortName, techList } from './data';
import { KindIcon, LevelMix, LevelTag, ROLE_HELP, kindLabel, levelLabel, plural, roleLabel } from './ui';

const ProcLink = ({ name, onOpenProcess }: { name: string; onOpenProcess: (p: string) => void }) => (
  <Typography.Link componentId="sts-lb-lineage.drawer.proc" onClick={() => onOpenProcess(name)}>
    <span title={name}>{shortName(name)}</span>
  </Typography.Link>
);

/** One-line summary of why a program got its complexity level. */
export function driversText(p?: LProgram): string {
  const d = (p?.drivers ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  const top = (o: unknown, n: number) =>
    Object.entries((o as Record<string, number>) ?? {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, n)
      .map(([k, v]) => `${k} ${v}`)
      .join(', ');
  if (d.transformations) parts.push(top(d.transformations, 4));
  if (d.functions) {
    const total = Object.values(d.functions as Record<string, number>).reduce((a, b) => a + b, 0);
    parts.push(`${total} function calls`);
  }
  for (const [k, label] of [
    ['embeddedSql', 'SQL statements'],
    ['dynamicSql', 'dynamic SQL'],
    ['loops', 'loops/cursors'],
    ['conditionals', 'conditionals'],
    ['parameters', 'parameters'],
    ['statements', 'statements'],
    ['lines', 'lines'],
  ] as const)
    if (d[k]) parts.push(`${d[k]} ${label}`);
  return parts.filter(Boolean).join(' · ') || '-';
}

export function ObjectDrawer({
  model,
  id,
  onClose,
  onOpen,
  onOpenProcess,
  onGraph,
  onImpact,
}: {
  model: Model;
  id?: string;
  onClose: () => void;
  onOpen: (id: string) => void;
  onOpenProcess: (p: string) => void;
  onGraph: (id: string) => void;
  onImpact: (id: string) => void;
}) {
  const node = id ? model.byId.get(id) : undefined;
  return (
    <Drawer.Root open={!!node} onOpenChange={(open) => !open && onClose()}>
      <Drawer.Content
        componentId="sts-lb-lineage.details"
        width={680}
        title={
          node && (
            <span className="lbl-name">
              <KindIcon kind={node.kind} />
              {node.name}
            </span>
          )
        }
      >
        {node && <ObjectDetails model={model} node={node} onOpen={onOpen} onOpenProcess={onOpenProcess} onGraph={onGraph} onImpact={onImpact} />}
      </Drawer.Content>
    </Drawer.Root>
  );
}

function ObjectDetails({
  model,
  node,
  onOpen,
  onOpenProcess,
  onGraph,
  onImpact,
}: {
  model: Model;
  node: LNode;
  onOpen: (id: string) => void;
  onOpenProcess: (p: string) => void;
  onGraph: (id: string) => void;
  onImpact: (id: string) => void;
}) {
  const up = model.up.get(node.id) ?? [];
  const down = model.down.get(node.id) ?? [];
  const programs = model.programsOf.get(node.id) ?? [];
  const hub = model.hubById.get(node.id);
  const prog = node.kind === 'job' ? model.programs.get(node.name) : undefined;
  const own = (c: string) => c.slice(0, c.lastIndexOf('.')).toLowerCase() === node.name.toLowerCase();
  const cols = (model.doc.columns ?? []).filter((c) => own(c.from) || own(c.to));
  return (
    <div className="lbl-details">
      <KeyValueList>
        <KeyValueListItem label="Type">{kindLabel(node.kind)}</KeyValueListItem>
        <KeyValueListItem label="Role">
          <span title={node.role ? ROLE_HELP[node.role] : undefined}>{roleLabel(node.role)}</span>
        </KeyValueListItem>
        <KeyValueListItem label="Technology">{techList(model, node.id).join(', ') || '-'}</KeyValueListItem>
        <KeyValueListItem label="Parent process">
          {node.process && model.procByName.has(node.process) ? (
            <ProcLink name={node.process} onOpenProcess={onOpenProcess} />
          ) : node.process === SHARED ? (
            `Shared by ${hub?.processCount ?? 0} processes`
          ) : (
            '-'
          )}
        </KeyValueListItem>
        {prog?.complexity && (
          <KeyValueListItem label="Complexity">
            <span className="lbl-row">
              <LevelTag level={prog.complexity} />
              <Typography.Text color="secondary">{driversText(prog)}</Typography.Text>
            </span>
          </KeyValueListItem>
        )}
        {node.uc && (
          <KeyValueListItem label="Suggested UC target">
            <span className="lbl-row">
              <Typography.Text code>{node.uc.target}</Typography.Text>
              <Tag componentId="sts-lb-lineage.details.layer">{node.uc.layer}</Tag>
            </span>
          </KeyValueListItem>
        )}
        {node.volume && (
          <KeyValueListItem label="Volume">
            {[node.volume.rows !== undefined && `${node.volume.rows.toLocaleString()} rows`, node.volume.bytes !== undefined && fmtBytes(node.volume.bytes)]
              .filter(Boolean)
              .join(' · ')}
          </KeyValueListItem>
        )}
        {node.tags.length > 0 && (
          <KeyValueListItem label="Tags">
            {node.tags.map((t) => (
              <Tag key={t} componentId="sts-lb-lineage.details.tag">
                {t}
              </Tag>
            ))}
          </KeyValueListItem>
        )}
      </KeyValueList>
      {hub && (
        <div>
          <Typography.Title level={4}>Shared table</Typography.Title>
          <Typography.Paragraph>
            {`Written by ${hub.writers.length || 'no'} and read by ${hub.readers.length} processes. Cut over together, or keep a contract between them.`}
          </Typography.Paragraph>
          <div className="lbl-row">
            {[...hub.writers.map((w) => ['writes', w]), ...hub.readers.map((r) => ['reads', r])].map(([how, p]) => (
              <Tag key={how + p} componentId="sts-lb-lineage.details.hub-proc" onClick={() => onOpenProcess(p)}>
                {`${how}: ${shortName(p)}`}
              </Tag>
            ))}
          </div>
        </div>
      )}
      <div className="lbl-row">
        <Button componentId="sts-lb-lineage.details.graph" type="primary" icon={<ShareNodesIcon />} onClick={() => onGraph(node.id)} disabled={up.length + down.length === 0}>
          See lineage graph
        </Button>
        <Button componentId="sts-lb-lineage.details.impact" onClick={() => onImpact(node.id)} disabled={down.length === 0}>
          Impact analysis
        </Button>
      </div>
      <Tabs.Root componentId="sts-lb-lineage.details.tabs" defaultValue={up.length ? 'up' : 'down'}>
        <Tabs.List>
          <Tabs.Trigger value="up">{`Upstream (${up.length})`}</Tabs.Trigger>
          <Tabs.Trigger value="down">{`Downstream (${down.length})`}</Tabs.Trigger>
          <Tabs.Trigger value="programs">{`Programs (${programs.length})`}</Tabs.Trigger>
          {cols.length > 0 && <Tabs.Trigger value="columns">{`Columns (${cols.length})`}</Tabs.Trigger>}
        </Tabs.List>
        <Tabs.Content value="up">
          <EdgeTable model={model} edges={up} side="from" onOpen={onOpen} />
        </Tabs.Content>
        <Tabs.Content value="down">
          <EdgeTable model={model} edges={down} side="to" onOpen={onOpen} />
        </Tabs.Content>
        <Tabs.Content value="programs">
          {programs.length === 0 ? (
            <Empty description="No program reads or writes this object." />
          ) : (
            <Table size="small">
              <TableRow isHeader>
                <TableHeader componentId="sts-lb-lineage.programs.name">Program</TableHeader>
                <TableHeader componentId="sts-lb-lineage.programs.role">Access</TableHeader>
                <TableHeader componentId="sts-lb-lineage.programs.cx">Complexity</TableHeader>
                <TableHeader componentId="sts-lb-lineage.programs.proc">Process</TableHeader>
              </TableRow>
              {programs.map(({ program, role }) => {
                const pr = model.processOfProgram.get(program.name);
                return (
                  <TableRow key={program.name + role}>
                    <TableCell>
                      <span className="lbl-name" title={program.name}>
                        <FileCodeIcon aria-hidden />
                        {shortName(program.name)}
                      </span>
                    </TableCell>
                    <TableCell>{role === 'reads' ? 'Reads' : 'Writes'}</TableCell>
                    <TableCell>{program.complexity ? <LevelTag level={program.complexity} /> : '-'}</TableCell>
                    <TableCell>{pr ? <ProcLink name={pr} onOpenProcess={onOpenProcess} /> : '-'}</TableCell>
                  </TableRow>
                );
              })}
            </Table>
          )}
        </Tabs.Content>
        {cols.length > 0 && (
          <Tabs.Content value="columns">
            <Typography.Hint>Parsed from the SQL embedded in ETL programs. Statements that do not parse are skipped.</Typography.Hint>
            <Table size="small">
              <TableRow isHeader>
                <TableHeader componentId="sts-lb-lineage.columns.from">From column</TableHeader>
                <TableHeader componentId="sts-lb-lineage.columns.to">To column</TableHeader>
                <TableHeader componentId="sts-lb-lineage.columns.via">Program</TableHeader>
              </TableRow>
              {cols.map((c) => (
                <TableRow key={c.from + '>' + c.to}>
                  <TableCell>
                    <code>{c.from}</code>
                  </TableCell>
                  <TableCell>
                    <code>{c.to}</code>
                  </TableCell>
                  <TableCell>{c.via.map(shortName).join(', ')}</TableCell>
                </TableRow>
              ))}
            </Table>
          </Tabs.Content>
        )}
      </Tabs.Root>
    </div>
  );
}

function EdgeTable({ model, edges, side, onOpen }: { model: Model; edges: LEdge[]; side: 'from' | 'to'; onOpen: (id: string) => void }) {
  if (edges.length === 0) return <Empty description={`No ${side === 'from' ? 'upstream' : 'downstream'} objects.`} />;
  return (
    <Table size="small">
      <TableRow isHeader>
        <TableHeader componentId="sts-lb-lineage.edges.name">Name</TableHeader>
        <TableHeader componentId="sts-lb-lineage.edges.via">Via</TableHeader>
        <TableHeader componentId="sts-lb-lineage.edges.grain">Grain</TableHeader>
      </TableRow>
      {edges.map((e) => {
        const other = model.byId.get(e[side])!;
        return (
          <TableRow key={e.from + e.to + e.kind}>
            <TableCell>
              <span className="lbl-name">
                <KindIcon kind={other.kind} />
                <Typography.Link componentId="sts-lb-lineage.edges.open" onClick={() => onOpen(other.id)}>
                  {other.name}
                </Typography.Link>
              </span>
            </TableCell>
            <TableCell>
              <span title={e.via.join('\n')}>
                {e.via.map(shortName).slice(0, 2).join(', ')}
                {e.via.length > 2 ? ` +${e.via.length - 2}` : ''}
              </span>
            </TableCell>
            <TableCell>{e.kind === 'orchestration' ? 'Orchestration' : e.grain === 'statement' ? 'Statement' : 'Job'}</TableCell>
          </TableRow>
        );
      })}
    </Table>
  );
}

export function ProcessDrawer({
  model,
  name,
  onClose,
  onOpen,
  onOpenProcess,
  onLineage,
  onImpact,
}: {
  model: Model;
  name?: string;
  onClose: () => void;
  onOpen: (id: string) => void;
  onOpenProcess: (p: string) => void;
  onLineage: (name: string) => void;
  onImpact: (name: string) => void;
}) {
  const p = name ? model.procByName.get(name) : undefined;
  const shared = p ? model.ins.hubs.filter((h) => h.writers.includes(p.name) || h.readers.includes(p.name)) : [];
  return (
    <Drawer.Root open={!!p} onOpenChange={(open) => !open && onClose()}>
      <Drawer.Content
        componentId="sts-lb-lineage.process"
        width={760}
        title={
          p && (
            <span className="lbl-name" title={p.name}>
              <WorkflowsIcon aria-hidden />
              {shortName(p.name)}
            </span>
          )
        }
      >
        {p && (
          <div className="lbl-details">
            <KeyValueList>
              {p.cycle !== null && (
                <KeyValueListItem label="Dependency cycle">
                  Feeds, and is fed by, other processes in the same cycle. They depend on each other.
                </KeyValueListItem>
              )}
              <KeyValueListItem label="Technology">{p.tech.join(', ') || '-'}</KeyValueListItem>
              <KeyValueListItem label="Complexity">
                <LevelMix counts={p.complexity} />
              </KeyValueListItem>
              {p.volume && (
                <KeyValueListItem label="Data volume">{`${fmtBytes(p.volume.bytes)} · ${p.volume.rows.toLocaleString()} rows (matched tables only)`}</KeyValueListItem>
              )}
              <KeyValueListItem label="Size">{`${plural(p.programs.length, 'program')} · ${plural(p.objects.length, 'object')} · ${plural(shared.length, 'shared table')}`}</KeyValueListItem>
            </KeyValueList>
            <div className="lbl-row">
              <Button componentId="sts-lb-lineage.process.lineage" type="primary" icon={<ShareNodesIcon />} onClick={() => onLineage(p.name)} disabled={p.objects.length + shared.length === 0}>
                Open process lineage
              </Button>
              <Button componentId="sts-lb-lineage.process.impact" onClick={() => onImpact(p.name)}>
                Impact analysis
              </Button>
            </div>
            <Tabs.Root componentId="sts-lb-lineage.process.tabs" defaultValue="programs">
              <Tabs.List>
                <Tabs.Trigger value="programs">{`Programs (${p.programs.length})`}</Tabs.Trigger>
                <Tabs.Trigger value="objects">{`Objects (${p.objects.length})`}</Tabs.Trigger>
                <Tabs.Trigger value="shared">{`Shared (${shared.length})`}</Tabs.Trigger>
                <Tabs.Trigger value="deps">{`Depends on (${p.upstream.length})`}</Tabs.Trigger>
                <Tabs.Trigger value="feeds">{`Feeds (${p.downstream.length})`}</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="programs">
                <Table size="small">
                  <TableRow isHeader>
                    <TableHeader componentId="sts-lb-lineage.process.prog">Program</TableHeader>
                    <TableHeader componentId="sts-lb-lineage.process.prog-type">Type</TableHeader>
                    <TableHeader componentId="sts-lb-lineage.process.prog-cx">Complexity</TableHeader>
                    <TableHeader componentId="sts-lb-lineage.process.prog-why">Why</TableHeader>
                  </TableRow>
                  {p.programs.map((name) => {
                    const prog = model.programs.get(name);
                    const jobNode = model.byId.get(`job:${name.toLowerCase()}`);
                    return (
                      <TableRow key={name}>
                        <TableCell>
                          <span className="lbl-name" title={name}>
                            <FileCodeIcon aria-hidden />
                            {jobNode ? (
                              <Typography.Link componentId="sts-lb-lineage.process.prog-open" onClick={() => onOpen(jobNode.id)}>
                                {shortName(name)}
                              </Typography.Link>
                            ) : (
                              shortName(name)
                            )}
                          </span>
                        </TableCell>
                        <TableCell>{prog?.type ?? '-'}</TableCell>
                        <TableCell>{prog?.complexity ? <LevelTag level={prog.complexity} /> : '-'}</TableCell>
                        <TableCell>
                          <span title={driversText(prog)}>{driversText(prog)}</span>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </Table>
              </Tabs.Content>
              <Tabs.Content value="objects">
                <ObjList model={model} ids={p.objects} onOpen={onOpen} />
              </Tabs.Content>
              <Tabs.Content value="shared">
                <ObjList model={model} ids={shared.map((h) => h.id)} onOpen={onOpen} />
              </Tabs.Content>
              <Tabs.Content value="deps">
                <ProcList model={model} names={p.upstream} onOpenProcess={onOpenProcess} />
              </Tabs.Content>
              <Tabs.Content value="feeds">
                <ProcList model={model} names={p.downstream} onOpenProcess={onOpenProcess} />
              </Tabs.Content>
            </Tabs.Root>
          </div>
        )}
      </Drawer.Content>
    </Drawer.Root>
  );
}

function ObjList({ model, ids, onOpen }: { model: Model; ids: string[]; onOpen: (id: string) => void }) {
  if (!ids.length) return <Empty description="None." />;
  return (
    <Table size="small">
      <TableRow isHeader>
        <TableHeader componentId="sts-lb-lineage.process.obj">Object</TableHeader>
        <TableHeader componentId="sts-lb-lineage.process.obj-role">Role</TableHeader>
      </TableRow>
      {ids.map((id) => {
        const n = model.byId.get(id)!;
        return (
          <TableRow key={id}>
            <TableCell>
              <span className="lbl-name">
                <KindIcon kind={n.kind} />
                <Typography.Link componentId="sts-lb-lineage.process.obj-open" onClick={() => onOpen(id)}>
                  {n.name}
                </Typography.Link>
              </span>
            </TableCell>
            <TableCell>{roleLabel(n.role) + (n.process === SHARED ? ' · shared' : '')}</TableCell>
          </TableRow>
        );
      })}
    </Table>
  );
}

function ProcList({ model, names, onOpenProcess }: { model: Model; names: string[]; onOpenProcess: (p: string) => void }) {
  if (!names.length) return <Empty description="No process dependencies in this direction." />;
  return (
    <Table size="small">
      <TableRow isHeader>
        <TableHeader componentId="sts-lb-lineage.process.dep">Process</TableHeader>
        <TableHeader componentId="sts-lb-lineage.process.dep-c">Highest</TableHeader>
      </TableRow>
      {names.map((n) => {
        const q = model.procByName.get(n);
        return (
          <TableRow key={n}>
            <TableCell>
              <ProcLink name={n} onOpenProcess={onOpenProcess} />
            </TableCell>
            <TableCell>{q ? <LevelTag level={q.maxComplexity} /> : '-'}</TableCell>
          </TableRow>
        );
      })}
    </Table>
  );
}

export { levelLabel };
