import { randomBytes } from 'node:crypto';
import { getExecutionContext } from '@databricks/appkit';
import type { LlmEvent } from './llm';

/**
 * One MLflow trace per model call, built from the metadata event only: no prompt or response text,
 * because inputs carry customer catalog details. Uses the MLflow REST API directly instead of
 * @mlflow/core, whose init() installs a global OTel provider that would trace every AppKit span.
 */
export function toTraceInfo(event: LlmEvent, experimentId: string, endedAt: number) {
  const metadata: Record<string, string> = {
    'mlflow.trace_schema.version': '3',
    'mlflow.trace.tokenUsage': JSON.stringify({
      input_tokens: event.inputTokens ?? 0,
      output_tokens: event.outputTokens ?? 0,
      total_tokens: (event.inputTokens ?? 0) + (event.outputTokens ?? 0),
    }),
    'gsb.prompt_id': event.promptId,
    'gsb.prompt_version': String(event.promptVersion),
    'gsb.endpoint': event.endpoint,
    'gsb.outcome': event.outcome,
    'gsb.attempts': String(event.attempts),
  };
  if (event.error) metadata['gsb.error'] = event.error.slice(0, 200);
  return {
    trace_id: `tr-${randomBytes(16).toString('hex')}`,
    trace_location: { type: 'MLFLOW_EXPERIMENT', mlflow_experiment: { experiment_id: experimentId } },
    request_time: new Date(endedAt - event.latencyMs).toISOString(),
    execution_duration: `${event.latencyMs / 1000}s`,
    state: event.outcome === 'ok' ? 'OK' : 'ERROR',
    trace_metadata: metadata,
    tags: { 'mlflow.traceName': `llm.${event.promptId}` },
  };
}

/** Fire and forget, as the app service principal. A tracing failure never fails the request. */
export function logTrace(event: LlmEvent): void {
  const experimentId = process.env.MLFLOW_EXPERIMENT_ID?.trim();
  if (!experimentId) return;
  getExecutionContext()
    .client.apiClient.request({
      path: '/api/3.0/mlflow/traces',
      method: 'POST',
      headers: new Headers({ 'Content-Type': 'application/json' }),
      raw: false,
      payload: { trace: { trace_info: toTraceInfo(event, experimentId, Date.now()) } },
    })
    .catch((err: unknown) => console.warn(`MLflow trace export failed: ${(err as Error).message}`));
}
