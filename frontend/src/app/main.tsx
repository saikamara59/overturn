import React from 'react';
import { createRoot } from 'react-dom/client';
import '../styles.css';
import { ServerApp } from './ServerApp';

createRoot(document.getElementById('app')!).render(
  <React.StrictMode>
    <ServerApp />
  </React.StrictMode>,
);
