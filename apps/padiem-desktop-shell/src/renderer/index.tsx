import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app.js';

const container = document.getElementById('root');
if (!container) {
  throw new Error('padiem shell root container missing');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
