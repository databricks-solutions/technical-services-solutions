import type { SemanticBrief } from '../../shared/brief';
import type { TestCase } from '../../shared/designer';
import type { AgentCheck, AgentScore } from '../../shared/genie';
import type { MetricView } from '../../shared/metricView';

export const MIN_BENCHMARKS = 10;
const MIN_EXAMPLES = 3;
const MIN_SAMPLES = 3;

export interface AgentInput {
  view: MetricView | null;
  brief: SemanticBrief | null;
  tests: TestCase[];
  /** Text dimensions that get entity matching in the space settings. null when the types could not be read. */
  matched: string[] | null;
  /** The space exists, and whether it has the settings of the current design. */
  space: { current: boolean } | null;
}

const share = (n: number, d: number) => (d ? n / d : 0);
const level = (n: number, pass: number) => (n >= pass ? 'pass' : n > 0 ? 'warn' : 'fail');
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/**
 * A rule-based score of the Genie agent, from the design and the space settings. Each failed check names where to
 * fix it. Pass counts 1, a warning counts half.
 */
export function scoreAgent(a: AgentInput): AgentScore {
  const fields = a.view ? [...a.view.dimensions, ...a.view.measures] : [];
  const described = fields.filter((f) => f.comment?.trim()).length;
  const withSynonyms = fields.filter((f) => f.synonyms?.length).length;
  const benchmarks = a.tests.filter((t) => t.expect).length;
  const examples = a.tests.length - benchmarks;
  const samples = new Set((a.brief?.keyQuestions ?? []).map((q) => q.trim()).filter(Boolean)).size;
  const rules = (a.brief?.glossary.length ?? 0) + (a.brief?.assumptions.length ?? 0);
  const designer = { label: 'Open the Metric Designer', path: 'designer?tab=model' };
  const tests = { label: 'Open the tests', path: 'designer?tab=tests' };
  const intent = { label: 'Open Intent & Context', path: 'intake' };

  const checks: AgentCheck[] = [
    {
      id: 'view_comment',
      label: 'The view has a description',
      status: a.view?.comment?.trim() ? 'pass' : 'fail',
      detail: a.view?.comment?.trim()
        ? a.view.comment.trim().slice(0, 200)
        : 'Genie reads the view description to know what the view is for.',
      fix: a.view?.comment?.trim() ? null : designer,
    },
    {
      id: 'field_comments',
      label: 'Fields have descriptions',
      status:
        share(described, fields.length) >= 0.8 ? 'pass' : share(described, fields.length) >= 0.3 ? 'warn' : 'fail',
      detail: `${described} of ${plural(fields.length, 'field')} have a description.`,
      fix: described < fields.length ? designer : null,
    },
    {
      id: 'synonyms',
      label: 'Fields have synonyms',
      status: share(withSynonyms, fields.length) >= 0.5 ? 'pass' : withSynonyms ? 'warn' : 'fail',
      detail: `${withSynonyms} of ${plural(fields.length, 'field')} have synonyms: the words that users type for them.`,
      fix: withSynonyms < fields.length ? designer : null,
    },
    {
      id: 'instructions',
      label: 'The space has instructions',
      status: !a.brief ? 'fail' : rules ? 'pass' : 'warn',
      detail: !a.brief
        ? 'Confirm a brief. Its goal, audience, glossary and rules become the instructions.'
        : rules
          ? `The goal, the audience, and ${rules === 1 ? '1 glossary term or rule' : `${rules} glossary terms and rules`}.`
          : 'The goal and the audience only. Add glossary terms or rules to the brief.',
      fix: rules ? null : intent,
    },
    {
      id: 'samples',
      label: `At least ${MIN_SAMPLES} sample questions`,
      status: level(samples, MIN_SAMPLES),
      detail: `${plural(samples, 'key question')} in the brief. Users see them when they open the space.`,
      fix: samples < MIN_SAMPLES ? intent : null,
    },
    {
      id: 'examples',
      label: `At least ${MIN_EXAMPLES} example SQL queries`,
      status: level(examples, MIN_EXAMPLES),
      detail: `${plural(examples, 'test')} with no expected value. Each one teaches Genie a query.`,
      fix: examples < MIN_EXAMPLES ? tests : null,
    },
    {
      id: 'benchmarks',
      label: `At least ${MIN_BENCHMARKS} benchmarks`,
      status: level(benchmarks, MIN_BENCHMARKS),
      detail: `${plural(benchmarks, 'test')} with an expected value. Benchmarks measure the accuracy of Genie. Use as a test in the Genie panel makes one from an answer.`,
      fix: benchmarks < MIN_BENCHMARKS ? tests : null,
    },
    {
      id: 'entity_matching',
      label: 'Text dimensions use entity matching',
      status: a.matched === null ? 'warn' : 'pass',
      detail:
        a.matched === null
          ? 'The column types of the sandbox view could not be read. Create the space, then look again.'
          : a.matched.length
            ? `The app turns it on for ${a.matched.join(', ')}.`
            : 'The view has no text dimensions.',
      fix: null,
    },
    {
      id: 'space_current',
      label: 'The space has the settings of this design',
      status: a.space?.current ? 'pass' : 'fail',
      detail: !a.space
        ? 'There is no Genie space yet. Click Create the Genie space.'
        : a.space.current
          ? 'The settings match the latest validated version.'
          : 'The design changed since the last update of the space. Click Update the view and the space.',
      fix: null,
    },
  ];
  const points = checks.reduce((n, c) => n + (c.status === 'pass' ? 1 : c.status === 'warn' ? 0.5 : 0), 0);
  const score = Math.round((100 * points) / checks.length);
  return { score, ready: score >= 80 && benchmarks > 0, checks };
}
