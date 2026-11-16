import { shellQuote } from './pages';

export interface DashboardView {
  /** The view and version in Unity Catalog now. null before the first Promote. */
  promoted: { view: string; version: number } | null;
  /** The dashboard JSON to examine, and what it shows. */
  plan: { json: string; kpis: string[]; trend: string | null; breakdown: string | null } | null;
  /** The default folder: the user's home folder. */
  folder: string;
  name: string;
  warehouseId: string | null;
}

/** Only a folder under /Users or /Shared, with no "..". */
export const validFolder = (f: string) =>
  /^\/(Workspace\/)?(Users|Shared)\/[^\0]{1,400}$/.test(f) && !f.split('/').includes('..');

/**
 * Apps cannot get the scope of the dashboards API, so the user runs this command as themselves. The dataset names
 * the metric view in full, so no default catalog or schema is needed.
 */
export const dashboardCommand = (name: string, warehouseId: string, folder: string, json: string) =>
  [
    'databricks lakeview create',
    `--display-name ${shellQuote(name)}`,
    `--warehouse-id ${shellQuote(warehouseId)}`,
    `--serialized-dashboard ${shellQuote(JSON.stringify(JSON.parse(json)))}`,
    `--json ${shellQuote(JSON.stringify({ parent_path: folder }))}`,
  ].join(' \\\n  ');
