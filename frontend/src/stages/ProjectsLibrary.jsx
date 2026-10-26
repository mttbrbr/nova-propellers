import { Search, Star } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { request } from '../backend.js';
import { usePreferences } from '../components/ProjectPicker.jsx';
import { formatValue } from '../lib/blade.js';
import { togglePinned } from '../lib/preferences.js';
import { Button, Metric, Notice, Section, SelectField } from '../ui/controls.jsx';

const PAGE = 40;
const when = (iso) => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';

function DeleteDialog({ projects, onCancel, onConfirm }) {
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const phrase = projects.length === 1 ? projects[0].name : `delete ${projects.length} projects`;
  const records = projects.reduce((sum, item) => sum + item.simulations + item.runs, 0);
  const field = useRef(null);
  useEffect(() => { field.current?.focus(); }, []);
  return <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6" onKeyDown={(event) => { if (event.key === 'Escape') onCancel(); }}>
    <div role="dialog" aria-modal="true" aria-labelledby="delete-title" className="flex w-full max-w-md flex-col gap-4 rounded-xl border border-nv-err/40 bg-nv-panel p-6">
      <h2 id="delete-title" className="m-0 text-lg">{projects.length === 1 ? `Delete “${projects[0].name}”?` : `Delete ${projects.length} projects?`}</h2>
      <p className="m-0 text-[13px] leading-relaxed text-nv-reference">This removes {projects.length === 1 ? 'the project' : 'the projects'} with {records} simulations and runs from this computer, including their geometry revisions. It cannot be undone; export a .nova first if you may need {projects.length === 1 ? 'it' : 'them'} again.</p>
      <label className="flex flex-col gap-1.5 text-[13px] text-nv-muted">Type <span className="font-mono text-nv-ink">{phrase}</span> to confirm
        <input ref={field} aria-label="Confirmation" value={typed} onChange={(event) => setTyped(event.target.value)}
          className="h-[34px] rounded-md border border-nv-edge bg-nv-chrome px-2.5 text-[13px] text-nv-ink focus:border-nv-err focus:outline-none" /></label>
      {error && <Notice tone="err" role="alert">{error}</Notice>}
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onCancel}>Keep</Button>
        <Button variant="danger" disabled={typed !== phrase || busy} onClick={async () => {
          setBusy(true); setError('');
          try { await onConfirm(); } catch (caught) { setError(caught.message); setBusy(false); }
        }}>{busy ? 'Deleting…' : 'Delete permanently'}</Button></div>
    </div>
  </div>;
}

function ProjectDetail({ row, current, onOpen, onCompare, onExport, onDelete }) {
  const [simulations, setSimulations] = useState([]);
  const { pinned } = usePreferences();
  useEffect(() => {
    let valid = true;
    setSimulations([]);
    request(`/v1/projects/${row.id}/simulations`).then((items) => { if (valid) setSimulations(items); }).catch(() => {});
    return () => { valid = false; };
  }, [row.id]);
  const isPinned = pinned.includes(row.id);
  return <>
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0"><h2 className="m-0 truncate text-xl font-semibold">{row.name}</h2><p className="m-0 mt-1.5 text-[13px] text-nv-muted">Modified {when(row.updated_at)} · revision {row.revision}{current ? ' · open now' : ''}</p></div>
      <button type="button" aria-label={isPinned ? 'Unpin project' : 'Pin project'} aria-pressed={isPinned} onClick={() => togglePinned(row.id)}
        className={isPinned ? 'text-nv-warn' : 'text-nv-muted hover:text-nv-ink'}><Star size={18} fill={isPinned ? 'currentColor' : 'none'} aria-hidden="true" /></button>
    </div>
    <div className="grid grid-cols-3 gap-2">
      <Button className="!bg-nv-ink font-semibold !text-nv-canvas hover:!bg-nv-ink-strong" disabled={current} onClick={() => onOpen(row.id)}>Open</Button>
      <Button onClick={() => onCompare([row.id])}>Compare…</Button><Button onClick={() => onExport(row)}>Export .nova</Button>
    </div>
    <dl className="m-0 grid grid-cols-3 gap-4 border-y border-nv-line py-[18px]">
      <Metric size="md" label="Last thrust" value={row.last_result ? formatValue(row.last_result.thrust_n, 4) : '—'} unit={row.last_result ? 'N' : ''} sub={row.last_result ? `${(row.last_result.model || '').toUpperCase()} · ${row.last_result.simulation_name || ''}` : row.last_run_state === 'failed' ? 'last run failed' : 'never run'} />
      <Metric size="md" label="Runs" value={row.runs} sub={`${row.studies} studies`} />
      <Metric size="md" label="Solvers" value={row.models.map((m) => m.toUpperCase()).join(', ') || '—'} />
    </dl>
    <Section title={`Simulations · ${row.simulations}`}>
      <table className="w-full border-collapse text-[13px]"><tbody>{simulations.map((item) => <tr key={item.id} className="border-t border-nv-line first:border-t-0">
        <td className="py-2">{item.name}</td>
        <td className="py-2 text-right font-mono text-nv-muted">{item.kind && item.kind !== 'propeller' ? item.kind : `${(item.workflow?.nodes || []).filter((n) => n.type === 'analysis').map((n) => (n.config?.model || 'bemt').toUpperCase()).join(' + ')} · ${formatValue(item.inputs?.rpm, 5)} rpm`}</td>
      </tr>)}{!simulations.length && <tr><td className="py-2 text-nv-muted">{row.simulations ? 'Loading…' : 'No simulations'}</td></tr>}</tbody></table>
    </Section>
    <div className="flex-1" />
    <section aria-labelledby="danger-title" className="flex flex-col gap-2 rounded-[10px] border border-nv-err/30 p-4">
      <h3 id="danger-title" className="m-0 text-[13px] font-semibold text-nv-err-ink">Delete project</h3>
      <p className="m-0 text-[13px] leading-relaxed text-nv-reference">Removes {row.simulations} simulations and {row.runs} runs with their geometry revisions from this computer. You will be asked to type the project name.</p>
      <Button variant="danger" className="self-start" onClick={() => onDelete([row])}>Delete project…</Button>
    </section>
  </>;
}

