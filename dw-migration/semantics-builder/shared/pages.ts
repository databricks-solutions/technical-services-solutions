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

/** Discover limits a Page description to this many characters. */
export const DESCRIPTION_MAX = 160;

/** Cuts text to `max` characters at a word boundary. */
export function clip(s: string, max = DESCRIPTION_MAX): string {
  const t = s.trim().replace(/\s+/g, ' ');
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 3);
  return `${cut.slice(0, cut.lastIndexOf(' ') > 0 ? cut.lastIndexOf(' ') : cut.length)}...`;
}

/** Related assets of a Page are tables and views, so a column reference becomes its table. */
export function assetOf(ref: string): string {
  const parts = ref.split('.');
  return parts.length > 3 ? parts.slice(0, 3).join('.') : ref;
}
export const domainSchema = z.object({ domain: text(200).min(1) });
export const pageEditSchema = z.object({
  key: text(300).min(1),
  title: text(200).min(1),
  synonyms: z.array(text(100).min(1)).max(20),
  description: text(DESCRIPTION_MAX),
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

/**
 * One Page as Markdown, with only the fields a Page has, labeled so that Genie Code bulk import maps them. Sources are
 * not links, and a Page source must be a link, so they go to the body.
 */
export function pageMarkdown(page: PageDraft, domain: string): string {
  const list = (items: string[]) => (items.length ? items.join(', ') : 'None');
  const assets = [...new Set(page.relatedAssets.map(assetOf))];
  return [
    `# ${page.title}`,
    '',
    `- **Domain:** ${domain}`,
    `- **Synonyms:** ${list(page.synonyms)}`,
    `- **Description:** ${clip(page.description) || 'None'}`,
    `- **Related assets:** ${list(assets.map((a) => `\`${a}\``))}`,
    '',
    page.body.trim(),
    ...(page.sources.length ? ['', '## Sources', '', ...page.sources.map((s) => `- ${s}`)] : []),
    '',
  ].join('\n');
}

/** The prompt for Genie Code bulk import: the domain, the file layout, and a preview before it creates the Pages. */
export function importPrompt(domain: string, count: number): string {
  return [
    `Bulk import pages. Use the domain ${domain}.`,
    `The source is the attached Markdown file: ${count} pages, one per top-level heading, each with Domain, Synonyms,`,
    'Description and Related assets lines, then the body. Keep the text as written.',
    'Show me the proposed pages before you create them as drafts.',
  ].join(' ');
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
