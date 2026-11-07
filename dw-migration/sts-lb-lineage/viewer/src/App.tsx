import {
  BarChartIcon,
  Button,
  DashboardIcon,
  Empty,
  Header,
  NavList,
  NavListSidebar,
  Spinner,
  TableIcon,
  Tag,
  TargetIcon,
  Typography,
  WorkflowsIcon,
  HistoryIcon,
} from '@databricks/design-system';
import { type ReactNode, useEffect, useMemo, useState } from 'react';

import { type Model, SHARED, buildModel, loadDoc, shortName } from './data';
import { ObjectDrawer, ProcessDrawer } from './Drawers';
import { LineageModal } from './Graph';
import { Impact, QuickFind } from './Impact';
import { Objects } from './Objects';
import { Overview } from './Overview';
import { ProcessMap } from './ProcessMap';
import { Changes } from './Changes';
import { Statistics } from './Statistics';
import { plural } from './ui';
import { type Tab, routeHref, useRoute } from './url';

export function App({ dark, onToggleDark }: { dark: boolean; onToggleDark: () => void }) {
  const [model, setModel] = useState<Model | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    loadDoc()
      .then((d) => setModel(buildModel(d)))
      .catch((e) => setError(String(e)));
  }, []);
  if (error) return <Empty title="Could not load lineage" description={error} />;
  if (!model) return <Spinner label="Loading lineage" />;
  return <Shell model={model} dark={dark} onToggleDark={onToggleDark} />;
}

type GraphTarget = { kind: 'object'; id: string } | { kind: 'process'; name: string };

const PAGES: { group: string; items: { tab: Tab; label: string; icon: ReactNode; intro: string }[] }[] = [
  {
    group: 'Summary',
    items: [
      { tab: 'overview', label: 'Overview', icon: <DashboardIcon />, intro: 'What was scanned, how it connects, and how far to trust it. Click any process or table to see its lineage graph.' },
      { tab: 'statistics', label: 'Statistics', icon: <BarChartIcon />, intro: 'Descriptive statistics of the scanned code and its lineage. All numbers come from the analyzer output.' },
    ],
  },
  {
    group: 'Explore',
    items: [
      {
        tab: 'processes',
        label: 'Process map',
        icon: <WorkflowsIcon />,
        intro: 'One node per top-level process, linked by the tables they share. Click a process to see its own lineage graph.',
      },
      { tab: 'objects', label: 'Objects', icon: <TableIcon />, intro: 'Every table and job as a lineage graph or a list. Filter or group on the left; click any object to see its upstream and downstream.' },
    ],
  },
  {
    group: 'Analyze',
    items: [
      {
        tab: 'impact',
        label: 'Impact analysis',
        icon: <TargetIcon />,
        intro: 'Pick a table, job, or process to see what it affects, what it depends on, or how two objects connect.',
      },
    ],
  },
];

const CHANGES = {
  group: 'Compare',
  items: [{ tab: 'changes' as Tab, label: 'Changes', icon: <HistoryIcon />, intro: 'What changed since the previous scan given with --compare.' }],
};

