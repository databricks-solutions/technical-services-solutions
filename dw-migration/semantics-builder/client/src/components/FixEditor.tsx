import {
  Button,
  PlusIcon,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  TrashIcon,
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

/** The key of a proposed key fix, editable. The server rebuilds the SQL from the edits. */
export function FixEditor({
  rows,
  edits,
  onChange,
}: {
  rows: FixRow[];
  edits: FixEdits;
  onChange: (e: FixEdits) => void;
}) {
  const key = rows.find((r): r is KeyRow => r.kind === 'key');
  return key ? <KeyEditor row={key} edits={edits} onChange={onChange} /> : null;
}
