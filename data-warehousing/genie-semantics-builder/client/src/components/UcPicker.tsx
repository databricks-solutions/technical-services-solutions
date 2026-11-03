import { useState } from 'react';
import {
  Checkbox,
  FormUI,
  SimpleSelect,
  SimpleSelectOption,
  Spinner,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { UcTable } from '../../../shared/brief';
import { useResource } from '../api';

const q = encodeURIComponent;

function NameSelect({
  id,
  label,
  path,
  value,
  onChange,
}: {
  id: string;
  label: string;
  path: string;
  value?: string;
  onChange: (v: string) => void;
}) {
  const names = useResource<string[]>(path);
  const empty = names.status === 'ready' && !names.data?.length;
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <SimpleSelect
        componentId={`gsb.uc.${id}`}
        id={`gsb-uc-${id}`}
        label={label}
        value={value ?? ''}
        disabled={names.status !== 'ready' || empty}
        placeholder={
          names.status === 'loading'
            ? 'Loading'
            : empty
              ? `No ${label.toLowerCase()}s you can access`
              : `Select a ${label.toLowerCase()}`
        }
        onChange={(e) => onChange(e.target.value)}
      >
        {(names.data ?? []).map((n) => (
          <SimpleSelectOption key={n} value={n}>
            {n}
          </SimpleSelectOption>
        ))}
      </SimpleSelect>
      {names.status === 'error' || names.status === 'forbidden' ? (
        <FormUI.Message type="error" message={names.error ?? 'Could not load the list.'} />
      ) : null}
    </div>
  );
}

/** Catalog and schema dropdowns, limited to what the signed-in user can access. */
export function CatalogSchemaSelect({
  idPrefix,
  purpose = 'browse',
  catalog,
  schema,
  onChange,
}: {
  idPrefix: string;
  /** publish: only regular catalogs and schemas where the user can create tables. */
  purpose?: 'browse' | 'publish';
  catalog?: string;
  schema?: string;
  onChange: (catalog: string | undefined, schema: string | undefined) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 12 }}>
      <NameSelect
        id={`${idPrefix}_catalog`}
        label="Catalog"
        path={`/api/uc/catalogs?purpose=${purpose}`}
        value={catalog}
        onChange={(c) => onChange(c, undefined)}
      />
      {catalog ? (
        <NameSelect
          key={catalog}
          id={`${idPrefix}_schema`}
          label="Schema"
          path={`/api/uc/schemas?catalog=${q(catalog)}&purpose=${purpose}`}
          value={schema}
          onChange={(s) => onChange(catalog, s)}
        />
      ) : (
        <div style={{ flex: 1 }} />
      )}
    </div>
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
  if (tables.status === 'loading') return <Spinner label="Loading tables" />;
  if (tables.status !== 'ready')
    return <FormUI.Message type="error" message={tables.error ?? 'Could not load the tables.'} />;
  if (!tables.data?.length)
    return <Typography.Text color="secondary">This schema has no tables you can access.</Typography.Text>;
  return (
    <div
      role="group"
      aria-label={`Tables in ${catalog}.${schema}`}
      style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 240, overflow: 'auto' }}
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
  );
}

/** Browse catalogs and schemas, then tick tables. Selections can span schemas. */
export function TablePicker({ value, onChange }: { value: string[]; onChange: (tables: string[]) => void }) {
  const [browse, setBrowse] = useState<{ catalog?: string; schema?: string }>({});
  const toggle = (full: string, on: boolean) =>
    onChange(on ? [...value.filter((t) => t !== full), full] : value.filter((t) => t !== full));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <CatalogSchemaSelect
        idPrefix="sources"
        catalog={browse.catalog}
        schema={browse.schema}
        onChange={(catalog, schema) => setBrowse({ catalog, schema })}
      />
      {browse.catalog && browse.schema && (
        <TableChecklist
          key={`${browse.catalog}.${browse.schema}`}
          catalog={browse.catalog}
          schema={browse.schema}
          selected={value}
          onToggle={toggle}
        />
      )}
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
