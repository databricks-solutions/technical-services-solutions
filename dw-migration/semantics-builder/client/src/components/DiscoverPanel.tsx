import { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  FormUI,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import { MAX_DISCOVER_SCHEMAS } from '../../../shared/discover';
import type { DiscoverResult, KpiGroup } from '../../../shared/discover';
import { api, useResource } from '../api';
import { ImportModal } from './ImportModal';
import { MONO } from './SqlBlock';

const q = encodeURIComponent;

/** Scan schemas for metric views and SQL views, group the same KPIs, and import the canonical view. */
export function DiscoverPanel() {
  const [catalog, setCatalog] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<DiscoverResult>();
  const [importing, setImporting] = useState<KpiGroup>();
  const catalogs = useResource<string[]>('/api/uc/catalogs?purpose=browse');
  const schemas = useResource<string[]>(catalog ? `/api/uc/schemas?catalog=${q(catalog)}` : null);

  const toggle = (s: string, on: boolean) => setPicked((p) => (on ? [...p, s] : p.filter((x) => x !== s)));
  const scan = () => {
    setBusy(true);
    setError(undefined);
    api<DiscoverResult>('/api/discover', { schemas: picked }).then(
      (r) => {
        setBusy(false);
        setResult(r);
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <section aria-label="Discover KPIs" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Text color="secondary">
        Pick up to {MAX_DISCOVER_SCHEMAS} schemas. The app reads their metric views and SQL views as you, finds the same
        KPI in two or more views, and shows where the formulas differ. It changes nothing.
      </Typography.Text>
      <div style={{ maxWidth: 320 }}>
        <FormUI.Label htmlFor="discover-catalog">Catalog</FormUI.Label>
        <SimpleSelect
          componentId="gsb.discover.catalog"
          id="discover-catalog"
          value={catalog}
          placeholder={catalogs.status === 'loading' ? 'Loading' : 'Pick a catalog'}
          onChange={(e) => setCatalog(e.target.value)}
        >
          {(catalogs.data ?? []).map((c) => (
            <SimpleSelectOption key={c} value={c}>
              {c}
            </SimpleSelectOption>
          ))}
        </SimpleSelect>
      </div>
      {catalog && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {(schemas.data ?? []).map((s) => {
            const full = `${catalog}.${s}`;
            return (
              <Checkbox
                key={full}
                componentId="gsb.discover.schema"
                isChecked={picked.includes(full)}
                isDisabled={!picked.includes(full) && picked.length >= MAX_DISCOVER_SCHEMAS}
                onChange={(on) => toggle(full, on)}
              >
                {s}
              </Checkbox>
            );
          })}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {picked.map((s) => (
          <Tag key={s} componentId="gsb.discover.picked" closable onClose={() => toggle(s, false)}>
            {s}
          </Tag>
        ))}
        <Button componentId="gsb.discover.scan" type="primary" loading={busy} disabled={!picked.length} onClick={scan}>
          Find KPIs
        </Button>
      </div>
      {error && <Alert componentId="gsb.discover.error" type="error" closable={false} message={error} />}
      {result && (
        <>
          <Typography.Text>
            {result.views.length} view{result.views.length === 1 ? '' : 's'} with KPIs, {result.groups.length} KPI
            {result.groups.length === 1 ? '' : 's'} in two or more views,{' '}
            {result.groups.filter((g) => g.conflict).length} with different formulas.
          </Typography.Text>
          {result.problems.map((p) => (
            <Alert key={p} componentId="gsb.discover.problem" type="warning" closable={false} message={p} />
          ))}
          {result.groups.length > 0 && (
            <Table aria-label="Duplicate KPIs" scrollable>
              <TableRow isHeader>
                <TableHeader componentId="gsb.discover.h_kpi">KPI</TableHeader>
                <TableHeader componentId="gsb.discover.h_state">State</TableHeader>
                <TableHeader componentId="gsb.discover.h_canonical">Proposed definition</TableHeader>
                <TableHeader componentId="gsb.discover.h_views">In views</TableHeader>
                <TableHeader componentId="gsb.discover.h_actions">Actions</TableHeader>
              </TableRow>
              {result.groups.map((g) => (
                <TableRow key={`${g.canonical.view}:${g.canonical.name}`}>
                  <TableCell>
                    <Typography.Text bold>{g.canonical.name}</Typography.Text>
                  </TableCell>
                  <TableCell>
                    {g.conflict ? (
                      <Tag componentId="gsb.discover.state" color="coral">
                        Different formulas
                      </Tag>
                    ) : (
                      <Tag componentId="gsb.discover.state" color="teal">
                        Same formula
                      </Tag>
                    )}
                  </TableCell>
                  <TableCell>
                    <code style={{ ...MONO, overflowWrap: 'anywhere' }}>{g.canonical.expr}</code>
                    <div>
                      <Typography.Text color="secondary">from {g.canonical.view}</Typography.Text>
                    </div>
                  </TableCell>
                  <TableCell>
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {g.kpis.map((k) => (
                        <li key={`${k.view}:${k.name}`}>
                          <code style={MONO}>{k.view}</code> {k.kind === 'metric_view' ? '(metric view)' : '(SQL view)'}
                          : {k.name} = <code style={{ ...MONO, overflowWrap: 'anywhere' }}>{k.expr}</code>
                        </li>
                      ))}
                    </ul>
                  </TableCell>
                  <TableCell>
                    {g.canonical.kind === 'metric_view' ? (
                      <Button componentId="gsb.discover.import" onClick={() => setImporting(g)}>
                        Import {g.canonical.view.split('.').pop()}
                      </Button>
                    ) : (
                      <Typography.Text color="secondary">
                        In a SQL view. Add it as a measure in a sub-project.
                      </Typography.Text>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </Table>
          )}
        </>
      )}
      {importing && (
        <ImportModal
          initialView={importing.canonical.view}
          replaces={importing.replaces}
          onClose={() => setImporting(undefined)}
        />
      )}
    </section>
  );
}
