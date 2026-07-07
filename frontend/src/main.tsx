import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { readWorkbenchData } from './data';
import './styles.css';

createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <App data={readWorkbenchData()} />
  </React.StrictMode>,
);
