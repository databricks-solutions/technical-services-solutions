import { useState } from 'react';
import type { ReactNode } from 'react';
import {
  CatalogIcon,
  Checkbox,
  ChevronDownIcon,
  ChevronRightIcon,
  FormUI,
  Input,
  SchemaIcon,
  SearchIcon,
  Spinner,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { UcTable } from '../../../shared/brief';
import { useResource } from '../api';

const q = encodeURIComponent;
const INDENT = 20;

function Loading({ label }: { label: string }) {
  return (
    <li style={{ listStyle: 'none', padding: 4 }}>
      <Spinner size="small" label={label} />
    </li>
  );
}

/** A disclosure row: a button that opens its children, which load only when open. */
function Node({
  icon,
  label,
  count,
  depth,
  children,
}: {
  icon: ReactNode;
  label: string;
  count: number;
  depth: number;
  children: () => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li style={{ listStyle: 'none' }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          width: '100%',
          padding: `4px 4px 4px ${depth * INDENT + 4}px`,
          border: 'none',
          borderRadius: 4,
          background: 'transparent',
          color: 'var(--db-text-base)',
          cursor: 'pointer',
          textAlign: 'left',
          font: 'inherit',
          fontSize: 13,
        }}
      >
        {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
        {icon}
        <span>{label}</span>
        {count > 0 && (
          <Tag componentId="gsb.uc.node_count" color="indigo">
            {count} selected
          </Tag>
        )}
      </button>
      {open && <ul style={{ margin: 0, padding: 0 }}>{children()}</ul>}
    </li>
  );
}

function TableChecklist({
  catalog,
  schema,
  selected,
  onToggle,
}: {
  catalog: string;
  schema: string;
  selected: string[];
  onToggle: (fullName: string, on: boolean) => void;
}) {
  const tables = useResource<UcTable[]>(`/api/uc/tables?catalog=${q(catalog)}&schema=${q(schema)}`);
  const pad = { paddingLeft: 2 * INDENT + 28 };
  if (tables.status === 'loading') return <Loading label="Loading tables" />;
  if (tables.status !== 'ready')
    return (
      <li style={{ listStyle: 'none' }}>
        <FormUI.Message type="error" message={tables.error ?? 'Could not load the tables.'} />
      </li>
    );
  if (!tables.data?.length)
    return (
      <li style={{ listStyle: 'none', ...pad }}>
        <Typography.Text color="secondary">No tables you can access.</Typography.Text>
      </li>
    );
  return (
    <li style={{ listStyle: 'none', ...pad }}>
      <div
        role="group"
        aria-label={`Tables in ${catalog}.${schema}`}
        style={{ display: 'flex', flexDirection: 'column', gap: 2 }}
      >
        {tables.data.map((t) => {
          const full = `${catalog}.${schema}.${t.name}`;
          return (
            <Checkbox
              key={t.name}
              componentId="gsb.uc.table"
              isChecked={selected.includes(full)}
              onChange={(on) => onToggle(full, on)}
            >
              {t.name}
              {t.type && t.type !== 'MANAGED' && t.type !== 'EXTERNAL' ? (
                <Typography.Text color="secondary"> ({t.type.toLowerCase().replace(/_/g, ' ')})</Typography.Text>
              ) : null}
            </Checkbox>
          );
        })}
      </div>
    </li>
  );
}

function SchemaList({
  catalog,
  selected,
  onToggle,
}: {
  catalog: string;
  selected: string[];
  onToggle: (fullName: string, on: boolean) => void;
}) {
  const schemas = useResource<string[]>(`/api/uc/schemas?purpose=browse&catalog=${q(catalog)}`);
  if (schemas.status === 'loading') return <Loading label="Loading schemas" />;
  if (schemas.status !== 'ready')
    return (
      <li style={{ listStyle: 'none' }}>
        <FormUI.Message type="error" message={schemas.error ?? 'Could not load the schemas.'} />
      </li>
    );
  return (
    <>
      {(schemas.data ?? []).map((s) => (
        <Node
          key={s}
          icon={<SchemaIcon />}
          label={s}
          depth={1}
          count={selected.filter((t) => t.startsWith(`${catalog}.${s}.`)).length}
        >
          {() => <TableChecklist catalog={catalog} schema={s} selected={selected} onToggle={onToggle} />}
        </Node>
      ))}
    </>
  );
}

/** The filter and the catalog tree that both pickers share. */
function CatalogTree({
  countOf,
  children,
}: {
  countOf: (catalog: string) => number;
  children: (catalog: string) => ReactNode;
}) {
  const catalogs = useResource<string[]>('/api/uc/catalogs?purpose=browse');
  const [filter, setFilter] = useState('');
  const shown = (catalogs.data ?? []).filter((c) => c.toLowerCase().includes(filter.trim().toLowerCase()));
  return (
    <>
      <Input
        componentId="gsb.uc.filter"
        aria-label="Filter catalogs"
        placeholder="Filter catalogs"
        prefix={<SearchIcon />}
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        allowClear
        style={{ maxWidth: 360 }}
      />
      <div
        style={{
          maxHeight: 360,
          overflow: 'auto',
          padding: 4,
          border: '1px solid var(--db-border-base)',
          borderRadius: 8,
        }}
      >
        {catalogs.status !== 'loading' && catalogs.status !== 'ready' && (
          <FormUI.Message type="error" message={catalogs.error ?? 'Could not load the catalogs.'} />
        )}
        <ul aria-label="Unity Catalog" style={{ margin: 0, padding: 0 }}>
          {catalogs.status === 'loading' && <Loading label="Loading catalogs" />}
          {shown.map((c) => (
            <Node key={c} icon={<CatalogIcon />} label={c} depth={0} count={countOf(c)}>
              {() => children(c)}
            </Node>
          ))}
        </ul>
      </div>
    </>
  );
}

/** Catalog Explorer style: open catalogs and schemas, tick tables. Selections can span schemas. */
export function TablePicker({ value, onChange }: { value: string[]; onChange: (tables: string[]) => void }) {
  const toggle = (full: string, on: boolean) =>
    onChange(on ? [...value.filter((t) => t !== full), full] : value.filter((t) => t !== full));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <CatalogTree countOf={(c) => value.filter((t) => t.startsWith(`${c}.`)).length}>
        {(c) => <SchemaList catalog={c} selected={value} onToggle={toggle} />}
      </CatalogTree>
      {value.length > 0 && (
        <div aria-label="Selected tables" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {value.map((t) => (
            <Tag
              key={t}
              componentId="gsb.uc.selected"
              closable
              closeButtonProps={{ 'aria-label': `Remove ${t}` }}
              onClose={() => toggle(t, false)}
            >
              {t}
            </Tag>
          ))}
        </div>
      )}
    </div>
  );
}

