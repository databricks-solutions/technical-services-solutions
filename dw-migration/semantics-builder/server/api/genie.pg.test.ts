import path from 'node:path';
import type { Request } from 'express';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import pg from 'pg';
import { loadMigrations, migrate } from '../db/migrate';
import { sandboxViewName } from '../designer/validate';
import type { GenieDeps } from '../genie/client';
import type { LlmDeps } from '../llm/llm';
import type { TuneOutput } from '../llm/prompts/tune';
import type { RunDeps } from '../sql/runner';
import type { UcDeps } from '../uc/metadata';
import { designerRepo } from './designer';
import { registerGenieRoutes } from './genie';
import { projectRepo } from './projects';

// Runs only against a throwaway Postgres: TEST_DATABASE_URL=postgres://... pnpm test
const url = process.env.TEST_DATABASE_URL;
const ACTOR = 'author@x.com';
const YAML = `version: 1.1
source: c.s.orders
fields:
  - name: Region
    expr: region
measures:
  - name: Revenue
    expr: SUM(price)
`;

describe.skipIf(!url)('Genie optimization routes on Postgres', () => {
  const pool = new pg.Pool({ connectionString: url });
  const routes = new Map<string, (req: Request, res: unknown) => void>();
  const app = {
    get: (p: string, h: (req: Request, res: unknown) => void) => routes.set(`GET ${p}`, h),
    post: (p: string, h: (req: Request, res: unknown) => void) => routes.set(`POST ${p}`, h),
  };
  // The fake Genie: the test sets the state of each eval run.
  const sent: string[] = [];
  const runs = new Map<string, { status: string; correct: number }>();
  const genie: Partial<GenieDeps> = {
    updateSpace: (_id: string, config: string) => {
      sent.push(config);
      return Promise.resolve();
    },
    startEval: () => {
      const id = `run${runs.size + 1}`;
      runs.set(id, { status: 'RUNNING', correct: 0 });
      return Promise.resolve(id);
    },
    evalRun: (_id: string, run: string) =>
      Promise.resolve({
        status: runs.get(run)!.status,
        numQuestions: 1,
        numCorrect: runs.get(run)!.correct,
        numNeedsReview: 0,
      }),
    evalResults: (_id: string, run: string) =>
      Promise.resolve([
        {
          resultId: `${run}-r1`,
          question: 'Revenue in Asia?',
          assessment: runs.get(run)!.correct ? 'GOOD' : 'BAD',
          expectedSql: 'SELECT 1',
          actualSql: 'SELECT 2',
        },
      ]),
  };
  const suggestion = (text: string): TuneOutput => ({
    kind: 'instruction',
    text,
    field: '',
    synonyms: [],
    question: '',
    measures: [],
    dimensions: [],
    rationale: 'Asia is a region.',
  });
  let next: TuneOutput = suggestion('x');
  const llm: LlmDeps = {
    invoke: () =>
      Promise.resolve({
        choices: [
          { message: { tool_calls: [{ function: { name: 'submit_space_change', arguments: JSON.stringify(next) } }] } },
        ],
      }),
    sleep: () => Promise.resolve(),
    log: () => undefined,
  };
  const run: RunDeps = { execute: () => Promise.resolve({ columns: [], rows: [] }), audit: () => Promise.resolve() };
  const uc: Partial<UcDeps> = { table: () => Promise.resolve({ columns: [{ name: 'Region', type_text: 'string' }] }) };
  let sub = '';

  const call = (method: 'GET' | 'POST', route: string, body?: unknown) =>
    new Promise<{ code: number; body: Record<string, unknown> }>((resolve) => {
      let code = 200;
      const res = {
        status: (c: number) => ((code = c), res),
        json: (b: Record<string, unknown>) => resolve({ code, body: b }),
      };
      const [pattern, params] = route.split('|');
      const req = {
        params: { id: sub, ...(params ? { tuningId: params } : {}) },
        body,
        query: {},
        header: (n: string) => (n === 'x-forwarded-email' ? ACTOR : undefined),
      } as never;
      routes.get(`${method} ${pattern}`)!(req, res);
    });

  beforeAll(async () => {
    process.env.GSB_SANDBOX_SCHEMA = 'sandbox.gsb';
    await pool.query('DROP SCHEMA IF EXISTS gsb CASCADE');
    await migrate(pool, await loadMigrations(path.resolve('server/db/migrations')));
    const projects = projectRepo(pool as never);
    const designer = designerRepo(pool as never);
    const parent = await projects.create(ACTOR, { name: 'Sales' });
    sub = (await projects.create(ACTOR, { name: 'Revenue' }, parent.id)).id;
    await designer.add(ACTOR, sub, {
      name: 'orders',
      yaml: YAML,
      explanations: { summary: '', measures: {}, dimensions: {} },
      tests: [
        {
          name: 'Revenue in Asia?',
          measures: ['Revenue'],
          dimensions: [],
          expect: { value: 1, tolerancePct: 0.5, filters: [{ dimension: 'Region', value: 'ASIA' }] },
        },
      ],
      issues: [],
      origin: 'generated',
    });
    const v = sandboxViewName('sandbox.gsb', 'orders', sub);
    const r = await designer.startRun(ACTOR, sub, 1, v, ['CREATE x']);
    await designer.finishRun(r, 'passed', [], null);
    await pool.query(
      `INSERT INTO gsb.genie_space (project_id, space_id, view_name, created_by) VALUES ($1, 'sp1', $2, $3)`,
      [sub, v, ACTOR]
    );
    registerGenieRoutes(
      app as never,
      pool as never,
      () => run,
      () => genie as GenieDeps,
      () => uc as UcDeps,
      () => llm
    );
  });
  afterAll(() => pool.end());

  const tuning = async () => (await call('GET', '/api/projects/:id/genie/tuning')).body;

  it('runs the benchmarks, then keeps a change only when more answers are correct', async () => {
    // Bring the space up to date with the design, then measure the accuracy before any change.
    const view = (await call('GET', '/api/projects/:id/genie')).body as { setup: string[]; config: string };
    expect(
      (await call('POST', '/api/projects/:id/genie/space', { statements: view.setup, config: view.config })).code
    ).toBe(200);
    expect((await call('POST', '/api/projects/:id/genie/eval', {})).code).toBe(200);
    expect((await call('POST', '/api/projects/:id/genie/eval', {})).body.error).toMatch(/still running/);
    runs.set('run1', { status: 'DONE', correct: 0 });
    expect(await tuning()).toMatchObject({
      runs: [{ status: 'done', numCorrect: 0, current: true }],
      spaceCurrent: true,
    });

    // A change that does not help is reverted, and the space gets its settings back.
    next = suggestion('Asia means the region ASIA.');
    const s1 = (await call('POST', '/api/projects/:id/genie/tuning/suggest', { question: 'Revenue in Asia?' }))
      .body as {
      tuning: { id: string };
      config: string;
    };
    expect(s1.config).toContain('Asia means the region ASIA.');
    expect(
      (await call('POST', '/api/projects/:id/genie/tuning/:tuningId/apply|' + s1.tuning.id, { config: 'other' })).body
        .error
    ).toMatch(/changed since you examined/);
    expect(
      (await call('POST', '/api/projects/:id/genie/tuning/:tuningId/apply|' + s1.tuning.id, { config: s1.config })).code
    ).toBe(200);
    expect(sent.at(-1)).toBe(s1.config);
    expect(
      (await call('POST', '/api/projects/:id/genie/space', { statements: view.setup, config: view.config })).body.error
    ).toMatch(/on trial/);
    runs.set('run2', { status: 'DONE', correct: 0 });
    let t = await tuning();
    expect(t).toMatchObject({
      tunings: [{ status: 'reverted', beforeCorrect: 0, afterCorrect: 0 }],
      spaceCurrent: true,
    });
    expect(sent.at(-1)).toBe(view.config);

    // A change that helps is kept, and it stays in the settings of the space.
    next = suggestion('Filter Region for a region name.');
    const s2 = (await call('POST', '/api/projects/:id/genie/tuning/suggest', { question: 'Revenue in Asia?' }))
      .body as {
      tuning: { id: string };
      config: string;
    };
    await call('POST', '/api/projects/:id/genie/tuning/:tuningId/apply|' + s2.tuning.id, { config: s2.config });
    runs.set('run3', { status: 'DONE', correct: 1 });
    t = await tuning();
    expect((t.tunings as unknown[])[0]).toMatchObject({ status: 'kept', beforeCorrect: 0, afterCorrect: 1 });
    expect(t.spaceCurrent).toBe(true);
    // No wrong answer is left, so there is nothing to suggest.
    expect((await call('POST', '/api/projects/:id/genie/tuning/suggest', { question: 'Revenue in Asia?' })).code).toBe(
      409
    );
  });
});
