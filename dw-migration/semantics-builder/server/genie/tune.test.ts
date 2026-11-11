import { describe, expect, it } from 'vitest';
import type { MetricView } from '../../shared/metricView';
import type { TuneOutput } from '../llm/prompts/tune';
import { keeps, toChange } from './tune';

const view = {
  version: '1.1',
  source: 'c.s.orders',
  dimensions: [{ name: 'Customer Region', expr: 'region' }],
  measures: [{ name: 'Net Revenue', expr: 'SUM(price)' }],
} as MetricView;
const tests = [{ name: 'What is the net revenue in Asia?', measures: ['Net Revenue'], dimensions: [] }];
const out = (o: Partial<TuneOutput>): TuneOutput => ({
  kind: 'instruction',
  text: '',
  field: '',
  synonyms: [],
  question: '',
  measures: [],
  dimensions: [],
  rationale: 'why',
  ...o,
});

describe('toChange', () => {
  it('keeps only the fields of its kind, with the exact field names of the view', () => {
    expect(
      toChange(out({ kind: 'synonym', field: 'customer region', synonyms: ['area', 'area', ' '] }), view, tests)
    ).toEqual({
      kind: 'synonym',
      field: 'Customer Region',
      synonyms: ['area'],
    });
    expect(
      toChange(
        out({
          kind: 'example',
          question: 'Revenue by region?',
          measures: ['net revenue'],
          dimensions: ['Customer Region'],
        }),
        view,
        tests
      )
    ).toEqual({
      kind: 'example',
      question: 'Revenue by region?',
      measures: ['Net Revenue'],
      dimensions: ['Customer Region'],
    });
  });

  it('stops invented fields, a copied benchmark and empty changes', () => {
    expect(() => toChange(out({ kind: 'description', field: 'Profit', text: 'x' }), view, tests)).toThrow(
      /not a field/
    );
    expect(() =>
      toChange(
        out({ kind: 'example', question: 'what is the net revenue in asia?', measures: ['Net Revenue'] }),
        view,
        tests
      )
    ).toThrow(/repeats a test/);
    expect(() =>
      toChange(out({ kind: 'example', question: 'Q?', measures: ['Customer Region'] }), view, tests)
    ).toThrow(/not a measure/);
    expect(() => toChange(out({ kind: 'instruction', text: '' }), view, tests)).toThrow(/empty/);
  });
});

describe('keeps', () => {
  it('keeps a change only when more answers are correct', () => {
    expect(keeps(2, 3)).toBe(true);
    expect(keeps(2, 2)).toBe(false);
    expect(keeps(3, 2)).toBe(false);
  });
});
