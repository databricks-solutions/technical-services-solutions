import {
  Button,
  Checkbox,
  Input,
  PlusIcon,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  TrashIcon,
  Typography,
} from '@databricks/design-system';
import type { FixColumn, FixEdits, FixRow } from '../../../shared/readiness';
import { MONO } from './SqlBlock';

type KeyRow = Extract<FixRow, { kind: 'key' }>;

function ColumnSelect({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: FixColumn[];
  onChange: (v: string) => void;
}) {
  return (
    <SimpleSelect
      componentId="gsb.fix.column"
      id={id}
      aria-label={label}
      value={value}
      placeholder="Pick a column"
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <SimpleSelectOption key={o.name} value={o.name}>
          {o.name} ({o.type})
        </SimpleSelectOption>
      ))}
    </SimpleSelect>
  );
}

/** A key as column pairs: the key column, and for a foreign key the column it references. */
function KeyEditor({ row, edits, onChange }: { row: KeyRow; edits: FixEdits; onChange: (e: FixEdits) => void }) {
  const columns = edits.key?.columns ?? row.columns;
  const refColumns = edits.key?.refColumns ?? row.refColumns;
  const fk = row.references !== null;
  const set = (c: string[], r: string[]) =>
    onChange({ ...edits, key: { columns: c, ...(fk ? { refColumns: r } : {}) } });
  const typeOf = (opts: FixColumn[], n: string) => opts.find((o) => o.name === n)?.type ?? '';
  return (
    <Table aria-label="Key columns">
      <TableRow isHeader>
        <TableHeader componentId="gsb.fix.h_table">Table</TableHeader>
        <TableHeader componentId="gsb.fix.h_column">Key column</TableHeader>
        <TableHeader componentId="gsb.fix.h_type">Data type</TableHeader>
        {fk && <TableHeader componentId="gsb.fix.h_ref">References</TableHeader>}
        {fk && <TableHeader componentId="gsb.fix.h_ref_type">Data type</TableHeader>}
        <TableHeader componentId="gsb.fix.h_remove"> </TableHeader>
      </TableRow>
      {columns.map((c, i) => (
        // The pairs are positional, so the index is the key.
        // eslint-disable-next-line react/no-array-index-key
        <TableRow key={i}>
          <TableCell>
            <code style={MONO} title={row.table}>
              {row.table.split('.').pop()}
            </code>
          </TableCell>
          <TableCell>
            <ColumnSelect
              id={`fix-col-${i}`}
              label={`Key column ${i + 1}`}
              value={c}
              options={row.options}
              onChange={(v) =>
                set(
                  columns.map((x, j) => (j === i ? v : x)),
                  refColumns
                )
              }
            />
          </TableCell>
          <TableCell>{typeOf(row.options, c)}</TableCell>
          {fk && (
            <TableCell>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <code style={MONO} title={row.references ?? ''}>
                  {row.references?.split('.').pop()}
                </code>
                <ColumnSelect
                  id={`fix-ref-${i}`}
                  label={`Referenced column ${i + 1}`}
                  value={refColumns[i] ?? ''}
                  options={row.refOptions}
                  onChange={(v) =>
                    set(
                      columns,
                      columns.map((_, j) => (j === i ? v : (refColumns[j] ?? '')))
                    )
                  }
                />
              </div>
            </TableCell>
          )}
          {fk && <TableCell>{typeOf(row.refOptions, refColumns[i] ?? '')}</TableCell>}
          <TableCell>
            <Button
              componentId="gsb.fix.remove_column"
              icon={<TrashIcon />}
              aria-label={`Remove key column ${i + 1}`}
              disabled={columns.length === 1}
              onClick={() =>
                set(
                  columns.filter((_, j) => j !== i),
                  refColumns.filter((_, j) => j !== i)
                )
              }
            />
          </TableCell>
        </TableRow>
      ))}
      <TableRow>
        <TableCell>
          <Button
            componentId="gsb.fix.add_column"
            size="small"
            icon={<PlusIcon />}
            disabled={columns.length >= 10}
            onClick={() => set([...columns, ''], [...refColumns, ''])}
          >
            Add a column
          </Button>
        </TableCell>
      </TableRow>
    </Table>
  );
}

