import { z } from 'zod';
import type { SemanticBrief } from '../../../shared/brief';
import type { Explanations, TestCase } from '../../../shared/designer';
import type { Pattern } from '../../../shared/patterns';
import { formatSchema } from '../../../shared/metricView';
import type { TableProfile } from '../../readiness/profile';
import { untrusted } from '../llm';
import type { ToolPrompt } from '../llm';

const text = (max: number) => z.string().trim().max(max);
const alias = z
  .string()
  .regex(/^[a-z][a-z0-9_]{0,62}$/)
  .describe('Lowercase join name.');

const fieldShape = {
  name: text(255).min(1).describe('Business name in Title Case, for example "Net Revenue".'),
  expr: text(2000).min(1),
  comment: text(500).describe('One sentence business description.'),
  displayName: text(255).nullable(),
  synonyms: z.array(text(100)).max(10).describe('Other words users say for this field.'),
  format: formatSchema.nullable().describe('Display format. null when unsure.'),
  explanation: text(500).describe('Plain-language explanation of how the value is computed, without SQL.'),
};

const designOutput = z.object({
  name: z
    .string()
    .regex(/^[a-z][a-z0-9_]{0,99}$/)
    .describe('snake_case metric view name, for example sales_metrics.'),
  comment: text(1000),
  source: text(800).describe('Full name of the fact table. Must be one of the project tables.'),
  filter: text(2000).nullable().describe('Optional global filter on the fact table. null for none.'),
  joins: z
    .array(
      z.object({
        name: alias,
        source: text(800).describe('Full name of a project table.'),
        parent: alias.nullable().describe('Join name this table joins from. null when it joins from the fact table.'),
        keys: z
          .array(z.object({ parentColumn: text(255), column: text(255) }))
          .min(1)
          .max(4)
          .describe('Equality keys: a column of the parent table and the matching key column of this table.'),
      })
    )
    .max(20)
    .describe('Many-to-one joins, parents listed before their children.'),
  dimensions: z.array(z.object(fieldShape)).min(1).max(60),
  measures: z
    .array(
      z.object({
        ...fieldShape,
        additivity: z
          .enum(['additive', 'semi_additive', 'non_additive', 'ratio'])
          .describe('additive sums across all dimensions; ratio divides other measures.'),
        window: z
          .array(
            z.object({
              order: text(255).min(1).describe('Name of a dimension of this view, usually a date.'),
              range: text(60)
                .min(1)
                .describe('current, cumulative, all, or trailing|leading <n> [unit] [inclusive|exclusive].'),
              semiadditive: z.enum(['first', 'last']).nullable(),
              offset: text(30).nullable().describe('Shift of the window, for example -1 month. null for none.'),
            })
          )
          .max(3)
          .nullable()
          .optional()
          .describe('Window measure spec. null for a regular measure.'),
      })
    )
    .min(1)
    .max(60),
  tests: z
    .array(
      z.object({
        name: text(200).min(1),
        dimensions: z.array(text(255)).max(3),
        measures: z.array(text(255)).min(1).max(4),
      })
    )
    .min(3)
    .max(5)
    .describe('Queries that prove the model: a few dimensions and measures each, by name.'),
  summary: text(1000).describe('Two or three sentences for the user about the model.'),
});
export type DesignOutput = z.infer<typeof designOutput>;

const SYSTEM = `You are a semantic modeling advisor for Databricks Unity Catalog metric views.
Design one metric view for a confirmed Semantic Brief from the profiled project tables.
Rules:
- Use only the tables and columns you receive. Use exact names. Never invent names.
- Pick one fact table as source. Join dimension tables many-to-one on their primary key. For a snowflake, set parent to the join it hangs from.
- Join names must not be a prefix of a fact table column name. Prefer dim_<table> at the top level.
- In expr, address the fact table as source.<column> and a joined table by its full join path: <join>.<nested join>.<column>.
- Dimension expr is not aggregated. Measure expr aggregates, for example SUM(source.amount) or COUNT(DISTINCT source.id). A ratio uses MEASURE(\`Other Measure\`) of measures defined in this view.
- Cover the measures, dimensions and time grains of the brief. Use DATE_TRUNC for time grains.
- Do not use window functions, subqueries or semicolons.
- metric_dictionary, when given, holds the team's definitions with the columns they match. For a measure or
  dimension the dictionary defines, use its name, its definition as the comment, its synonyms, display_name and
  format, and its formula translated to these columns. Certified entries are fixed: keep the exact name and the
  same formula.`;