// Hook rather than component: filters, table and detail fill three different columns.
export default function useProjectsLibrary({ currentProjectId, onOpen, onCompare, onExport, onDelete, onCount }) {
  const [index, setIndex] = useState([]);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [show, setShow] = useState('all');
  const [sort, setSort] = useState('modified');
  const [solver, setSolver] = useState('');
  const [selected, setSelected] = useState([]);
  const [focused, setFocused] = useState(null);
  const [limit, setLimit] = useState(PAGE);
  const [confirm, setConfirm] = useState(null);
  const { pinned } = usePreferences();
  const sentinel = useRef(null);
  const load = () => request('/v2/project-index').then((rows) => { setIndex(rows); onCount?.(rows.length); setError(''); }).catch((caught) => setError(caught.message));
  // Load once on entry; deletions and imports call load() explicitly.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);
  const term = query.trim().toLowerCase();
  const rows = useMemo(() => index
    .filter((row) => show !== 'pinned' || pinned.includes(row.id))
    .filter((row) => show !== 'results' || row.last_result)
    .filter((row) => show !== 'never' || !row.runs)
    .filter((row) => !solver || row.models.includes(solver))
    .filter((row) => !term || [row.name, row.id, ...row.airfoils, ...row.models, ...row.simulation_list.map((s) => s.name)].some((value) => value?.toLowerCase().includes(term)))
    .sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'runs' ? b.runs - a.runs : String(b.updated_at).localeCompare(String(a.updated_at))),
  [index, show, pinned, solver, term, sort]);
  useEffect(() => { setLimit(PAGE); }, [term, show, sort, solver]);
  useEffect(() => {
    if (!sentinel.current) return undefined;
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) setLimit((value) => value + PAGE); });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [rows.length]);
  const focusRow = index.find((row) => row.id === focused) || rows[0];
  const chosen = index.filter((row) => selected.includes(row.id));
  const toggle = (id) => setSelected((list) => list.includes(id) ? list.filter((item) => item !== id) : [...list, id]);
  const remove = async (projects) => {
    await onDelete(projects.map((row) => row.id));
    setConfirm(null); setSelected((list) => list.filter((id) => !projects.some((row) => row.id === id))); setFocused(null);
    await load();
  };
  const filters = <section aria-labelledby="projects-show" className="flex flex-col gap-2.5">
    <h2 id="projects-show" className="m-0 text-[13px] font-semibold">Show</h2>
    <div className="flex flex-wrap gap-1.5">{[['all', 'All'], ['pinned', `★ Pinned · ${pinned.filter((id) => index.some((row) => row.id === id)).length}`], ['results', 'With results'], ['never', 'Never run']].map(([id, name]) =>
      <button key={id} type="button" aria-pressed={show === id} onClick={() => setShow(id)} className={`h-7 rounded-full border px-2.5 text-[12.5px] ${show === id ? 'border-nv-accent text-nv-ink-strong' : 'border-nv-edge text-nv-reference hover:bg-nv-hover'}`}>{name}</button>)}</div>
    <SelectField label="Sort" ariaLabel="Sort projects" value={sort} onChange={setSort} options={[['modified', 'Last modified'], ['name', 'Name'], ['runs', 'Most runs']]} />
    <SelectField label="Solver" ariaLabel="Filter by solver" value={solver} onChange={setSolver} options={[['', 'Any'], ['bemt', 'BEMT'], ['llt', 'LLT'], ['vlm', 'VLM'], ['bem', 'BEM']]} />
  </section>;
  return {
    filters,
    main: <>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex h-[38px] min-w-[280px] flex-1 items-center gap-2 rounded-md border border-nv-edge bg-nv-chrome px-2.5 focus-within:border-nv-accent">
          <Search size={16} className="text-nv-muted" aria-hidden="true" />
          <input aria-label="Search projects" placeholder="Search name, simulation, airfoil or solver…" value={query} onChange={(event) => setQuery(event.target.value)} className="h-9 min-w-0 flex-1 bg-transparent text-[13px] outline-none" />
        </label>
        <span className="text-nv-muted">{rows.length === index.length ? `${index.length} projects` : `${rows.length} of ${index.length}`}</span>
      </div>
      {error && <Notice tone="err" role="alert">{error}</Notice>}
      {selected.length > 0 && <div role="toolbar" aria-label="Selection actions" className="flex flex-wrap items-center gap-2.5 rounded-lg border border-nv-line bg-nv-panel px-3 py-1.5">
        <span className="flex-1">{selected.length} selected</span>
        <Button className="!h-[30px]" disabled={selected.length > 4} title={selected.length > 4 ? 'Compare up to 4 projects' : undefined} onClick={() => onCompare(selected)}>Compare results</Button>
        <Button className="!h-[30px]" onClick={() => chosen.forEach((row) => onExport(row))}>Export .nova</Button>
        <Button variant="danger" className="!h-[30px]" onClick={() => setConfirm(chosen)}>Delete…</Button>
        <Button variant="ghost" className="!h-[30px]" onClick={() => setSelected([])}>Clear</Button>
      </div>}
      <div className="min-h-0 overflow-x-auto">
        <table aria-label="Saved projects" className="w-full min-w-[640px] border-collapse text-[13px]">
          <thead><tr className="text-xs text-nv-muted">
            <th scope="col" className="w-9 pb-2.5 text-left font-medium"><span className="sr-only">Select</span></th><th scope="col" className="w-7 pb-2.5"><span className="sr-only">Pinned</span></th>
            <th scope="col" className="pb-2.5 text-left font-medium">Project</th><th scope="col" className="px-3 pb-2.5 text-right font-medium">Simulations</th><th scope="col" className="px-3 pb-2.5 text-right font-medium">Runs</th>
            <th scope="col" className="px-3 pb-2.5 text-left font-medium">Last result</th><th scope="col" className="pb-2.5 text-left font-medium">Modified</th></tr></thead>
          <tbody>{rows.slice(0, limit).map((row) => <tr key={row.id} data-project-id={row.id} aria-selected={focusRow?.id === row.id}
            className={`cursor-pointer border-t border-nv-line ${focusRow?.id === row.id ? 'bg-nv-accent/[.07]' : 'hover:bg-nv-raised'}`} onClick={() => setFocused(row.id)}>
            <td className="py-2.5" onClick={(event) => event.stopPropagation()}><input type="checkbox" className="accent-nv-accent" aria-label={`Select ${row.name}`} checked={selected.includes(row.id)} onChange={() => toggle(row.id)} /></td>
            <td className={pinned.includes(row.id) ? 'text-nv-warn' : 'text-nv-edge'} aria-label={pinned.includes(row.id) ? 'Pinned' : undefined}>★</td>
            <td className="py-2.5"><button type="button" className="text-left" onClick={() => setFocused(row.id)}><span className="block">{row.name}{row.id === currentProjectId && <span className="text-nv-muted"> · open</span>}</span>
              <span className="mt-0.5 block text-xs text-nv-muted">{[row.airfoils.join(', '), row.models.map((m) => m.toUpperCase()).join(', ')].filter(Boolean).join(' · ') || 'No propeller simulation'}</span></button></td>
            <td className="px-3 text-right font-mono">{row.simulations}</td><td className="px-3 text-right font-mono">{row.runs}</td>
            <td className="px-3 font-mono text-nv-reference">{row.last_result ? `${formatValue(row.last_result.thrust_n, 4)} N · ${(row.last_result.model || '').toUpperCase()}` : <span className={`font-sans ${row.last_run_state === 'failed' ? 'text-nv-err-ink' : 'text-nv-muted'}`}>{row.last_run_state === 'failed' ? 'last run failed' : row.runs ? 'no finished result' : 'never run'}</span>}</td>
            <td className="text-nv-muted">{when(row.updated_at)}</td>
          </tr>)}</tbody>
        </table>
        {rows.length > limit && <div ref={sentinel} className="py-3 text-[12.5px] text-nv-muted">Showing {limit} of {rows.length} · more load as you scroll</div>}
        {!rows.length && !error && <p className="m-0 py-6 text-[13px] text-nv-muted">{index.length ? 'No project matches these filters.' : 'No saved projects yet. Save a draft from the header to create one.'}</p>}
      </div>
      {confirm && <DeleteDialog projects={confirm} onCancel={() => setConfirm(null)} onConfirm={() => remove(confirm)} />}
    </>,
    side: focusRow ? <ProjectDetail key={focusRow.id} row={focusRow} current={focusRow.id === currentProjectId} onOpen={onOpen} onCompare={onCompare} onExport={onExport} onDelete={(projects) => setConfirm(projects)} />
      : <p className="m-0 text-[13px] text-nv-muted">Select a project to see its details.</p>,
  };
}
