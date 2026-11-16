import { UC_NAME_PART } from '../../shared/brief';
import { renderMetricView, validateMetricView } from '../../shared/metricView';

// Unity Catalog keeps these apart from view_definition, so they never count as a change.
const strip = <T extends { comment?: unknown; synonyms?: unknown; display_name?: unknown; format?: unknown }>(f: T) => {
  const { comment: _c, synonyms: _s, display_name: _d, format: _f, ...rest } = f;
  return rest;
};

const canonical = (yaml: string) => {
  const view = validateMetricView(yaml).view;
  if (!view) return yaml.replace(/\s+/g, ' ').trim();
  const { comment: _c, ...head } = view;
  return renderMetricView({ ...head, dimensions: view.dimensions.map(strip), measures: view.measures.map(strip) });
};

/** True when two metric view YAMLs define the same view, whatever their layout and semantic metadata. */
export const sameYaml = (a: string, b: string) => canonical(a) === canonical(b);

/** Why a promotion target is not allowed, or null. The sandbox schema is for checks, not for real views. */
export function checkTarget(fullName: string, sandbox: string | null): string | null {
  const parts = fullName.split('.');
  if (parts.length !== 3 || !parts.every((p) => UC_NAME_PART.test(p)))
    return 'Name the target as catalog.schema.view, with letters, digits and underscores.';
  if (sandbox && `${parts[0]}.${parts[1]}`.toLowerCase() === sandbox.toLowerCase())
    return 'The sandbox schema is for checks. Pick another schema for the real view.';
  return null;
}