function SchemaChecklist({
  catalog,
  value,
  onChange,
}: {
  catalog: string;
  value: string;
  onChange: (schema: string) => void;
}) {
  const schemas = useResource<string[]>(`/api/uc/schemas?purpose=browse&catalog=${q(catalog)}`);
  if (schemas.status === 'loading') return <Loading label="Loading schemas" />;
  if (schemas.status !== 'ready')
    return (
      <li style={{ listStyle: 'none' }}>
        <FormUI.Message type="error" message={schemas.error ?? 'Could not load the schemas.'} />
      </li>
    );
  return (
    <li style={{ listStyle: 'none', paddingLeft: INDENT + 28 }}>
      <div
        role="group"
        aria-label={`Schemas in ${catalog}`}
        style={{ display: 'flex', flexDirection: 'column', gap: 2 }}
      >
        {(schemas.data ?? []).map((s) => {
          const full = `${catalog}.${s}`;
          return (
            <Checkbox
              key={s}
              componentId="gsb.uc.schema"
              isChecked={value === full}
              onChange={(on) => onChange(on ? full : '')}
            >
              {s}
            </Checkbox>
          );
        })}
      </div>
    </li>
  );
}

/** The same tree as the table picker, down to schemas: tick one schema. */
export function SchemaPicker({ value, onChange }: { value: string; onChange: (schema: string) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <CatalogTree countOf={(c) => (value.startsWith(`${c}.`) ? 1 : 0)}>
        {(c) => <SchemaChecklist catalog={c} value={value} onChange={onChange} />}
      </CatalogTree>
      {value && (
        <div aria-label="Selected schema" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Tag
            componentId="gsb.uc.selected_schema"
            closable
            closeButtonProps={{ 'aria-label': `Remove ${value}` }}
            onClose={() => onChange('')}
          >
            {value}
          </Tag>
        </div>
      )}
    </div>
  );
}
