import '@databricks/design-system/index.css';
import '@databricks/design-system/index-dark.css';
import '@databricks/design-system/fonts/dm-sans.css';
import './app.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