export const designPrompt: ToolPrompt<DesignOutput> = {
  id: 'designer.generate',
  version: 2,
  system: SYSTEM,
  tool: {
    name: 'submit_metric_view_design',
    description: 'Submit the metric view design, explanations and test cases.',
    schema: designOutput,
  },
  maxTokens: 16000,
};

const applyOutput = designOutput.extend({
  roles: z
    .array(
      z.object({
        role: text(60).min(1),
        mappedTo: text(600)
          .nullable()
          .describe('The project column or expression that plays this role. null when no column fits.'),
        reason: text(500),
      })
    )
    .min(1)
    .describe('One entry per pattern role.'),
});
export type ApplyOutput = z.infer<typeof applyOutput>;

export const applyPatternPrompt: ToolPrompt<ApplyOutput> = {
  id: 'designer.apply_pattern',
  version: 2,
  system: `${SYSTEM.replace(
    '- Do not use window functions, subqueries or semicolons.',
    '- Use window measures (the window field) and OVER () only where the pattern does. Do not use subqueries or semicolons.'
  )}
You receive a metric view pattern written for sample data. Adapt the same technique to the project tables.
- Map every pattern role to a project column. When no project column fits a role, set mappedTo to null and explain why. Do not invent tables.
- The pattern can use SQL query sources for reference data. The project design must use project tables only.
- Include an adapted measure for every measure of the pattern, with the same window settings and meaning. Rename fields to the business terms of the brief.`,
  tool: {
    name: 'submit_adapted_metric_view',
    description: 'Submit the adapted metric view design, the role mapping, explanations and test cases.',
    schema: applyOutput,
  },
  maxTokens: 16000,
};

export const refineDesignPrompt: ToolPrompt<DesignOutput> = {
  ...designPrompt,
  id: 'designer.refine',
  system: `${SYSTEM}\nYou receive the current metric view YAML and a change request. Apply the change, keep everything else, and summarize what changed.`,
};

const tables = (profiles: TableProfile[]) =>
  JSON.stringify(
    profiles.map((p) => ({
      table: p.fullName,
      comment: p.comment || null,
      columns: p.columns.map((c) => ({ name: c.name, type: c.type, comment: c.comment || null })),
      primaryKey: p.primaryKey,
      foreignKeys: p.foreignKeys,
    })),
    null,
    2
  );

const briefScope = (b: SemanticBrief) =>
  JSON.stringify({
    title: b.title,
    businessGoal: b.businessGoal,
    measures: b.measures,
    dimensions: b.dimensions,
    timeGrains: b.timeGrains,
    glossary: b.glossary,
  });

const dictionaryPart = (dictionary: unknown[]) =>
  dictionary.length ? [untrusted('metric_dictionary', JSON.stringify(dictionary))] : [];

export function designRequest(brief: SemanticBrief, profiles: TableProfile[], dictionary: unknown[] = []): string {
  return [
    'Design the metric view for this brief.',
    untrusted('semantic_brief', briefScope(brief)),
    untrusted('project_tables', tables(profiles)),
    ...dictionaryPart(dictionary),
  ].join('\n\n');
}

export function refineDesignRequest(
  brief: SemanticBrief,
  profiles: TableProfile[],
  current: { yaml: string; explanations: Explanations; tests: TestCase[] },
  instruction: string,
  dictionary: unknown[] = []
): string {
  return [
    'Change the metric view as requested.',
    untrusted('change_request', instruction),
    untrusted('current_metric_view_yaml', current.yaml),
    untrusted('current_tests', JSON.stringify(current.tests)),
    untrusted('semantic_brief', briefScope(brief)),
    untrusted('project_tables', tables(profiles)),
    ...dictionaryPart(dictionary),
  ].join('\n\n');
}

export function applyPatternRequest(
  brief: SemanticBrief,
  profiles: TableProfile[],
  pattern: Pick<Pattern, 'title' | 'scenario' | 'roles' | 'yaml'>
): string {
  return [
    'Adapt this pattern to the project tables.',
    untrusted('pattern', JSON.stringify({ title: pattern.title, scenario: pattern.scenario, roles: pattern.roles })),
    untrusted('pattern_metric_view_yaml', pattern.yaml),
    untrusted('semantic_brief', briefScope(brief)),
    untrusted('project_tables', tables(profiles)),
  ].join('\n\n');
}
