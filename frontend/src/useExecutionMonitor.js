import { useEffect } from 'react';
import { request } from './backend.js';

export default function useExecutionMonitor(record, setRecord, onError) {
  const id = record?.id;
  const active = ['queued', 'running', 'cancelling'].includes(record?.state);
  useEffect(() => {
    if (!id || !active) return undefined;
    let valid = true;
    let timer;
    const poll = async () => {
      try {
        const next = await request(`/v1/runs/${id}`);
        if (valid) setRecord((previous) => previous?.id === id ? next : previous);
      } catch (error) {
        if (valid) onError(error.message);
      } finally {
        if (valid) timer = window.setTimeout(poll, 350);
      }
    };
    timer = window.setTimeout(poll, 250);
    return () => { valid = false; window.clearTimeout(timer); };
  }, [id, active, setRecord, onError]);
}
