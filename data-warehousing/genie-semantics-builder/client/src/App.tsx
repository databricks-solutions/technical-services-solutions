import type { ReactNode } from 'react';
import { createBrowserRouter, Outlet, RouterProvider, useLocation, useMatch, useNavigate } from 'react-router';
import {
  BeakerIcon,
  CatalogIcon,
  ChartLineIcon,
  FolderIcon,
  NavList,
  NavListSidebar,
  SimpleSelect,
  SimpleSelectOption,
  SparkleIcon,
  Typography,
} from '@databricks/design-system';
import { ErrorBoundary } from './ErrorBoundary';
import { ThemeProvider, useThemePreference } from './theme';
import type { ThemePreference } from './theme';
import { DesignerPage } from './pages/DesignerPage';
import { IntakePage } from './pages/IntakePage';
import { PlaygroundPage } from './pages/PlaygroundPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { SourcesPage } from './pages/SourcesPage';

interface Destination {
  path: string;
  label: string;
  icon: ReactNode;
}

// Project modules appear here as each phase ships.
const projectModules = [
  { slug: 'intake', label: 'Intent & Context', icon: <SparkleIcon /> },
  { slug: 'sources', label: 'Source Readiness', icon: <CatalogIcon /> },
  { slug: 'designer', label: 'Metric Designer', icon: <ChartLineIcon /> },
  { slug: 'playground', label: 'Playground', icon: <BeakerIcon /> },
];

function ThemeSelect() {
  const { preference, setPreference } = useThemePreference();
  return (
    <SimpleSelect
      componentId="gsb.shell.theme"
      id="gsb-theme"
      label="Theme"
      value={preference}
      onChange={(e) => setPreference(e.target.value as ThemePreference)}
    >
      <SimpleSelectOption value="system">System</SimpleSelectOption>
      <SimpleSelectOption value="light">Light</SimpleSelectOption>
      <SimpleSelectOption value="dark">Dark</SimpleSelectOption>
    </SimpleSelect>
  );
}

function Shell() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const projectId = useMatch('/projects/:projectId/*')?.params.projectId;
  const destinations: Destination[] = [
    { path: '/', label: 'Projects', icon: <FolderIcon /> },
    ...(projectId
      ? projectModules.map((m) => ({ path: `/projects/${projectId}/${m.slug}`, label: m.label, icon: m.icon }))
      : []),
  ];

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <NavListSidebar componentId="gsb.shell.sidebar">
        {({ showExpandedContent }) => (
          <NavList.Root aria-label="Genie Semantics Builder">
            <NavList.Group>
              <NavList.GroupContent>
                <NavList.List>
                  {destinations.map((d) => (
                    <NavList.Item key={d.path}>
                      <NavList.Link
                        href={d.path}
                        active={pathname === d.path}
                        icon={d.icon}
                        iconPosition={showExpandedContent ? 'side' : 'only'}
                        label={d.label}
                        onClick={(e) => {
                          e.preventDefault();
                          void navigate(d.path);
                        }}
                      />
                    </NavList.Item>
                  ))}
                </NavList.List>
              </NavList.GroupContent>
            </NavList.Group>
          </NavList.Root>
        )}
      </NavListSidebar>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 16,
            padding: '12px 24px',
            borderBottom: '1px solid var(--db-border-base)',
          }}
        >
          <Typography.Title level={3} withoutMargins>
            Genie Semantics Builder
          </Typography.Title>
          <ThemeSelect />
        </header>
        <main style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-labelledby="gsb-page-title" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Typography.Title level={2} id="gsb-page-title">
        {title}
      </Typography.Title>
      {children}
    </section>
  );
}

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      {
        path: '/',
        element: (
          <Page title="Projects">
            <ProjectsPage />
          </Page>
        ),
      },
      {
        path: '/projects/:projectId/intake',
        element: (
          <Page title="Intent & Context">
            <IntakePage />
          </Page>
        ),
      },
      {
        path: '/projects/:projectId/sources',
        element: (
          <Page title="Source Readiness">
            <SourcesPage />
          </Page>
        ),
      },
      {
        path: '/projects/:projectId/designer',
        element: (
          <Page title="Metric Designer">
            <DesignerPage />
          </Page>
        ),
      },
      {
        path: '/projects/:projectId/playground',
        element: (
          <Page title="Playground">
            <PlaygroundPage />
          </Page>
        ),
      },
      { path: '*', element: <Page title="Not found">{null}</Page> },
    ],
  },
]);

export default function App() {
  return (
    <ThemeProvider>
      <ErrorBoundary>
        <RouterProvider router={router} />
      </ErrorBoundary>
    </ThemeProvider>
  );
}
