import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { initializeBackend } from './backend.js';
import './styles.css';

const root = createRoot(document.getElementById('root'));

function renderApp() {
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

function renderStartupError(error) {
  root.render(
    <main className="grid min-h-screen place-items-center bg-zinc-950 p-8 text-zinc-100">
      <section className="max-w-lg rounded-xl border border-red-900 bg-red-950/30 p-6">
        <h1 className="text-lg font-semibold">Nova could not start</h1>
        <p className="mt-3 text-sm leading-6 text-red-200">
          {error instanceof Error ? error.message : String(error)}
        </p>
        <button
          className="mt-5 rounded-md border border-zinc-700 px-4 py-2 text-sm"
          onClick={() => window.location.reload()}
        >
          Retry
        </button>
      </section>
    </main>,
  );
}

initializeBackend().then(renderApp).catch(renderStartupError);
