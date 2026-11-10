import { z } from 'zod';

/** A draft Page for UC Semantics Discover: one business concept, ready for Genie Code bulk import. */
export interface PageDraft {
  key: string;
  kind: 'term' | 'metric' | 'dimension' | 'entity';
  title: string;
  synonyms: string[];
  description: string;
  body: string;
  /** Unity Catalog objects the Page links to. */
  relatedAssets: string[];
  /** Where the content comes from. */
  sources: string[];
  include: boolean;
  /** True when the user changed the generated Page. */
  edited: boolean;
}

export interface PagesView {
  /** Domain of the top-level project; Pages need one. */
  domain: string | null;
  pages: PageDraft[];
}

/** A Discover domain or subdomain. A Page names it by its tag key, for example `Finance/Tax`. */
export interface DiscoverDomain {
  id: string;
  name: string;
  subdomain: boolean;
}

/** Published Discover domains. `error` is set when the list is not available; then the user types the name. */
export interface DomainList {
  domains: DiscoverDomain[];
  error: string | null;
}

const text = (max: number) => z.string().trim().max(max);
export const domainSchema = z.object({ domain: text(200).min(1) });
export const pageEditSchema = z.object({
  key: text(300).min(1),
  title: text(200).min(1),
  synonyms: z.array(text(100).min(1)).max(20),
  description: text(1000),
  body: text(20_000),
  include: z.boolean(),
});
export const pageKeySchema = z.object({ key: text(300).min(1) });

/**
 * Patterns of personal or regulated data. The docs say Pages must not hold PII, so the export warns on these.
 * A hit is a prompt to check, not proof.
 */
const PII: [RegExp, string][] = [
  [/[\w.+-]+@[\w-]+\.[\w.-]+/, 'an email address'],
  [/\b\d{3}-\d{2}-\d{4}\b/, 'a social security number'],
  [/\b(?:\d[ -]?){13,16}\b/, 'a card or account number'],
  [/(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b/, 'a phone number'],
];

export function piiWarnings(page: Pick<PageDraft, 'title' | 'synonyms' | 'description' | 'body'>): string[] {
  const all = [page.title, ...page.synonyms, page.description, page.body].join('\n');
  return PII.filter(([re]) => re.test(all)).map(([, what]) => `It may contain ${what}.`);
}

const KIND: Record<PageDraft['kind'], string> = {
  term: 'Business term',
  metric: 'Metric',
  dimension: 'Dimension',
  entity: 'Entity',
};

/** One Page as Markdown, with the fields of a Page labeled so that Genie Code bulk import can map them. */
export function pageMarkdown(page: PageDraft, domain: string): string {
  const list = (items: string[]) => (items.length ? items.join(', ') : 'None');
  return [
    `# ${page.title}`,
    '',
    `- **Domain:** ${domain}`,
    `- **Type:** ${KIND[page.kind]}`,
    `- **Synonyms:** ${list(page.synonyms)}`,
    `- **Description:** ${page.description || 'None'}`,
    `- **Related assets:** ${list(page.relatedAssets.map((a) => `\`${a}\``))}`,
    `- **Sources:** ${list(page.sources)}`,
    '',
    page.body.trim(),
    '',
  ].join('\n');
}

/** All included Pages in one file for bulk import, one Page per top-level heading. */
export function pagesBundle(view: PagesView, title: string): string {
  const pages = view.pages.filter((p) => p.include);
  return [
    `<!-- Pages for UC Semantics Discover, from STS Semantics Builder: ${title}. One Page per top-level heading. -->`,
    '',
    ...pages.map((p) => pageMarkdown(p, view.domain ?? '')),
  ].join('\n');
}
