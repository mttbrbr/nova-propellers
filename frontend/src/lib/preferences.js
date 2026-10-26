// Per-viewer conveniences kept in browser storage: pinned and recently opened projects.
// Storage can be unavailable (private windows, cleared data), so every access is guarded.
const PINNED = 'nova.pinnedProjects';
const RECENT = 'nova.recentProjects';

function read(key) {
  try { return JSON.parse(window.localStorage.getItem(key) || '[]'); } catch { return []; }
}
function write(key, value) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event('nova:preferences'));
}

export const pinnedProjects = () => read(PINNED);
export const recentProjects = () => read(RECENT);
export function togglePinned(id) {
  const current = pinnedProjects();
  write(PINNED, current.includes(id) ? current.filter((item) => item !== id) : [id, ...current]);
}
export function rememberProject(id) {
  write(RECENT, [id, ...recentProjects().filter((item) => item !== id)].slice(0, 8));
}
export function forgetProject(id) {
  write(PINNED, pinnedProjects().filter((item) => item !== id));
  write(RECENT, recentProjects().filter((item) => item !== id));
}
