import { describe, expect, it } from 'vitest';
import { toTraceInfo } from './mlflow';

describe('toTraceInfo', () => {
  it('records metadata only, in the MLflow v3 trace shape', () => {
    const info = toTraceInfo(
      {
        promptId: 'readiness.assess',
        promptVersion: 1,
        endpoint: 'model',
        outcome: 'error',
        attempts: 3,
        latencyMs: 1500,
        inputTokens: 10,
        outputTokens: 5,
        error: '429',
      },
      '123',
      Date.parse('2026-01-01T00:00:01.500Z')
    );
    expect(info).toMatchObject({
      trace_location: { type: 'MLFLOW_EXPERIMENT', mlflow_experiment: { experiment_id: '123' } },
      request_time: '2026-01-01T00:00:00.000Z',
      execution_duration: '1.5s',
      state: 'ERROR',
      tags: { 'mlflow.traceName': 'llm.readiness.assess' },
    });
    expect(info.trace_id).toMatch(/^tr-[0-9a-f]{32}$/);
    expect(JSON.parse(info.trace_metadata['mlflow.trace.tokenUsage'])).toEqual({
      input_tokens: 10,
      output_tokens: 5,
      total_tokens: 15,
    });
    expect(Object.keys(info)).not.toContain('request_preview');
  });
});
