import { useCallback, useEffect, useState } from 'react';
import type { DataStateStatus } from './components/DataState';

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok) throw new ApiError(res.status, json.error ?? `Request failed (${res.status})`);
  return json as T;
}

export function statusOf(err: unknown): DataStateStatus {
  return err instanceof ApiError && (err.status === 401 || err.status === 403) ? 'forbidden' : 'error';
}

/** Loads a resource and maps the result to the four required data states. */
/** Fired after a delete that does not change the URL, so the navigation tree refreshes. */
export const PROJECTS_CHANGED = 'gsb:projects-changed';

export function useResource<T>(path: string) {
  const [state, setState] = useState<{ path: string; status: DataStateStatus; data?: T; error?: string }>({
    path,
    status: 'loading',
  });
  const fetchIt = useCallback(() => {
    api<T>(path).then(
      (data) => setState({ path, status: 'ready', data }),
      (err: unknown) => setState({ path, status: statusOf(err), error: (err as Error).message })
    );
  }, [path]);
  useEffect(fetchIt, [fetchIt]);
  const current = state.path === path ? state : { path, status: 'loading' as const };
  return {
    ...current,
    reload: () => {
      setState({ path, status: 'loading' });
      fetchIt();
    },
    setData: (data: T) => setState({ path, status: 'ready', data }),
    /** Refetches without a loading state. Stable across renders. */
    refresh: fetchIt,
  };
}
