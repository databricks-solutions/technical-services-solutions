import { describe, expect, it } from 'vitest';
import { checkTarget, sameYaml } from './promote';

const yaml =
  'version: 1.1\nsource: c.s.t\ndimensions:\n  - name: A\n    expr: a\nmeasures:\n  - name: Rows\n    expr: COUNT(1)\n';

describe('sameYaml', () => {
  it('ignores layout and quoting, and sees a real change', () => {
    const relaid =
      'version: "1.1"\n\nsource: c.s.t\ndimensions:\n- name: A\n  expr: a\nmeasures:\n- name: Rows\n  expr: COUNT(1)';
    expect(sameYaml(yaml, relaid)).toBe(true);
    expect(sameYaml(yaml, yaml.replace('COUNT(1)', 'COUNT(*)'))).toBe(false);
  });

  it('ignores the semantic metadata that Unity Catalog keeps apart from view_definition', () => {
    const rich = yaml
      .replace('source: c.s.t\n', 'comment: Orders\nsource: c.s.t\n')
      .replace(
        '    expr: a\n',
        '    expr: a\n    comment: The A\n    display_name: A name\n    synonyms:\n      - aa\n    format:\n      type: number\n'
      );
    expect(rich).not.toBe(yaml);
    expect(sameYaml(rich, yaml)).toBe(true);
  });
});

describe('checkTarget', () => {
  it('accepts catalog.schema.view outside the sandbox schema', () => {
    expect(checkTarget('main.sales.order_metrics', 'sandbox.semantics_builder')).toBeNull();
    expect(checkTarget('main.sales', 'sandbox.semantics_builder')).toMatch(/catalog.schema.view/);
    expect(checkTarget('sandbox.semantics_builder.x', 'sandbox.semantics_builder')).toMatch(/sandbox/);
    expect(checkTarget('main.sales.bad name', null)).toMatch(/catalog.schema.view/);
  });
});
