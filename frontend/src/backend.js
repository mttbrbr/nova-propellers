import { invoke, isTauri } from '@tauri-apps/api/core';

const webEndpoint = import.meta.env.VITE_API_BASE_URL || '/api';
let backendEndpoint = webEndpoint;

export async function initializeBackend() {
  if (!isTauri()) {
    return { endpoint: webEndpoint, ready: true, mode: 'web' };
  }

  const status = await invoke('backend_status');
  if (!status.ready || !status.endpoint) {
    throw new Error(status.error || 'The local Nova backend is not ready.');
  }
  backendEndpoint = status.endpoint;
  return status;
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
