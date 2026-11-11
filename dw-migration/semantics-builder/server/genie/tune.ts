import type { TestCase } from '../../shared/designer';
import type { TuningChange } from '../../shared/genie';
import type { MetricView } from '../../shared/metricView';
import type { TuneOutput } from '../llm/prompts/tune';

export const fieldsOf = (view: MetricView) => [
  ...view.measures.map((f) => ({
    name: f.name,
    kind: 'measure' as const,
    description: f.comment ?? '',
    synonyms: f.synonyms ?? [],
  })),
  ...view.dimensions.map((f) => ({
    name: f.name,
    kind: 'dimension' as const,
    description: f.comment ?? '',
    synonyms: f.synonyms ?? [],
  })),
];

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/**
 * Checks the AI output against the view and the tests, and keeps only the fields of its kind. Throws a message for
 * the user when the change cannot be used.
 */
export function toChange(out: TuneOutput, view: MetricView, tests: TestCase[]): TuningChange {
  const find = (name: string, kind?: 'measure' | 'dimension') =>
    fieldsOf(view).find((f) => same(f.name, name) && (!kind || f.kind === kind))?.name;
  const fail = (why: string): never => {
    throw new Error(`The AI suggestion cannot be used: ${why}`);
  };
  switch (out.kind) {
    case 'instruction':
      return out.text ? { kind: 'instruction', text: out.text } : fail('the instruction is empty.');
    case 'description': {
      const field = find(out.field) ?? fail(`${out.field || 'no field'} is not a field of the view.`);
      return out.text ? { kind: 'description', field, text: out.text } : fail('the description is empty.');
    }
    case 'synonym': {
      const field = find(out.field) ?? fail(`${out.field || 'no field'} is not a field of the view.`);
      const synonyms = [...new Set(out.synonyms.map((s) => s.trim()).filter(Boolean))];
      return synonyms.length ? { kind: 'synonym', field, synonyms } : fail('there are no synonyms.');
    }
    case 'example': {
      if (!out.question) fail('the example has no question.');
      if (tests.some((t) => same(t.name, out.question))) fail('the example repeats a test question.');
      const measures = out.measures.map((m) => find(m, 'measure') ?? fail(`${m} is not a measure of the view.`));
      const dimensions = out.dimensions.map(
        (d) => find(d, 'dimension') ?? fail(`${d} is not a dimension of the view.`)
      );
      if (!measures.length) fail('the example has no measure.');
      return { kind: 'example', question: out.question, measures, dimensions };
    }
  }
}

/** The app keeps a change only when more benchmark answers are correct than before. */
export const keeps = (before: number, after: number) => after > before;
