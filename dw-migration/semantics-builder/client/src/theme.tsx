import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ApplyGlobalStyles, DesignSystemProvider, DesignSystemThemeProvider } from '@databricks/design-system';

export type ThemePreference = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'gsb-theme';
const ThemeContext = createContext<{ preference: ThemePreference; setPreference: (p: ThemePreference) => void }>({
  preference: 'system',
  setPreference: () => {},
});

export const useThemePreference = () => useContext(ThemeContext);

function readPreference(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'light' || stored === 'dark' ? stored : 'system';
}

function useSystemDark(): boolean {
  const query = window.matchMedia('(prefers-color-scheme: dark)');
  const [dark, setDark] = useState(query.matches);
  useEffect(() => {
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [query]);
  return dark;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const systemDark = useSystemDark();
  const isDarkMode = preference === 'dark' || (preference === 'system' && systemDark);

  const setPreference = (p: ThemePreference) => {
    localStorage.setItem(STORAGE_KEY, p);
    setPreferenceState(p);
  };

  return (
    <ThemeContext.Provider value={{ preference, setPreference }}>
      {/* DesignSystemThemeProvider is the only dark-mode switch Du Bois exposes (see README). */}
      <DesignSystemThemeProvider isDarkMode={isDarkMode}>
        <DesignSystemProvider>
          <ApplyGlobalStyles />
          {children}
        </DesignSystemProvider>
      </DesignSystemThemeProvider>
    </ThemeContext.Provider>
  );
}
