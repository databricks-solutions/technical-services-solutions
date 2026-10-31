import { useCallback, useEffect, useRef, useState } from "react";

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      const d = body.detail;
      detail = Array.isArray(d) ? d.map((x: any) => { const loc = (x.loc || []).slice(1).join("."); return loc ? `${loc}: ${x.msg}` : x.msg; }).join("; ") : d || JSON.stringify(body);
    } catch {
      /* not JSON */
    }
    const err = new Error(`${res.status}: ${detail}`) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/** Days since a UTC timestamp from the results tables ("2026-10-01 12:00:00"); null if it can't be read. */
export function ageDays(ts: any): number | null {
  if (!ts) return null;
  const s = String(ts).trim();
  const t = Date.parse(s.includes("T") ? s : `${s.replace(" ", "T")}Z`);
  return Number.isNaN(t) ? null : (Date.now() - t) / 86_400_000;
}

/** "3 days ago", "today", "2 months ago": relative age of a scan or run. */
export function relativeAge(ts: any): string {
  const d = ageDays(ts);
  if (d === null) return "age unknown";
  if (d < 1) return "today";
  if (d < 2) return "yesterday";
  if (d < 60) return `${Math.floor(d)} days ago`;
  return `${Math.floor(d / 30)} months ago`;
}

export function useApi<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const load = useCallback(() => {
    if (!path) return;
    setLoading(true);
    setError(null);
    api<T>(path)
      .then(setData)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [path]);
  useEffect(load, [load]);
  return { data, error, loading, reload: load };
}

/** Reloads while a stored run is starting (404 until the job writes its first row) or RUNNING, and calls
 *  onFinished once when it reaches a final status after having been seen starting or running. */
export function usePollWhileRunning(status: string | undefined, error: string | null, reload: () => void,
                                    onFinished?: () => void, ms = 6000) {
  const pending = status === "RUNNING" || !!error?.startsWith("404");
  const wasPending = useRef(false);
  useEffect(() => {
    if (pending) {
      wasPending.current = true;
      const t = setTimeout(reload, ms);
      return () => clearTimeout(t);
    }
    if (wasPending.current && status) {
      wasPending.current = false;
      onFinished?.();
    }
  }, [pending, status, error, reload, ms]);
}

export type JobState = {
  job_run_id: string;
  life_cycle: string | null;
  result: string | null;
  /** Only for runs the signed-in user started (or operators): the Databricks message and run link. */
  message?: string | null;
  url?: string | null;
  start_time?: number | null;
  end_time?: number | null;
  error?: string;
};

export const TERMINAL_LIFE_CYCLES = ["TERMINATED", "INTERNAL_ERROR", "SKIPPED"];

/** True while a started job hasn't reached a terminal state (and polling hasn't given up). */
export const jobRunning = (jobRunId: string | null, s: JobState | null) =>
  !!jobRunId && !(s && (s.error || TERMINAL_LIFE_CYCLES.includes(s.life_cycle || "")));

/** Polls a job run until it finishes, then calls onDone. */
export function useJob(jobRunId: string | null, onDone?: (s: JobState) => void) {
  const [state, setState] = useState<JobState | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    setState(null);
    if (!jobRunId) return;
    let stop = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const s = await api<JobState>(`/api/jobs/${jobRunId}`);
        if (stop) return;
        failures = 0;
        setState(s);
        if (TERMINAL_LIFE_CYCLES.includes(s.life_cycle || "")) {
          done.current?.(s);
          return;
        }
      } catch (e: any) {
        if (stop) return;
        if (++failures >= 4) {
          const s = { job_run_id: jobRunId, life_cycle: null, result: null, message: null, url: null,
                      error: `Couldn't read the job status (${e.message || e}). Check the job run in Jobs & Pipelines.` };
          setState(s);
          done.current?.(s);
          return;
        }
      }
      if (!stop) timer = setTimeout(tick, 5000);
    };
    tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobRunId]);
  return state;
}

export const fmt = (n: any, digits = 0) => {
  const v = Number(n);
  if (n === null || n === undefined || n === "" || Number.isNaN(v)) return "-";
  if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(1) + "B";
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (Math.abs(v) >= 1e4) return (v / 1e3).toFixed(1) + "K";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
};

export const pct = (n: any) => {
  const v = Number(n);
  return n === null || n === undefined || n === "" || Number.isNaN(v) ? "-" : `${Math.round(v * 100)}%`;
};
