import { invoke, isTauri } from '@tauri-apps/api/core';

const webEndpoint = import.meta.env.VITE_API_BASE_URL || '/api';
let backendEndpoint = webEndpoint;
const startupPollIntervalMs = 100;

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export async function initializeBackend() {
  if (!isTauri()) {
    return { endpoint: webEndpoint, ready: true, mode: 'web' };
  }

  // The hidden WebView can load before the Python sidecar has completed its
  // startup. Rust owns the timeout and reports a terminal error; until then,
  // keep waiting instead of turning the transient "not ready" state into a
  // permanent frontend error screen.
  while (true) {
    const status = await invoke('backend_status');
    if (status.error) {
      throw new Error(status.error);
    }
    if (status.ready && status.endpoint) {
      backendEndpoint = status.endpoint;
      return status;
    }
    await wait(startupPollIntervalMs);
  }
}

export function api(path) {
  return `${backendEndpoint.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
}

export function monitorBackend(onFailure, intervalMs = 1000) {
  if (!isTauri()) {
    return () => {};
  }

  let stopped = false;
  let timer;
  const poll = async () => {
    try {
      const status = await invoke('backend_status');
      if (!status.ready) {
        stopped = true;
        onFailure(new Error(status.error || 'The local Nova backend stopped.'));
        return;
      }
    } catch (error) {
      stopped = true;
      onFailure(error);
      return;
    }
    if (!stopped) timer = window.setTimeout(poll, intervalMs);
  };
  timer = window.setTimeout(poll, intervalMs);
  return () => {
    stopped = true;
    window.clearTimeout(timer);
  };
}
