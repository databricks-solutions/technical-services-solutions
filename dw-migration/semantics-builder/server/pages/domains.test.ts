import { describe, expect, it } from 'vitest';
import { parseDomains } from './domains';

describe('parseDomains', () => {
  it('names each domain by its tag key, marks subdomains, drops drafts, and sorts by name', () => {
    expect(
      parseDomains([
        { domain_id: 'b', tag_key: 'Sales/Orders', parent_domain_id: 'a' },
        { domain_id: 'a', tag_key: 'Sales' },
        { domain_id: 'c', tag_key: 'Finance', effective_draft: true },
      ])
    ).toEqual([
      { id: 'a', name: 'Sales', subdomain: false },
      { id: 'b', name: 'Sales/Orders', subdomain: true },
    ]);
  });

  it('drops entries without an id or a tag key', () => {
    expect(parseDomains([{ domain_id: 'a' }, { tag_key: 'x' }])).toEqual([]);
  });
});
