import { useEffect } from 'react';
import type { MouseEvent, ReactNode } from 'react';
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  RouterProvider,
  useLocation,
  useMatch,
  useNavigate,
} from 'react-router';
import type { ProjectSummary } from '../../shared/brief';
import { api, DRIFT_CHECKED, PROJECTS_CHANGED, useResource } from './api';
import {
  CatalogIcon,
  FolderIcon,
  HomeIcon,
  NavList,
  NavListSidebar,
  SimpleSelect,
  SimpleSelectOption,
  Typography,
} from '@databricks/design-system';
import { ErrorBoundary } from './ErrorBoundary';
import { ThemeProvider, useThemePreference } from './theme';
import type { ThemePreference } from './theme';
import { DesignerPage } from './pages/DesignerPage';
import { OptimizePage } from './pages/OptimizePage';
import { IntakePage } from './pages/IntakePage';
import { PlaygroundPage } from './pages/PlaygroundPage';
import { ProjectPage } from './pages/ProjectPage';
import { ProjectsPage, subPath } from './pages/ProjectsPage';
import { SourcesPage } from './pages/SourcesPage';
import { OverviewPage } from './pages/OverviewPage';
import { PublishPage } from './pages/PublishPage';
import { SubProjectLayout } from './pages/SubProjectLayout';
import { LibraryPage } from './pages/LibraryPage';

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
  const inProject = useMatch('/projects/:parentId/*')?.params.parentId;
  const sub = useMatch('/projects/:parentId/sub/:projectId/*')?.params;
  const projects = useResource<ProjectSummary[]>('/api/projects');
  const { refresh } = projects;
  // Pages create and delete projects, so the tree refreshes on each navigation.
  useEffect(() => refresh(), [pathname, refresh]);
  // Check on open: once per browser session, the server checks the user's promoted views older than one day.
  useEffect(() => {
    if (sessionStorage.getItem(DRIFT_CHECKED)) return;
    sessionStorage.setItem(DRIFT_CHECKED, '1');
    api<{ checked: number }>('/api/drift/stale', {}).then(
      (r) => r.checked && window.dispatchEvent(new Event(DRIFT_CHECKED)),
      () => sessionStorage.removeItem(DRIFT_CHECKED)
    );
  }, []);
  useEffect(() => {
    window.addEventListener(PROJECTS_CHANGED, refresh);
    return () => window.removeEventListener(PROJECTS_CHANGED, refresh);
  }, [refresh]);
  const go = (path: string) => (e: MouseEvent) => {
    e.preventDefault();
    void navigate(path);
  };

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <NavListSidebar componentId="gsb.shell.sidebar">
        {({ showExpandedContent }) => {
          const side = showExpandedContent ? 'side' : 'only';
          return (
            <NavList.Root aria-label="STS Semantics Builder">
              <NavList.Group>
                <NavList.GroupContent>
                  <NavList.List>
                    <NavList.Item>
                      <NavList.Link
                        href="/"
                        active={pathname === '/'}
                        icon={<HomeIcon />}
                        iconPosition={side}
                        label="All projects"
                        onClick={go('/')}
                      />
                    </NavList.Item>
                    <NavList.Item>
                      <NavList.Link
                        href="/metric-views"
                        active={pathname === '/metric-views'}
                        icon={<CatalogIcon />}
                        iconPosition={side}
                        label="Metric views"
                        onClick={go('/metric-views')}
                      />
                    </NavList.Item>
                  </NavList.List>
                </NavList.GroupContent>
              </NavList.Group>
              {showExpandedContent && !!projects.data?.length && (
                <NavList.Group>
                  <NavList.GroupLabel>Projects</NavList.GroupLabel>
                  <NavList.GroupContent>
                    <NavList.List>
                      {projects.data.map((p) => (
                        <NavList.Item key={p.id}>
                          <NavList.Link
                            href={`/projects/${p.id}`}
                            active={pathname === `/projects/${p.id}`}
                            icon={<FolderIcon />}
                            label={p.name}
                            onClick={go(`/projects/${p.id}`)}
                          />
                          {p.id === inProject && p.subProjects.length > 0 && (
                            <NavList.SubList aria-label={`${p.name} sub-projects`}>
                              {p.subProjects.map((s) => {
                                const path = subPath(p.id, s.id, 'overview');
                                return (
                                  <NavList.SubItem key={s.id}>
                                    <NavList.SubLink
                                      href={path}
                                      active={s.id === sub?.projectId}
                                      label={s.name}
                                      onClick={go(path)}
                                    />
                                  </NavList.SubItem>
                                );
                              })}
                            </NavList.SubList>
                          )}
                        </NavList.Item>
                      ))}
                    </NavList.List>
                  </NavList.GroupContent>
                </NavList.Group>
              )}
            </NavList.Root>
          );
        }}
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
            STS Semantics Builder
          </Typography.Title>
          <ThemeSelect />
        </header>
        <main style={{ flex: 1, overflow: 'auto', padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ErrorBoundary>
            <Outlet context={projects} />
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
        path: '/metric-views',
        element: (
          <Page title="Metric views">
            <LibraryPage />
          </Page>
        ),
      },
      {
        path: '/projects/:parentId',
        element: <ProjectPage />,
      },
      {
        path: '/projects/:parentId/sub/:projectId',
        element: <SubProjectLayout />,
        children: [
          { index: true, element: <Navigate to="overview" replace /> },
          { path: 'overview', element: <OverviewPage /> },
          { path: 'sources', element: <SourcesPage /> },
          { path: 'intake', element: <IntakePage /> },
          { path: 'patterns', element: <PlaygroundPage /> },
          { path: 'designer', element: <DesignerPage /> },
          { path: 'optimize', element: <OptimizePage /> },
          { path: 'publish', element: <PublishPage /> },
        ],
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
