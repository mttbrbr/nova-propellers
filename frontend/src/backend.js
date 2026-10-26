import { invoke, isTauri } from '@tauri-apps/api/core';

const webEndpoint = import.meta.env.VITE_API_BASE_URL || '/api';
let backendEndpoint = webEndpoint;
let sessionToken;
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
      sessionToken = status.sessionToken;
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

export async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers);
  if (sessionToken) headers.set('X-Nova-Session', sessionToken);
  const response = await window.fetch(url, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => `${item.loc?.join('.')}: ${item.msg}`).join('; ')
      : body.detail;
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response;
}

export async function request(path, body, method = 'POST') {
  const response = await apiFetch(api(path), body === undefined ? {} : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  return response.json();
}

export async function waitForExecution(record, onProgress, onPollingError) {
  let current = record;
  let interrupted = false;
  while (['queued', 'running', 'cancelling'].includes(current.state)) {
    await wait(250);
    try {
      current = await request(`/v1/runs/${current.id}`);
      if (interrupted) { interrupted = false; onPollingError?.(null); }
      onProgress?.(current);
    } catch (error) {
      if (error.status && error.status < 500 && ![408, 429].includes(error.status)) throw error;
      interrupted = true;
      onPollingError?.(error);
      await wait(750);
    }
  }
  return current;
}

export async function download(path, filename) {
  const response = await apiFetch(api(path));
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function fileBase64(file, maxBytes = 20 * 1024 * 1024) {
  if (file.size > maxBytes) throw new Error(`File exceeds the ${Math.floor(maxBytes / 1024 / 1024)} MiB limit`);
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
  return window.btoa(binary);
}
