import { Search, Star } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { request } from '../backend.js';
import { pinnedProjects, recentProjects, togglePinned } from '../lib/preferences.js';

const ago = (iso) => {
  if (!iso) return '';
  const minutes = Math.max(0, (Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  const days = Math.round(minutes / 60 / 24);
  return days === 1 ? 'yesterday' : days < 30 ? `${days} days ago` : new Date(iso).toLocaleDateString();
};

function Highlight({ text, query }) {
  const index = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (index < 0) return text;
  return <>{text.slice(0, index)}<mark className="bg-transparent font-semibold text-nv-accent">{text.slice(index, index + query.length)}</mark>{text.slice(index + query.length)}</>;
}

export function usePreferences() {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const update = () => setVersion((value) => value + 1);
    window.addEventListener('nova:preferences', update);
    return () => window.removeEventListener('nova:preferences', update);
  }, []);
  // Version forces a re-read after another component changes the stored lists.
  return useMemo(() => ({ pinned: pinnedProjects(), recent: recentProjects(), version }), [version]);
}

// Searchable project switcher for hundreds of projects (Ctrl+P). It searches project
// names, simulation names, airfoils and solvers; empty search shows pinned and recent.
export default function ProjectPicker({ project, locked, onOpen, onBrowse }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState([]);
  const [active, setActive] = useState(0);
  const [error, setError] = useState('');
  const { pinned, recent } = usePreferences();
  const input = useRef(null);
  const trigger = useRef(null);
  const listbox = useId();

  useEffect(() => {
    const show = () => { if (!locked) setOpen(true); };
    window.addEventListener('nova:open-project-picker', show);
    return () => window.removeEventListener('nova:open-project-picker', show);
  }, [locked]);
  useEffect(() => {
    if (!open) return;
    setQuery(''); setActive(0); setError('');
    request('/v2/project-index').then(setIndex).catch((caught) => setError(caught.message));
    window.setTimeout(() => input.current?.focus(), 0);
  }, [open]);

  const byId = useMemo(() => Object.fromEntries(index.map((row) => [row.id, row])), [index]);
  const term = query.trim().toLowerCase();
  const items = useMemo(() => {
    if (!term) {
      const ids = [...new Set([...pinned, ...recent])].filter((id) => byId[id]);
      const list = ids.map((id) => ({ key: id, group: pinned.includes(id) ? 'Pinned' : 'Recent', project: byId[id] }));
      if (list.length < 8) {
        index.filter((row) => !ids.includes(row.id)).slice(0, 8 - list.length).forEach((row) => list.push({ key: row.id, group: 'Recently modified', project: row }));
      }
      return list;
    }
    const projects = index.filter((row) => [row.name, row.id, ...row.airfoils, ...row.models, ...row.simulation_list.map((s) => s.name)].some((value) => value?.toLowerCase().includes(term)))
      .slice(0, 40).map((row) => ({ key: row.id, group: 'Projects', project: row }));
    const simulations = index.flatMap((row) => row.simulation_list.filter((s) => s.name.toLowerCase().includes(term)).map((s) => ({ key: `${row.id}:${s.id}`, group: 'Simulations', project: row, simulation: s })))
      .slice(0, 20);
    return [...projects, ...simulations];
  }, [term, index, byId, pinned, recent]);

  const close = () => { setOpen(false); trigger.current?.focus(); };
  const choose = (item) => { if (!item) return; setOpen(false); onOpen(item.project.id, item.simulation?.id || null); };
  const onKey = (event) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((value) => Math.min(items.length - 1, value + 1)); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((value) => Math.max(0, value - 1)); }
    else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); setOpen(false); onBrowse(); }
    else if (event.key === 'Enter') { event.preventDefault(); choose(items[active]); }
    else if (event.key === 'Escape') { event.preventDefault(); close(); }
  };
  const groups = [...new Set(items.map((item) => item.group))];

  return <>
    <button ref={trigger} type="button" disabled={locked} aria-haspopup="dialog" aria-expanded={open} data-project-id={project?.id || ''}
      aria-label={`Project: ${project?.name || 'none open'}`} title="Open project · Ctrl+P" onClick={() => setOpen(true)}
      className="flex h-8 min-w-0 max-w-[240px] items-center gap-2 rounded-md px-2 text-[13px] text-nv-muted hover:bg-nv-hover disabled:opacity-50">
      <Search size={14} aria-hidden="true" className="shrink-0" /><span className="truncate">{project?.name || 'No project · open…'}</span>
    </button>
    {open && <div className="fixed inset-0 z-50 bg-black/55" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <div role="dialog" aria-modal="true" aria-label="Open project" className="mx-auto mt-[72px] w-[min(680px,calc(100vw-24px))] overflow-hidden rounded-[14px] border border-nv-edge bg-nv-raised shadow-2xl shadow-black/70">
        <div className="flex items-center gap-2.5 border-b border-nv-edge px-4 py-3.5">
          <Search size={18} className="text-nv-muted" aria-hidden="true" />
          <input ref={input} role="combobox" aria-expanded="true" aria-controls={listbox} aria-activedescendant={items[active] ? `${listbox}-${active}` : undefined}
            aria-label="Search projects and simulations" placeholder="Search projects, simulations, airfoils or solvers…" value={query}
            onChange={(event) => { setQuery(event.target.value); setActive(0); }} onKeyDown={onKey}
            className="min-w-0 flex-1 bg-transparent text-[15px] text-nv-ink outline-none" />
          <span className="text-xs text-nv-muted">{term ? `${items.filter((item) => item.group === 'Projects').length} of ${index.length}` : `${index.length} projects`}</span>
        </div>
        <ul id={listbox} role="listbox" aria-label="Projects" className="m-0 max-h-[min(520px,calc(100vh-220px))] list-none overflow-y-auto p-1.5">
          {error && <li className="px-3 py-2 text-[13px] text-nv-err-ink">{error}</li>}
          {!error && !items.length && <li className="px-3 py-6 text-center text-[13px] text-nv-muted">{index.length ? 'No project or simulation matches.' : 'No saved projects yet. Save a draft to create one.'}</li>}
          {groups.map((group) => <li key={group} role="presentation">
            <p className="m-0 px-3 pb-1 pt-2.5 text-xs text-nv-muted">{group}</p>
            <ul role="group" aria-label={group} className="m-0 list-none p-0">{items.map((item, position) => item.group !== group ? null :
              <li key={item.key} id={`${listbox}-${position}`} role="option" aria-selected={position === active} data-project-id={item.project.id}
                data-simulation-id={item.simulation?.id} onMouseEnter={() => setActive(position)} onClick={() => choose(item)}
                className={`grid cursor-pointer grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-3 rounded-lg px-3 py-2 ${position === active ? 'bg-nv-active' : ''}`}>
                {item.simulation ? <span aria-hidden="true" className="text-nv-muted">↳</span>
                  : <button type="button" tabIndex={-1} aria-label={pinned.includes(item.project.id) ? `Unpin ${item.project.name}` : `Pin ${item.project.name}`}
                    onClick={(event) => { event.stopPropagation(); togglePinned(item.project.id); }}
                    className={pinned.includes(item.project.id) ? 'text-nv-warn' : 'text-nv-edge-strong hover:text-nv-muted'}><Star size={15} fill={pinned.includes(item.project.id) ? 'currentColor' : 'none'} aria-hidden="true" /></button>}
                <span className="min-w-0">
                  <span className="block truncate text-[13px]"><Highlight text={item.simulation ? item.simulation.name : item.project.name} query={query.trim()} />{item.project.id === project?.id && !item.simulation && <span className="text-nv-muted"> · current</span>}</span>
                  <span className="block truncate text-xs text-nv-muted">{item.simulation ? `in ${item.project.name} · ${item.simulation.kind === 'propeller' ? 'propeller' : item.simulation.kind}` : `${item.project.simulations} simulations · ${item.project.runs} runs${item.project.airfoils.length ? ` · ${item.project.airfoils.join(', ')}` : ''}`}</span>
                </span>
                <span className="text-xs text-nv-muted">{ago(item.project.updated_at)}</span>
              </li>)}</ul>
          </li>)}
        </ul>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-nv-edge bg-nv-panel px-4 py-2.5 text-xs text-nv-muted">
          <span><kbd className="font-mono">↑↓</kbd> move</span><span><kbd className="font-mono">Enter</kbd> open</span><span><kbd className="font-mono">Ctrl Enter</kbd> Library</span><span><kbd className="font-mono">Esc</kbd> close</span>
          <button type="button" className="ml-auto text-nv-accent hover:text-nv-accent-soft" onClick={() => { setOpen(false); onBrowse(); }}>Browse all {index.length} in Library →</button>
        </div>
      </div>
    </div>}
  </>;
}
