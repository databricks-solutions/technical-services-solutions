import type { SemanticBrief } from '../../shared/brief';
import type { DictionaryEntry } from '../../shared/dictionary';
import type { MetricView } from '../../shared/metricView';
import { assetOf, clip } from '../../shared/pages';
import type { PageDraft } from '../../shared/pages';

export interface PageInput {
  project: string;
  subProject: string;
  brief: { brief: SemanticBrief; version: number } | null;
  dictionary: DictionaryEntry[];
  dictionaryFile: string | null;
  /** The validated design, if any. */
  view: MetricView | null;
  /** The view in Unity Catalog, or null when it is not published yet. */
  target: string | null;
  sourceTables: string[];
  includeEntity: boolean;
}

const flat = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
const uniq = (xs: string[]) => [...new Set(xs.filter(Boolean))];

/**
 * Draft Pages from what the app knows: certified dictionary metrics, dimensions and terms, the brief glossary, and
 * one entity Page for the metric view. A dictionary entry wins over a glossary term with the same name.
 */
export function buildPages(input: PageInput): PageDraft[] {
  const projectSource = `STS Semantics Builder: ${input.project} / ${input.subProject}`;
  const viewRef = input.target ?? null;
  const fieldOf = (name: string) => {
    if (!input.view) return null;
    const n = flat(name);
    const m = input.view.measures.find((x) => flat(x.name) === n || flat(x.display_name ?? '') === n);
    if (m) return { kind: 'measure', name: m.name, expr: m.expr };
    const d = input.view.dimensions.find((x) => flat(x.name) === n || flat(x.display_name ?? '') === n);
    return d ? { kind: 'dimension', name: d.name, expr: d.expr } : null;
  };

  const pages: PageDraft[] = [];
  const seen = new Set<string>();
  for (const e of input.dictionary.filter((x) => x.status === 'certified')) {
    if (seen.has(flat(e.name))) continue;
    seen.add(flat(e.name));
    const field = fieldOf(e.name);
    const body = [
      '## Definition',
      e.definition,
      e.formula && `## Formula\n\n\`${e.formula}\``,
      e.aggregation && `Aggregation: ${e.aggregation}.`,
      e.grain && `Grain: ${e.grain}.`,
      e.format && `Format: ${e.format}.`,
      field && viewRef && `In the metric view \`${viewRef}\` this is the ${field.kind} \`${field.name}\`.`,
      ...Object.entries(e.notes).map(([k, v]) => `${k}: ${v}`),
    ]
      .filter(Boolean)
      .join('\n\n');
    pages.push({
      key: `${e.kind}:${flat(e.name)}`,
      kind: e.kind,
      title: e.display_name || e.name,
      synonyms: uniq([...e.synonyms, e.display_name && e.display_name !== e.name ? e.name : '']),
      description: clip(e.definition),
      body,
      relatedAssets: uniq([field && viewRef ? viewRef : '', e.source ? assetOf(e.source) : '']),
      sources: uniq([
        `Certified metric dictionary${input.dictionaryFile ? ` (${input.dictionaryFile})` : ''}`,
        projectSource,
      ]),
      include: true,
      edited: false,
    });
  }

  for (const g of input.brief?.brief.glossary ?? []) {
    if (seen.has(flat(g.term)) || !g.definition.trim()) continue;
    seen.add(flat(g.term));
    pages.push({
      key: `term:${flat(g.term)}`,
      kind: 'term',
      title: g.term,
      synonyms: [],
      description: clip(g.definition),
      body: `## Definition\n\n${g.definition}`,
      relatedAssets: viewRef ? [viewRef] : [],
      sources: [`Semantic Brief version ${input.brief!.version}`, projectSource],
      include: true,
      edited: false,
    });
  }

  if (input.includeEntity && input.view) {
    const v = input.view;
    const b = input.brief?.brief;
    const name = (f: { name: string; display_name?: string }) => f.display_name || f.name;
    const body = [
      '## What it is',
      v.comment || b?.businessGoal || `The governed metrics of ${input.subProject}.`,
      `## Measures\n\n${v.measures.map((m) => `- **${name(m)}**${m.comment ? `: ${m.comment}` : ''}`).join('\n')}`,
      `## Dimensions\n\n${v.dimensions.map((d) => `- **${name(d)}**${d.comment ? `: ${d.comment}` : ''}`).join('\n')}`,
      b?.keyQuestions.length && `## Questions it answers\n\n${b.keyQuestions.map((q) => `- ${q}`).join('\n')}`,
      `## Where the data comes from\n\nSource \`${v.source}\`${v.joins?.length ? `, joined to ${v.joins.map((j) => `\`${j.source}\``).join(', ')}` : ''}.`,
      viewRef ? `Query it in Unity Catalog as \`${viewRef}\`.` : 'Not published to Unity Catalog yet.',
    ]
      .filter(Boolean)
      .join('\n\n');
    pages.push({
      key: 'entity:view',
      kind: 'entity',
      title: b?.title || input.subProject,
      synonyms: [],
      description: clip(v.comment || b?.businessGoal || ''),
      body,
      relatedAssets: uniq([viewRef ?? '', ...input.sourceTables]),
      sources: uniq([input.brief ? `Semantic Brief version ${input.brief.version}` : '', projectSource]),
      include: true,
      edited: false,
    });
  }
  return pages;
}
