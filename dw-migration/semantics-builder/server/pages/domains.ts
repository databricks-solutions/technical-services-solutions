import { getExecutionContext, isInUserContext } from '@databricks/appkit';
import type { DiscoverDomain } from '../../shared/pages';

/** The account can hold many domains; stop after this many pages of results. */
const MAX_PAGES = 20;
/** The list is the same for every user, so the app keeps it for a short time. */
const CACHE_MS = 5 * 60 * 1000;

interface RawDomain {
  domain_id?: string;
  tag_key?: string;
  parent_domain_id?: string;
  effective_draft?: boolean;
}
interface RawPage {
  domains?: RawDomain[];
  next_page_token?: string;
}

/** Only published domains: a draft domain is visible only to its curators. */
export function parseDomains(raw: RawDomain[]): DiscoverDomain[] {
  return raw
    .filter((d): d is RawDomain & { domain_id: string; tag_key: string } => !!d.domain_id && !!d.tag_key)
    .filter((d) => !d.effective_draft)
    .map((d) => ({ id: d.domain_id, name: d.tag_key, subdomain: !!d.parent_domain_id }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export interface DomainsDeps {
  list(): Promise<DiscoverDomain[]>;
}

/**
 * Lists Discover domains as the app service principal. Apps cannot get the `domains` user scope, so this cannot run
 * as the user. The service principal needs MANAGE DISCOVER; the app shows domain names only, never drafts.
 */
export function domainsDeps(): DomainsDeps {
  let cached: { at: number; domains: DiscoverDomain[] } | undefined;
  return {
    async list() {
      if (cached && Date.now() - cached.at < CACHE_MS) return cached.domains;
      if (isInUserContext()) throw new Error('The domain list runs as the app service principal, not as the user');
      const api = getExecutionContext().client.apiClient;
      const all: RawDomain[] = [];
      let token: string | undefined;
      for (let i = 0; i < MAX_PAGES; i++) {
        // The SDK has no domains client yet (the API is Beta); this is the REST call it would make.
        const page = (await api.request({
          path: '/api/2.0/domains',
          method: 'GET',
          headers: new Headers(),
          raw: false,
          query: token ? { page_token: token } : {},
        })) as RawPage;
        all.push(...(page.domains ?? []));
        token = page.next_page_token;
        if (!token) break;
      }
      cached = { at: Date.now(), domains: parseDomains(all) };
      return cached.domains;
    },
  };
}
