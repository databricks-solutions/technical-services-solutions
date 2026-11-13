import type { Application, Request } from 'express';
import { discoverSchema } from '../../shared/discover';
import type { DiscoveredKpi, DiscoverResult } from '../../shared/discover';
import { consolidate, kpisOfMetricView, kpisOfSqlView } from '../discover/consolidate';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle } from './http';

const MAX_VIEWS = 500;

/** Reads the metric views and SQL views of the schemas the user picks, as the user, and groups their KPIs. Stores nothing. */
export function registerDiscoverRoutes(app: Application, ucFor: (req: Request) => UcDeps) {
  app.post(
    '/api/discover',
    handle(async (req): Promise<DiscoverResult> => {
      actorOf(req);
      const { schemas } = discoverSchema.parse(req.body);
      const uc = ucFor(req);
      const problems: string[] = [];
      const views: DiscoverResult['views'] = [];
      const kpis: DiscoveredKpi[] = [];
      const lists = await Promise.all(
        [...new Set(schemas)].map(async (s) => {
          const [catalog, schema] = s.split('.');
          try {
            return await uc.tables(catalog, schema, false);
          } catch (err) {
            problems.push(`${s}: ${(err as Error).message.slice(0, 200)}`);
            return [];
          }
        })
      );
      for (const t of lists.flat()) {
        if (views.length >= MAX_VIEWS) {
          problems.push(`Only the first ${MAX_VIEWS} views were read.`);
          break;
        }
        const kind = t.table_type === 'METRIC_VIEW' ? 'metric_view' : t.table_type === 'VIEW' ? 'sql_view' : null;
        if (!kind || !t.full_name || !t.view_definition) continue;
        const found =
          kind === 'metric_view'
            ? kpisOfMetricView(t.full_name, t.view_definition)
            : kpisOfSqlView(t.full_name, t.view_definition);
        if (!found.length) continue;
        views.push({ fullName: t.full_name, kind, kpis: found.length });
        kpis.push(...found);
      }
      return { views, groups: consolidate(kpis), problems };
    })
  );
}
