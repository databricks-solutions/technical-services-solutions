import { useSearchParams } from 'react-router';

/** The open inner tab, kept in the URL (?tab=) so refresh, back and shared links keep it. */
export function useTab<T extends string>(tabs: readonly T[], fallback: T): [T, (t: string) => void] {
  const [search, setSearch] = useSearchParams();
  const tab = tabs.find((t) => t === search.get('tab')) ?? fallback;
  const setTab = (t: string) =>
    setSearch(
      (p) => {
        p.set('tab', t);
        return p;
      },
      { replace: true }
    );
  return [tab, setTab];
}
