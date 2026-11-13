import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import pg from 'pg';
import { loadMigrations, migrate } from '../db/migrate';
import { projectRepo } from './projects';
import { designerRepo } from './designer';
import type { NewDraft } from './designer';
import { readinessRepo } from './readiness';
import { patternRunRepo } from './patterns';
import type { BriefOutput } from '../llm/prompts/brief';

// Runs only against a throwaway Postgres: TEST_DATABASE_URL=postgres://... pnpm test
const url = process.env.TEST_DATABASE_URL;

const output: BriefOutput = {
  summary: 'Revenue brief.',
  brief: {
    title: 'Sales',
    businessGoal: 'Track revenue',
    audience: [],
    keyQuestions: ['Revenue by month?'],
    measures: [{ name: 'Total Revenue', description: 'Sum of order totals', aggregation: 'sum' }],
    dimensions: [],
    timeGrains: ['month'],
    candidateSources: ['samples.tpch.orders', 'samples.tpch.customer'],
    glossary: [],
    assumptions: [],
    openQuestions: [],
  },
};

describe.skipIf(!url)('projectRepo on Postgres', () => {
  const pool = new pg.Pool({ connectionString: url });
  const repo = projectRepo(pool as never);
  const readiness = readinessRepo(pool as never);
  const designer = designerRepo(pool as never);
  const patternRuns = patternRunRepo(pool as never);

  beforeAll(async () => {
    await pool.query('DROP SCHEMA IF EXISTS gsb CASCADE');
    await migrate(pool, await loadMigrations(path.resolve('server/db/migrations')));
  });
  afterAll(() => pool.end());

  it('moves each existing project into a sub-project of a new parent', async () => {
    const all = await loadMigrations(path.resolve('server/db/migrations'));
    await pool.query('DROP SCHEMA IF EXISTS gsb CASCADE');
    await migrate(
      pool,
      all.filter((m) => m.version < '006')
    );
    const { rows } = await pool.query<{ id: string }>(
      "INSERT INTO gsb.project (name, created_by) VALUES ('Old', 'a@x.com') RETURNING id"
    );
    await pool.query("INSERT INTO gsb.source (project_id, full_name, added_by) VALUES ($1, 'a.b.c', 'a@x.com')", [
      rows[0].id,
    ]);
    await migrate(pool, all);
    const [top] = await repo.list('a@x.com');
    expect(top).toMatchObject({ name: 'Old', parentId: null });
    expect(top?.subProjects).toMatchObject([{ id: rows[0].id, name: 'Old', stage: 'intent', sources: 1 }]);
    await pool.query('DROP SCHEMA gsb CASCADE');
    await migrate(pool, all);
  }, 60_000); // It applies every migration twice; a slow machine needs more than 5 seconds.

  it('nests sub-projects under their project and reports their stage', async () => {
    const parent = await repo.create('n@x.com', { name: 'Sales' });
    const sub = await repo.create('n@x.com', { name: 'Revenue', description: 'Net revenue' }, parent.id);
    await repo.create('n@x.com', { name: 'Returns' }, parent.id);
    expect(sub.parentId).toBe(parent.id);
    await repo.addDraft('n@x.com', sub.id, output, {});
    await repo.confirm('n@x.com', sub.id, 1);
    const list = await repo.list('n@x.com');
    expect(list.map((p) => p.name)).toEqual(['Sales']);
    expect(list[0]?.subProjects.map((s) => [s.name, s.stage, s.sources]).sort()).toEqual([
      ['Returns', 'sources', 0],
      ['Revenue', 'design', 2],
    ]);
    expect(await repo.list('other@x.com')).toEqual([]);
  });

  it('plans and deletes a project with its sub-projects and sandbox views', async () => {
    const parent = await repo.create('d@x.com', { name: 'Gone' });
    const sub = await repo.create('d@x.com', { name: 'Child' }, parent.id);
    const plan = { sandboxView: 'a.b.pattern_ranking__gsb_1', statements: ['CREATE ...'] };
    const run = await patternRuns.start('d@x.com', sub.id, 'ranking', plan, 'SELECT 1');
    await patternRuns.finish(run, 'passed', 1, '');

    expect(await repo.deletePlan('d@x.com', parent.id)).toEqual({
      name: 'Gone',
      subProjects: ['Child'],
      cleanup: ['DROP VIEW IF EXISTS `a`.`b`.`pattern_ranking__gsb_1`'],
    });
    await expect(repo.remove('other@x.com', parent.id)).rejects.toMatchObject({ status: 404 });
    await repo.remove('d@x.com', parent.id);
    expect(await repo.list('d@x.com')).toEqual([]);
    const left = await pool.query<{ n: number }>(
      'SELECT count(*)::int AS n FROM gsb.pattern_run WHERE project_id = $1',
      [sub.id]
    );
    expect(left.rows[0].n).toBe(0);
    const audit = await pool.query(
      "SELECT target FROM gsb.audit_log WHERE action = 'delete_project' AND project_id = $1",
      [parent.id]
    );
    expect(audit.rows).toEqual([{ target: 'Gone' }]);
  });

  it('shares confirmed terms with sibling sub-projects and saves the chat', async () => {
    const parent = await repo.create('m@x.com', { name: 'Memory' });
    const revenue = await repo.create('m@x.com', { name: 'Revenue' }, parent.id);
    const returns = await repo.create('m@x.com', { name: 'Returns' }, parent.id);
    const withTerms = {
      ...output,
      brief: {
        ...output.brief,
        glossary: [{ term: 'Net Revenue', definition: 'Price less discount.' }],
        assumptions: ['Fiscal year starts in July.'],
      },
    };
    await repo.addDraft('m@x.com', revenue.id, withTerms, {});
    await repo.confirm('m@x.com', revenue.id, 1);

    const ctx = await repo.intakeContext(returns.id);
    expect(ctx.memory.map((m) => [m.kind, m.text, m.fromName])).toEqual([
      ['term', 'Net Revenue', 'Revenue'],
      ['assumption', 'Fiscal year starts in July.', 'Revenue'],
    ]);
    expect(ctx.metadata.memory).toHaveLength(2);

    const lastTurn = {
      ideas: [{ title: 'Returns', question: 'q', measures: ['Rate'], dimensions: [] }],
      suggestions: ['a'],
    };
    await repo.saveSession('m@x.com', returns.id, [{ role: 'user', content: 'hi' }], lastTurn);
    expect((await repo.intakeContext(returns.id)).session).toEqual([{ role: 'user', content: 'hi' }]);
    expect((await repo.intakeContext(returns.id)).lastTurn).toEqual(lastTurn);
    await repo.clearSession(returns.id);
    expect((await repo.intakeContext(returns.id)).session).toEqual([]);

    const other = await repo.create('m@x.com', { name: 'Other' });
    await expect(repo.removeMemory('m@x.com', other.id, ctx.memory[0].id)).rejects.toMatchObject({ status: 404 });
    await repo.removeMemory('m@x.com', returns.id, ctx.memory[0].id);
    expect((await repo.intakeContext(revenue.id)).memory).toHaveLength(1);
  });

  it('keeps projects private to their creator', async () => {
    const p = await repo.create('a@x.com', { name: 'TPC-H' });
    expect((await repo.list('a@x.com')).map((x) => x.id)).toContain(p.id);
    expect(await repo.list('b@x.com')).toEqual([]);
    await expect(repo.get('b@x.com', p.id)).rejects.toMatchObject({ status: 404 });
  });

  it('versions drafts, confirms only the latest, and registers sources once', async () => {
    const p = await repo.create('a@x.com', { name: 'Brief' });
    expect((await repo.addDraft('a@x.com', p.id, output, {})).version).toBe(1);
    expect((await repo.addDraft('a@x.com', p.id, output, {})).version).toBe(2);
    await expect(repo.confirm('a@x.com', p.id, 1)).rejects.toMatchObject({ status: 409 });

    const confirmed = await repo.confirm('a@x.com', p.id, 2);
    expect(confirmed.status).toBe('confirmed');
    await expect(repo.confirm('a@x.com', p.id, 2)).rejects.toMatchObject({ status: 409 });

    const sources = await pool.query('SELECT full_name FROM gsb.source WHERE project_id = $1 ORDER BY 1', [p.id]);
    expect(sources.rows.map((r: { full_name: string }) => r.full_name)).toEqual([
      'samples.tpch.customer',
      'samples.tpch.orders',
    ]);
    const audit = await pool.query('SELECT action FROM gsb.audit_log WHERE project_id = $1 ORDER BY id', [p.id]);
    expect(audit.rows.map((r: { action: string }) => r.action)).toEqual(['create_project', 'confirm_brief']);
  });

  it('claims a fix only with the statements the user saw, once', async () => {
    const p = await repo.create('a@x.com', { name: 'Readiness' });
    await repo.addDraft('a@x.com', p.id, output, {});
    await repo.confirm('a@x.com', p.id, 1);
    const [source] = (await readiness.view(p.id)).sources;
    const fix = {
      kind: 'table_comment' as const,
      title: 'Describe',
      rationale: 'Why',
      statements: ["COMMENT ON TABLE a.b.c IS 'x'"],
      effect: { tableComment: true as const },
    };
    const profile = {
      fullName: source.fullName,
      comment: '',
      columns: [{ name: 'order_date', type: 'date', comment: '' }],
      primaryKey: [],
      foreignKeys: [],
    };
    const result = {
      sourceId: source.sourceId,
      role: 'fact' as const,
      checks: [],
      model: 'm',
      profile,
      score: 1,
      recommendations: [fix],
    };
    await readiness.saveAssessment('a@x.com', p.id, [
      { ...result, assessment: { role: 'fact', score: 40, summary: 's', findings: [] } },
    ]);

    let view = await readiness.view(p.id);
    const before = view.score!.score;
    expect(view.sources.find((s) => s.sourceId === source.sourceId)?.report?.areas).toHaveLength(4);
    const rec = view.recommendations[0];
    expect(rec.scoreGain).toBeGreaterThan(0);
    await expect(readiness.claim('a@x.com', p.id, rec.id, ['DROP TABLE a.b.c'])).rejects.toMatchObject({ status: 409 });
    await readiness.claim('a@x.com', p.id, rec.id, rec.statements);
    await expect(readiness.claim('a@x.com', p.id, rec.id, rec.statements)).rejects.toMatchObject({ status: 409 });
    await readiness.finish(rec.id, 'applied', null);
    // The applied fix counts before the next assessment.
    expect((await readiness.view(p.id)).score!.score).toBe(before + rec.scoreGain);

    await readiness.saveAssessment('a@x.com', p.id, [{ ...result, assessment: null }]);
    view = await readiness.view(p.id);
    expect(view.recommendations.map((r) => r.status).sort()).toEqual(['applied', 'proposed']);
  });

  it('versions metric view drafts and rejects a save on a stale base', async () => {
    const p = await repo.create('dana@example.com', { name: 'Design' });
    const draft: NewDraft = {
      name: 'sales_metrics',
      yaml: 'source: a.b.c',
      explanations: { summary: 's', measures: {}, dimensions: {} },
      tests: [],
      issues: [],
      origin: 'generated',
    };
    expect(await designer.view(p.id)).toEqual({ draft: null, validation: null, history: [] });
    await designer.add('dana@example.com', p.id, draft);
    await designer.add('dana@example.com', p.id, { ...draft, yaml: 'source: a.b.d', origin: 'edited' }, 1);
    await expect(designer.add('dana@example.com', p.id, { ...draft, origin: 'edited' }, 1)).rejects.toThrow(
      /newer version/
    );
    const view = await designer.view(p.id);
    expect(view.draft).toMatchObject({ version: 2, yaml: 'source: a.b.d', origin: 'edited', status: 'draft' });
    expect(view.history.map((h) => h.version)).toEqual([2, 1]);
    expect((await designer.view(p.id, 1)).draft?.yaml).toBe('source: a.b.c');
    await expect(designer.view(p.id, 9)).rejects.toThrow(/not found/);
    const audit = await pool.query(
      "SELECT detail FROM gsb.audit_log WHERE project_id = $1 AND action = 'save_metric_view_draft' ORDER BY id",
      [p.id]
    );
    expect(audit.rows.map((r: { detail: unknown }) => r.detail)).toEqual([
      { version: 1, origin: 'generated' },
      { version: 2, origin: 'edited' },
    ]);

    await expect(designer.startRun('dana@example.com', p.id, 1, 'a.b.v', ['CREATE x'])).rejects.toThrow(/latest/);
    const run = await designer.startRun('dana@example.com', p.id, 2, 'a.b.v', ['CREATE x']);
    expect((await designer.view(p.id)).validation).toMatchObject({
      id: run,
      status: 'running',
      version: 2,
      cleanup: [],
    });
    const result = { name: 't', status: 'passed' as const, rows: 3, detail: 'ok', measureSql: 'q', expandedSql: null };
    await designer.finishRun(run, 'passed', [result], null);
    const done = await designer.view(p.id);
    expect(done.validation).toMatchObject({
      status: 'passed',
      results: [result],
      cleanup: ['DROP VIEW IF EXISTS `a`.`b`.`v`'],
    });
    expect(done.draft?.status).toBe('validated');
    expect((await designer.view(p.id, 1)).validation).toBeNull();
  });

  it('keeps the latest pattern run per pattern, with metadata only', async () => {
    const p = await repo.create('a@x.com', { name: 'Patterns' });
    const plan = { sandboxView: 'a.b.pattern_ranking__gsb_12345678', statements: ['CREATE ...'] };
    const first = await patternRuns.start('a@x.com', p.id, 'ranking', plan, 'SELECT 1');
    await patternRuns.finish(first, 'failed', 0, 'boom');
    const second = await patternRuns.start('a@x.com', p.id, 'ranking', plan, 'SELECT 2');
    const other = await patternRuns.start('a@x.com', p.id, 'funnel', { ...plan, sandboxView: 'a.b.f' }, 'SELECT 3');
    expect((await patternRuns.latest(p.id)).map((r) => [r.slug, r.status, r.cleanup])).toEqual([
      ['funnel', 'running', []],
      ['ranking', 'running', []],
    ]);
    await patternRuns.finish(second, 'passed', 12, '12 rows match the expected output.');
    await patternRuns.finish(other, 'failed', 0, 'x');
    const ranking = (await patternRuns.latest(p.id)).find((r) => r.slug === 'ranking');
    expect(ranking).toMatchObject({ status: 'passed', rows: 12, testSql: 'SELECT 2' });
    expect(ranking?.cleanup).toEqual(['DROP VIEW IF EXISTS `a`.`b`.`pattern_ranking__gsb_12345678`']);
    await patternRuns.markRemoved(p.id, plan.sandboxView);
    expect((await patternRuns.latest(p.id)).find((r) => r.slug === 'ranking')?.cleanup).toEqual([]);
    const audit = await pool.query(
      "SELECT count(*)::int AS n FROM gsb.audit_log WHERE project_id = $1 AND action = 'try_pattern'",
      [p.id]
    );
    expect(audit.rows[0]).toEqual({ n: 3 });
    await expect(patternRuns.start('a@x.com', p.id, 'Bad-Slug', plan, 'SELECT 1')).rejects.toMatchObject({
      code: '23514',
    });
  });

  it('accepts drafts that come from a pattern', async () => {
    const p = await repo.create('a@x.com', { name: 'From pattern' });
    const draft: NewDraft = {
      name: 'v',
      yaml: 'version: 1.1',
      explanations: { summary: '', measures: {}, dimensions: {} },
      tests: [],
      issues: [],
      origin: 'pattern',
    };
    await designer.add('a@x.com', p.id, draft);
    expect((await designer.view(p.id)).draft?.origin).toBe('pattern');
  });
});
