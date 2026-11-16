import { describe, expect, it } from 'vitest';
import { pagesScript, shellQuote } from '../../shared/pages';
import { requestIdOf } from './pages';

describe('the Pages script', () => {
  it('gives each Page a fixed UUID v4 request id', () => {
    const id = requestIdOf('3102461c-c4ce-4d4b-8d1d-ffa029e07658', 'metric:net_revenue');
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(requestIdOf('3102461c-c4ce-4d4b-8d1d-ffa029e07658', 'metric:net_revenue')).toBe(id);
  });

  it('quotes text so a quote in a Page cannot end the shell string', () => {
    expect(shellQuote("it's")).toBe(`'it'\\''s'`);
    const s = pagesScript("Sales's", [
      { title: "Customer's revenue", synonyms: ['a'], description: 'd', body: "x' ; rm -rf ~", requestId: 'r1' },
    ]);
    expect(s).toContain(`--arg k 'Sales'\\''s'`);
    expect(s).toContain(`rm -rf ~`);
    expect(s).not.toMatch(/[^\\]'; rm/);
  });
});