function Shell({ model, dark, onToggleDark }: { model: Model; dark: boolean; onToggleDark: () => void }) {
  const [route, go] = useRoute();
  const [graph, setGraph] = useState<GraphTarget | null>(null);
  const s = model.ins.summary;
  const pages = model.doc.diff ? [...PAGES, CHANGES] : PAGES;
  const page = pages.flatMap((g) => g.items).find((p) => p.tab === route.tab) ?? PAGES[0].items[0];

  const openObject = (id: string) => go({ obj: id, proc: undefined });
  const openProcess = (name: string) => {
    if (model.procByName.has(name)) go({ proc: name, obj: undefined });
  };

  const processScope = useMemo(() => {
    if (graph?.kind !== 'process') return undefined;
    const p = model.procByName.get(graph.name);
    const hubs = model.ins.hubs.filter((h) => h.writers.includes(graph.name) || h.readers.includes(graph.name)).map((h) => h.id);
    return [...(p?.objects ?? []), ...hubs];
  }, [graph, model]);

  return (
    <div className="lbl-shell">
      <NavListSidebar componentId="sts-lb-lineage.nav" expandedWidth={232} className="lbl-nav">
        {({ showExpandedContent }) => (
          <NavList.Root aria-label="STS Lakebridge Lineage">
            {showExpandedContent && (
              <div className="lbl-nav-title">
                <Typography.Text bold>STS Lakebridge Lineage</Typography.Text>
                <Typography.Hint>{`${plural(s.processes, 'process', 'processes')} · ${plural(s.tables, 'table')}`}</Typography.Hint>
              </div>
            )}
            {pages.map((g) => (
              <NavList.Group key={g.group}>
                {showExpandedContent && <NavList.GroupLabel>{g.group}</NavList.GroupLabel>}
                <NavList.GroupContent>
                  <NavList.List>
                    {g.items.map((it) => (
                      <NavList.Item key={it.tab}>
                        <NavList.Link
                          active={route.tab === it.tab}
                          href={routeHref({ tab: it.tab })}
                          icon={it.icon}
                          iconPosition={showExpandedContent ? 'side' : 'only'}
                          label={it.label}
                          onClick={(e) => {
                            e.preventDefault();
                            go({ tab: it.tab, obj: undefined, proc: undefined, only: undefined });
                          }}
                        />
                      </NavList.Item>
                    ))}
                  </NavList.List>
                </NavList.GroupContent>
              </NavList.Group>
            ))}
          </NavList.Root>
        )}
      </NavListSidebar>

      <main className="lbl-main">
        <Header
          title={page.label}
          titleAddOns={
            route.tab === 'overview'
              ? [
                  <Tag key="p" componentId="sts-lb-lineage.header.processes">{plural(s.processes, 'process', 'processes')}</Tag>,
                  <Tag key="t" componentId="sts-lb-lineage.header.tables">{plural(s.tables, 'table')}</Tag>,
                ]
              : undefined
          }
          buttons={[
            <QuickFind key="find" model={model} onPick={(t) => (t.startsWith('proc:') ? openProcess(t.slice(5)) : openObject(t))} />,
            <Button key="theme" componentId="sts-lb-lineage.header.theme" onClick={onToggleDark}>
              {dark ? 'Light mode' : 'Dark mode'}
            </Button>,
          ]}
        />
        <Typography.Paragraph color="secondary">{page.intro}</Typography.Paragraph>

        {route.tab === 'overview' && <Overview model={model} go={go} onOpenProcess={openProcess} onOpenObject={openObject} />}
        {route.tab === 'statistics' && <Statistics model={model} go={go} />}
        {route.tab === 'processes' && (
          <ProcessMap key={route.only ?? 'all'} model={model} initialCycles={route.only === 'cycles'} onOpenProcess={openProcess} onOpenObject={openObject} />
        )}
        {route.tab === 'objects' && (
          <Objects model={model} q={route.q ?? ''} setQ={(q) => go({ q: q || undefined })} onOpen={openObject} onOpenProcess={openProcess} />
        )}
        {route.tab === 'changes' && model.doc.diff && <Changes model={model} onOpen={openObject} onOpenProcess={openProcess} />}
        {route.tab === 'impact' && <Impact model={model} route={route} go={go} onOpen={openObject} onOpenProcess={openProcess} />}
      </main>

      <ObjectDrawer
        model={model}
        id={route.obj}
        onClose={() => go({ obj: undefined })}
        onOpen={openObject}
        onOpenProcess={openProcess}
        onGraph={(id) => {
          setGraph({ kind: 'object', id });
          go({ obj: undefined });
        }}
        onImpact={(id) => go({ tab: 'impact', mode: 'down', target: id, obj: undefined })}
      />
      <ProcessDrawer
        model={model}
        name={route.proc}
        onClose={() => go({ proc: undefined })}
        onOpen={openObject}
        onOpenProcess={openProcess}
        onLineage={(name) => {
          setGraph({ kind: 'process', name });
          go({ proc: undefined });
        }}
        onImpact={(name) => go({ tab: 'impact', mode: 'down', target: `proc:${name}`, proc: undefined })}
      />

      {graph?.kind === 'object' && (
        <LineageModal
          title={`Lineage: ${model.byId.get(graph.id)?.name}`}
          model={model}
          focusId={graph.id}
          groupBy="process"
          onClose={() => setGraph(null)}
          onOpenDetails={(id) => {
            setGraph(null);
            openObject(id);
          }}
          onOpenProcess={(p) => {
            setGraph(null);
            openProcess(p);
          }}
        />
      )}
      {graph?.kind === 'process' && processScope && (
        <LineageModal
          key={graph.name}
          title={`Process lineage: ${shortName(graph.name)}`}
          model={model}
          scope={processScope}
          boundary
          groupBy="process"
          onClose={() => setGraph(null)}
          onOpenDetails={(id) => {
            setGraph(null);
            openObject(id);
          }}
          onOpenProcess={(p) => {
            if (p === 'Shared tables' || p === SHARED || !model.procByName.has(p)) return;
            setGraph({ kind: 'process', name: p });
          }}
        />
      )}
    </div>
  );
}
