import { UC_NAME_PART } from '../../shared/brief';
import { renderMetricView, validateMetricView } from '../../shared/metricView';

const canonical = (yaml: string) => {
  const view = validateMetricView(yaml).view;
  return view ? renderMetricView(view) : yaml.replace(/\s+/g, ' ').trim();
};

/** True when two metric view YAMLs define the same view, whatever their layout. */
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
