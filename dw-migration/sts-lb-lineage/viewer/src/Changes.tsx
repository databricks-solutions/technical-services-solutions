import { Empty, Table, TableCell, TableHeader, TableRow, Tag, Typography } from '@databricks/design-system';
import type { ReactNode } from 'react';
import { type Model, shortName } from './data';
import { plural } from './ui';

/** Differences against the lineage.json given with --compare. */
export function Changes({ model, onOpen, onOpenProcess }: { model: Model; onOpen: (id: string) => void; onOpenProcess: (p: string) => void }) {
  const d = model.doc.diff!;
  const name = (id: string) => model.byId.get(id)?.name ?? d.removedObjects.find((o) => o.id === id)?.name ?? id.replace(/^\w+:/, '');
  const obj = (id: string) =>
    model.byId.has(id) ? (
      <Typography.Link componentId="sts-lb-lineage.changes.object" onClick={() => onOpen(id)}>
        {name(id)}
      </Typography.Link>
    ) : (
      name(id)
    );
  const proc = (p: string | null) =>
    p && model.procByName.has(p) ? (
      <Typography.Link componentId="sts-lb-lineage.changes.process" onClick={() => onOpenProcess(p)}>
        {shortName(p)}
      </Typography.Link>
    ) : (
      (p ?? '-')
    );
  const total =
    d.addedObjects.length + d.removedObjects.length + d.addedEdges.length + d.removedEdges.length + d.addedProcesses.length + d.removedProcesses.length + d.movedObjects.length;
  const section = (title: string, n: number, head: string[], rows: ReactNode[][]) =>
    n > 0 && (
      <section>
        <Typography.Title level={4}>{`${title} (${n})`}</Typography.Title>
        <Table size="small">
          <TableRow isHeader>
            {head.map((h) => (
              <TableHeader key={h} componentId={`sts-lb-lineage.changes.${h.toLowerCase().replace(/ /g, "-")}`}>
                {h}
              </TableHeader>
            ))}
          </TableRow>
          {rows.map((r, i) => (
            <TableRow key={i}>
              {r.map((c, j) => (
                <TableCell key={j}>{c}</TableCell>
              ))}
            </TableRow>
          ))}
        </Table>
      </section>
    );
  return (
    <div className="lbl-details">
      <div className="lbl-row">
        <Typography.Text>{`Previous scan: ${d.previous}`}</Typography.Text>
        <Tag componentId="sts-lb-lineage.changes.total">{plural(total, 'change')}</Tag>
      </div>
      {total === 0 && <Empty description="No changes in objects, edges, or processes since the previous scan." />}
      {section('New processes', d.addedProcesses.length, ['Process'], d.addedProcesses.map((p) => [proc(p)]))}
      {section('Removed processes', d.removedProcesses.length, ['Process'], d.removedProcesses.map((p) => [p]))}
      {section('New objects', d.addedObjects.length, ['Object', 'Process'], d.addedObjects.map((id) => [obj(id), proc(model.byId.get(id)?.process ?? null)]))}
      {section('Removed objects', d.removedObjects.length, ['Object', 'Kind'], d.removedObjects.map((o) => [o.name, o.kind]))}
      {section('Objects that moved to another process', d.movedObjects.length, ['Object', 'Was in', 'Now in'], d.movedObjects.map((m) => [obj(m.id), m.from ?? '-', proc(m.to)]))}
      {section('New relationships', d.addedEdges.length, ['From', 'To', 'Kind'], d.addedEdges.map((e) => [obj(e.from), obj(e.to), e.kind]))}
      {section('Removed relationships', d.removedEdges.length, ['From', 'To', 'Kind'], d.removedEdges.map((e) => [name(e.from), name(e.to), e.kind]))}
    </div>
  );
}
