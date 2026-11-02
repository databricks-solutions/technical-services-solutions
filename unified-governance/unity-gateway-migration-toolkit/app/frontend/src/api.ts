import { useCallback, useEffect, useRef, useState } from "react";

/** API error: `message` is "STATUS: text" (for code paths), `detail` is the raw body detail, and `job` is set when a 409 names the active run. */
export type ApiError = Error & { status: number; detail?: any; job?: { job_run_id: string; url: string | null } };

/** Text from a FastAPI-style error body: a string, an object with a message, or a validation list. */
function detailText(d: any): string {
  if (Array.isArray(d)) return d.map((x: any) => { const loc = (x.loc || []).slice(1).join("."); return loc ? `${loc}: ${x.msg}` : x.msg; }).join("; ");
  if (d && typeof d === "object") return String(d.message || d.detail || "");
  return d ? String(d) : "";
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let body: any = null;
    try {
      body = await res.json();
    } catch {
      /* not JSON */
    }
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : body;
    const err = new Error(`${res.status}: ${detailText(detail) || res.statusText}`) as ApiError;
    err.status = res.status;
    err.detail = detail;
    const src = detail && typeof detail === "object" && !Array.isArray(detail) && detail.job_run_id ? detail : body?.job_run_id ? body : null;
    if (src) err.job = { job_run_id: String(src.job_run_id), url: src.url ?? null };
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

/** A 404 whose detail is exactly "not found": the id doesn't exist. */
export const isUnknownId = (error: string | null | undefined) => /^404: not found$/i.test(String(error || ""));

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

/** Reloads while a stored run is starting (a 404 that isn't "not found") or RUNNING, and calls
 *  onFinished once when it reaches a final status after having been seen starting or running. */
export function usePollWhileRunning(status: string | undefined, error: string | null, reload: () => void,
                                    onFinished?: () => void, ms = 6000) {
  // A run that is starting (202 with status STARTING) or running keeps the page polling.
  const pending = status === "RUNNING" || status === "STARTING";
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

/** "missing_secret_key" -> "Missing secret key". Fallback for codes the server didn't label; keeps the rest of the text as is (paths, names). */
export function humanize(s: any): string {
  const t = String(s ?? "").replace(/_+/g, " ").trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : "-";
}

/** Plain names for endpoint kinds and plan actions (the codes come from the scan). */
export const KIND_LABEL: Record<string, string> = {
  external_model: "External model", pt: "Provisioned Throughput", v1_foundation: "Foundation model (v1)",
  system_ppt: "Databricks pay-per-token", deleted_or_unknown: "Deleted or unknown",
  v2_workspace_endpoint: "v2 workspace endpoint", custom_model: "Custom model", agent: "Agent endpoint",
};
/** Plain names for the caller classes (planner caller_class). Customer-owned is every class but platform. */
export const CALLER_LABEL: Record<string, string> = {
  platform: "Databricks-managed",
  no_client_info: "No client info (likely ai_query or batch: yours)",
  coding_agent: "Coding agent",
  sdk: "Databricks SDK or MLflow",
  llm_sdk: "LLM SDK (OpenAI, LangChain)",
  http: "HTTP client",
  service_principal: "Service principal",
  user: "User",
  unknown: "Unknown",
};
export const callerLabel = (c: any) => (c ? CALLER_LABEL[String(c)] || humanize(c) : "Not in the latest scan");
export const ACTION_LABEL: Record<string, string> = {
  create_model_service: "Create model service", use_system_ai: "Use existing system AI service", retire: "Retire",
};
export const kindLabel = (k: any) => KIND_LABEL[String(k)] || humanize(k);
export const actionLabel = (a: any) => ACTION_LABEL[String(a)] || humanize(a);

/** "1 service", "2 services". */
export const sentence = (s: any) => { const t = String(s ?? ""); return t ? t.charAt(0).toUpperCase() + t.slice(1) : t; };
export const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

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
