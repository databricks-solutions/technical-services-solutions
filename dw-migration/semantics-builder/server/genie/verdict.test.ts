import { describe, expect, it } from 'vitest';
import { fieldsUsed, verdictOf } from './verdict';

const view = { measures: ['Net Revenue', 'Order Count'], dimensions: ['Order Month', 'Customer Region'] };
const sql =
  "SELECT `Order Month`, MEASURE(`Net Revenue`) AS total FROM `c`.`s`.`v` WHERE `Customer Region` = 'ASIA' GROUP BY ALL";

describe('fieldsUsed', () => {
  it('finds measures inside MEASURE() and dimensions outside it, by name', () => {
    expect(fieldsUsed(sql, view)).toEqual({
      measures: ['Net Revenue'],
      dimensions: ['Order Month', 'Customer Region'],
    });
  });
});

describe('verdictOf', () => {
  it('matches when Genie uses every expected measure and dimension', () => {
    expect(verdictOf(sql, view, { measures: ['Net Revenue'], dimensions: ['Order Month'] })).toEqual({
      verdict: 'matches',
      detail: 'Uses Net Revenue by Order Month, Customer Region.',
    });
  });

  it('names what is missing', () => {
    expect(verdictOf(sql, view, { measures: ['Order Count'], dimensions: [] }).verdict).toBe('different');
    expect(verdictOf(sql, view, { measures: ['Order Count'], dimensions: [] }).detail).toBe(
      'Missing measure Order Count. Uses Net Revenue by Order Month, Customer Region.'
    );
  });

  it('has no answer without SQL, and needs review without an expected answer', () => {
    expect(verdictOf(null, view, { measures: ['Net Revenue'], dimensions: [] }).verdict).toBe('no_answer');
    expect(verdictOf(sql, view, null).verdict).toBe('needs_review');
  });
});
