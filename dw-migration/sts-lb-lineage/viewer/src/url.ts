import { useCallback, useEffect, useState } from 'react';

export type Tab = 'overview' | 'statistics' | 'processes' | 'objects' | 'impact' | 'changes';
export interface Route {
  tab: Tab;
  obj?: string; // object drawer
  proc?: string; // process drawer
  q?: string; // objects selector
  target?: string; // impact: object id or "proc:<name>"
  to?: string; // impact: path end
  mode?: 'down' | 'up' | 'path';
}

const KEYS: (keyof Route)[] = ['tab', 'obj', 'proc', 'q', 'target', 'to', 'mode'];

function read(): Route {
  const h = location.hash.slice(1);
  // older links were "#<object id>"
  if (h && !h.includes('=')) return { tab: 'objects', obj: decodeURIComponent(h) };
  const p = new URLSearchParams(h);
  const r: Route = { tab: (p.get('tab') as Tab) || 'overview' };
  for (const k of KEYS) if (k !== 'tab' && p.get(k)) (r as unknown as Record<string, string>)[k] = p.get(k)!;
  return r;
}

export const routeHref = (r: Route) => {
  const p = new URLSearchParams();
  for (const k of KEYS) if (r[k]) p.set(k, String(r[k]));
  return '#' + p.toString();
};

/** View state lives in the URL hash so every view can be shared and the back button works. */
export function useRoute(): [Route, (patch: Partial<Route>) => void] {
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const update = useCallback((patch: Partial<Route>) => {
    const next = { ...read(), ...patch };
    location.hash = routeHref(next).slice(1);
    setRoute(next);
  }, []);
  return [route, update];
}
