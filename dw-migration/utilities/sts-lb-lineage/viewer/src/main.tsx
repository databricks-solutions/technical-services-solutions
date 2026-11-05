import '@databricks/design-system/index.css';
import '@databricks/design-system/index-dark.css';
import '@databricks/design-system/fonts/dm-sans.css';
import '@xyflow/react/dist/style.css';
import './app.css';

import { ApplyGlobalStyles, DesignSystemProvider, DesignSystemThemeProvider } from '@databricks/design-system';
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';

const media = window.matchMedia('(prefers-color-scheme: dark)');

function Root() {
  const [dark, setDark] = useState(media.matches);
  useEffect(() => {
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);
  return (
    <DesignSystemThemeProvider isDarkMode={dark}>
      <DesignSystemProvider>
        <ApplyGlobalStyles />
        <App dark={dark} onToggleDark={() => setDark((d) => !d)} />
      </DesignSystemProvider>
    </DesignSystemThemeProvider>
  );
}

createRoot(document.getElementById('root')!).render(<Root />);