/**
 * A proposed fix as rows: table, column, data type, the current value and the proposed change. With onChange the
 * proposed text, the rows to include and the key columns are editable. The server rebuilds the SQL from the edits.
 */
export function FixEditor({
  rows,
  edits,
  onChange,
}: {
  rows: FixRow[];
  edits: FixEdits;
  onChange?: (e: FixEdits) => void;
}) {
  const key = rows.find((r): r is KeyRow => r.kind === 'key');
  if (key) {
    if (onChange) return <KeyEditor row={key} edits={edits} onChange={onChange} />;
    return (
      <Typography.Text>
        <code style={MONO}>{key.table}</code> ({key.columns.join(', ')})
        {key.references && (
          <>
            {' '}
            references <code style={MONO}>{key.references}</code> ({key.refColumns.join(', ')})
          </>
        )}
      </Typography.Text>
    );
  }
  const comments = rows.flatMap((r) => (r.kind === 'comment' ? [r] : []));
  const skip = new Set(edits.skip ?? []);
  const text = (r: (typeof comments)[number]) => edits.comments?.[r.index] ?? r.proposed;
  const put = (index: number, value: string) => {
    const next = [...(edits.comments ?? [])];
    while (next.length <= index) next.push(null);
    next[index] = value;
    onChange?.({ ...edits, comments: next });
  };
  // In review, one block per column with a full-width text box, so long proposals are easy to read and edit.
  if (onChange)
    return (
      <ol
        aria-label="Proposed changes"
        style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }}
      >
        {comments.map((r) => {
          const name = r.column ?? r.table.split('.').pop() ?? r.table;
          const off = skip.has(r.index);
          return (
            <li
              key={r.index}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                padding: 12,
                border: '1px solid var(--db-border-base)',
                borderRadius: 8,
                opacity: off ? 0.6 : 1,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <Checkbox
                  componentId="gsb.fix.include"
                  aria-label={`Include ${name}`}
                  isChecked={!off}
                  onChange={(on) =>
                    onChange({
                      ...edits,
                      skip: on ? [...skip].filter((i) => i !== r.index) : [...skip, r.index],
                    })
                  }
                />
                <code style={MONO}>{name}</code>
                <Typography.Text color="secondary">{r.column ? (r.type ?? '') : 'Table description'}</Typography.Text>
              </div>
              <Typography.Text color="secondary" size="sm">
                Current: {r.current || 'None'}
              </Typography.Text>
              <Input.TextArea
                componentId="gsb.fix.text"
                aria-label={`Proposed description of ${name}`}
                autoSize={{ minRows: 3, maxRows: 10 }}
                maxLength={1000}
                disabled={off}
                value={text(r)}
                onChange={(e) => put(r.index, e.target.value)}
              />
            </li>
          );
        })}
      </ol>
    );
  // Read-only: a fix covers one table, so the table is in the title; the proposal gets the most room.
  const W = { column: { flex: '0 0 22%' }, type: { flex: '0 0 12%' }, current: { flex: 2 }, proposed: { flex: 4 } };
  return (
    <Table aria-label="Proposed changes" scrollable>
      <TableRow isHeader>
        <TableHeader componentId="gsb.fix.h_column" style={W.column}>
          Column
        </TableHeader>
        <TableHeader componentId="gsb.fix.h_type" style={W.type}>
          Data type
        </TableHeader>
        <TableHeader componentId="gsb.fix.h_current" style={W.current}>
          Current description
        </TableHeader>
        <TableHeader componentId="gsb.fix.h_proposed" style={W.proposed}>
          Proposed description (AI)
        </TableHeader>
      </TableRow>
      {comments.map((r) => (
        <TableRow key={r.index}>
          <TableCell style={W.column}>
            <code style={MONO}>{r.column ?? r.table.split('.').pop()}</code>
          </TableCell>
          <TableCell style={W.type}>{r.column ? (r.type ?? '') : 'Table'}</TableCell>
          <TableCell multiline style={W.current}>
            <Typography.Text color="secondary">{r.current || 'None'}</Typography.Text>
          </TableCell>
          <TableCell multiline style={W.proposed}>
            <Typography.Text>{r.proposed}</Typography.Text>
          </TableCell>
        </TableRow>
      ))}
    </Table>
  );
}
