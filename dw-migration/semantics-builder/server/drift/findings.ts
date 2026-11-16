import type { DriftFinding, DriftSnapshot } from '../../shared/drift';
import { validateMetricView } from '../../shared/metricView';
import { toSourceProfiles } from '../designer/build';
import { sameYaml } from '../designer/promote';
import type { TableProfile } from '../readiness/profile';

export interface DriftInput {
  target: string;
  /** YAML of the last succeeded promotion. */
  promotedYaml: string;
  /** YAML in Unity Catalog now. null when the view is gone. */
  ucYaml: string | null;
  sources: { fullName: string; profile?: TableProfile; error?: string }[];
  owner: string | null;
  grants: string[];
  /** Sources with a row filter or a column mask. */
  restricted: string[];
  materialized: boolean;
  /** Latest Refresh Status of the materialization, when there is one. */
  refreshStatus: string | null;
  totals: Record<string, number | null> | null;
  baseline: Record<string, number | null> | null;
  previous: DriftSnapshot | null;
}

const DATA_CHANGE = 0.2;
const RANK = { error: 0, warning: 1, info: 2 } as const;

/** Drift findings of one promoted view, worst first, and the snapshot the next check compares with. */
export function driftFindings(i: DriftInput): { findings: DriftFinding[]; snapshot: DriftSnapshot } {
  const out: DriftFinding[] = [];
  const add = (f: DriftFinding) => out.push(f);

  if (i.ucYaml === null)
    add({
      kind: 'definition',
      severity: 'error',
      title: 'The view is gone',
      detail: `${i.target} does not exist or you cannot read it.`,
      fix: 'promote',
    });
  else if (!sameYaml(i.ucYaml, i.promotedYaml))
    add({
      kind: 'definition',
      severity: 'warning',
      title: 'Changed outside the app',
      detail: `The YAML of ${i.target} differs from the last promoted version.`,
      fix: 'promote',
    });

  for (const s of i.sources.filter((x) => !x.profile))
    add({
      kind: 'schema',
      severity: 'error',
      title: 'Source not readable',
      detail: `${s.fullName}: ${s.error ?? 'unknown error'}`,
      fix: 'readiness',
    });
  const profiles = i.sources.flatMap((s) => (s.profile ? [s.profile] : []));
  const checked = validateMetricView(i.ucYaml ?? i.promotedYaml, toSourceProfiles(profiles));
  for (const issue of checked.issues.filter((x) => x.severity === 'error'))
    add({
      kind: 'schema',
      severity: 'error',
      title: 'The view no longer fits its sources',
      detail: issue.message,
      fix: 'designer',
    });

  const columns = Object.fromEntries(
    profiles.map((p) => [p.fullName.toLowerCase(), Object.fromEntries(p.columns.map((c) => [c.name, c.type]))])
  );
  for (const [table, now] of Object.entries(columns)) {
    const before = i.previous?.columns[table];
    if (!before) continue;
    const dropped = Object.keys(before).filter((c) => !(c in now));
    const retyped = Object.keys(before).filter((c) => c in now && now[c] !== before[c]);
    const added = Object.keys(now).filter((c) => !(c in before));
    if (dropped.length || retyped.length)
      add({
        kind: 'schema',
        severity: 'warning',
        title: 'Source columns changed',
        detail: `${table}: ${[...dropped.map((c) => `${c} dropped`), ...retyped.map((c) => `${c} is now ${now[c]}, was ${before[c]}`)].join('; ')}.`,
        fix: 'readiness',
      });
    if (added.length)
      add({
        kind: 'schema',
        severity: 'info',
        title: 'New source columns',
        detail: `${table}: ${added.join(', ')}.`,
        fix: 'designer',
      });
  }

  if (i.previous && i.previous.owner !== i.owner)
    add({
      kind: 'governance',
      severity: 'warning',
      title: 'Owner changed',
      detail: `The owner is ${i.owner ?? 'unknown'}, was ${i.previous.owner ?? 'unknown'}.`,
      fix: null,
    });
  if (i.previous) {
    const gone = i.previous.grants.filter((g) => !i.grants.includes(g));
    const fresh = i.grants.filter((g) => !i.previous!.grants.includes(g));
    if (gone.length || fresh.length)
      add({
        kind: 'governance',
        severity: 'info',
        title: 'Grants changed',
        detail: [...fresh.map((g) => `added ${g}`), ...gone.map((g) => `removed ${g}`)].join('; '),
        fix: null,
      });
  }
  for (const s of i.restricted)
    add({
      kind: 'governance',
      severity: i.materialized ? 'error' : 'info',
      title: i.materialized ? 'A row filter or mask blocks the materialization' : 'Source has a row filter or mask',
      detail: `${s} has a row filter or a column mask.${i.materialized ? ' Materialization does not support it.' : ' Materialization is not possible while it stays.'}`,
      fix: i.materialized ? 'materialize' : null,
    });

  if (i.refreshStatus && !/^succeeded$/i.test(i.refreshStatus))
    add({
      kind: 'usage',
      severity: /^(failed|canceled|cancelled)$/i.test(i.refreshStatus) ? 'error' : 'info',
      title: 'Materialization refresh',
      detail: `The latest refresh is ${i.refreshStatus.toLowerCase()}.`,
      fix: 'materialize',
    });

  if (i.baseline && i.totals)
    for (const [m, was] of Object.entries(i.baseline)) {
      const now = i.totals[m];
      if (now === undefined || now === null)
        add({
          kind: 'data',
          severity: 'warning',
          title: `${m} has no value`,
          detail: `The baseline was ${was ?? 'empty'}.`,
          fix: 'designer',
        });
      else if (was !== null && was !== 0 && Math.abs(now - was) / Math.abs(was) > DATA_CHANGE)
        add({
          kind: 'data',
          severity: 'warning',
          title: `${m} moved`,
          detail: `${m} changed by ${Math.round((100 * (now - was)) / Math.abs(was))}% since the baseline.`,
          fix: null,
        });
    }

  if (!out.length)
    add({
      kind: 'definition',
      severity: 'info',
      title: 'No drift found',
      detail: 'The view matches its promoted version and its sources.',
      fix: null,
    });
  out.sort((a, b) => RANK[a.severity] - RANK[b.severity]);
  return { findings: out, snapshot: { owner: i.owner, grants: [...i.grants].sort(), columns } };
}
