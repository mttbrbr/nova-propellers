import { useCallback, useEffect, useState } from 'react';
import { request } from '../backend.js';
import { Button, Notice, StatusDot } from '../ui/controls.jsx';

const fieldClass = 'h-8 w-full min-w-0 rounded-md border border-nv-edge bg-nv-chrome px-2.5 font-mono text-[12.5px] text-nv-ink focus:border-nv-accent focus:outline-none';
const Kbd = ({ children }) => <kbd className="rounded border border-b-2 border-nv-edge bg-nv-chrome px-1.5 font-mono text-[11px] text-nv-muted">{children}</kbd>;

const sections = [['integrations', 'Integrations'], ['shortcuts', 'Shortcuts']];
const SHORTCUTS = [
  ['Global', [['Run', 'Ctrl Enter'], ['Save project', 'Ctrl S'], ['Search projects', 'Ctrl P'], ['Open settings', 'Ctrl ,'], ['Full screen', 'F11'], ['Design stages', 'Alt 1–4'], ['Move station (Geometry, Results)', '← →']]],
  ['Workflow', [['Add a block here', 'Double-click'], ['Search blocks', 'Ctrl K'], ['Run or cancel the workflow', 'Ctrl Enter'], ['Save workflow', 'Ctrl S'], ['Duplicate block', 'Ctrl D'],
    ['Remove block', 'Del'], ['Auto-layout', 'L'], ['Fit view', 'F'], ['Show shortcuts', '?'], ['Close cards', 'Esc']]],
];

// One external program: its saved local configuration (path and detected version). Paths stay on this computer.
function IntegrationCard({ adapter, saved, onSaved }) {
  const [executable, setExecutable] = useState(saved?.executable || '');
  const [probe, setProbe] = useState(saved?.probe || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  useEffect(() => { setExecutable(saved?.executable || ''); setProbe(saved?.probe || null); }, [saved?.id, saved?.executable]); // eslint-disable-line react-hooks/exhaustive-deps
  const environment = adapter.environments[0] || 'local_executable';
  const run = async (save) => {
    setBusy(true); setError(''); setNote('');
    try {
      const result = await request(`/v1/adapters/${adapter.id}/${save ? 'configure' : 'probe'}`, { executable, environment_kind: environment, options: {} });
      setProbe(save ? result.probe : result);
      if (save) { setNote('Saved'); await onSaved(); }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const pywake = adapter.id === 'pywake';
  const state = !probe ? ['muted', 'Not configured'] : probe.available && probe.compatible ? ['ok', `${probe.version || 'detected'} · compatible`] : ['warn', probe.available ? 'Incompatible' : 'Unavailable'];
  return <section aria-label={adapter.name} className="flex flex-col gap-3 rounded-2xl border border-nv-edge bg-nv-panel p-5">
    <div className="flex items-center gap-2.5"><h3 className="m-0 text-[14px] font-semibold">{adapter.name}</h3>
      <span className="inline-flex items-center gap-1.5 rounded-full border border-nv-edge px-2.5 py-px text-[11.5px] text-nv-muted"><StatusDot tone={state[0]} />{state[1]}</span></div>
    <p className="m-0 text-xs text-nv-muted">{adapter.description}</p>
    <label className="flex flex-col gap-1 text-xs text-nv-muted">{pywake ? 'Python interpreter' : 'Executable'}
      <input aria-label={`${adapter.name} ${pywake ? 'interpreter' : 'executable'}`} className={fieldClass} value={executable} placeholder={pywake ? '/path/to/pywake-env/bin/python' : '/path/to/openfast'}
        onChange={(e) => { setExecutable(e.target.value); setProbe(null); setNote(''); }} /></label>
    {pywake && <p className="m-0 text-xs text-nv-muted">Use a separate environment with <code>py-wake==2.6.20</code> and keep the venv symlink in the path.</p>}
    {probe?.message && <pre className="m-0 max-h-24 overflow-auto whitespace-pre-wrap rounded-md border border-nv-line bg-nv-chrome p-2 font-mono text-[11.5px] text-nv-reference">{probe.message.trim().slice(-600)}</pre>}
    {error && <Notice tone="err" role="alert">{error}</Notice>}
    <div className="flex items-center gap-2">
      <Button variant="primary" disabled={busy || !executable.trim()} onClick={() => run(true)}>Detect and save</Button>
      <Button disabled={busy || !executable.trim()} onClick={() => run(false)}>Detect only</Button>
      {note && <span role="status" className="text-xs text-nv-ok-ink">{note}</span>}
    </div>
  </section>;
}

function Integrations({ onOpenLegacy }) {
  const [adapters, setAdapters] = useState([]);
  const [configs, setConfigs] = useState([]);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => setConfigs(await request('/v1/integrations')), []);
  useEffect(() => {
    Promise.all([request('/v1/adapters'), request('/v1/integrations')]).then(([a, c]) => { setAdapters(a); setConfigs(c); }).catch((e) => setError(e.message));
  }, []);
  // The newest saved configuration of an adapter is the one workflows use unless a block names another.
  const latest = (id) => [...configs].filter((c) => c.adapter_id === id).sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')))[0];
  return <>
    <header className="flex flex-col gap-0.5"><h2 className="m-0 text-lg font-semibold">Integrations</h2>
      <p className="m-0 text-[13px] text-nv-muted">External programs Nova runs for you. They are installed independently; paths stay on this computer and never travel with projects or archives.</p></header>
    {error && <Notice tone="err" role="alert">{error}</Notice>}
    {adapters.map((adapter) => <IntegrationCard key={adapter.id} adapter={adapter} saved={latest(adapter.id)} onSaved={refresh} />)}
    {!adapters.length && !error && <p className="m-0 text-xs text-nv-muted">No executable adapters are available.</p>}
    <section className="flex flex-col gap-2 rounded-2xl border border-nv-edge bg-nv-panel p-5"><h3 className="m-0 text-[14px] font-semibold">Cases and results</h3>
      <p className="m-0 text-xs text-nv-muted">Run OpenFAST cases from the <b>OpenFAST case</b> and <b>OpenFAST run</b> blocks in Workflow. Wind farm cases, OpenFAST output import and external archives are still in the earlier view.</p>
      <div><Button onClick={onOpenLegacy}>Open external cases and results</Button></div></section>
  </>;
}

function Shortcuts() {
  return <>
    <header className="flex flex-col gap-0.5"><h2 className="m-0 text-lg font-semibold">Shortcuts</h2><p className="m-0 text-[13px] text-nv-muted">Keys that work across Nova and inside Workflow.</p></header>
    {SHORTCUTS.map(([group, rows]) => <section key={group} aria-label={group} className="rounded-2xl border border-nv-edge bg-nv-panel px-5 py-3">
      <h3 className="m-0 pb-1 text-[11.5px] font-medium uppercase tracking-wide text-nv-muted">{group}</h3>
      {rows.map(([label, combo]) => <div key={label} className="flex items-center justify-between border-t border-nv-line py-2 text-[13px]"><span>{label}</span>
        <span className="flex gap-1">{combo.split(' ').map((k) => <Kbd key={k}>{k}</Kbd>)}</span></div>)}</section>)}
  </>;
}

export default function SettingsWorkspace({ initial = 'integrations', onOpenLegacy }) {
  const [section, setSection] = useState(initial);
  return <div className="flex min-h-0 min-w-0 flex-1 flex-col md:flex-row">
    <nav aria-label="Settings sections" className="flex shrink-0 gap-1 border-b border-nv-line p-3 md:w-[220px] md:flex-col md:border-b-0 md:border-r md:p-4">
      <h2 className="m-0 hidden px-2.5 pb-3 text-[15px] font-semibold md:block">Settings</h2>
      {sections.map(([id, label]) => <button key={id} type="button" aria-current={section === id ? 'page' : undefined} onClick={() => setSection(id)}
        className={`h-9 rounded-lg px-2.5 text-left text-[13.5px] ${section === id ? 'bg-nv-active text-nv-ink' : 'text-nv-reference hover:bg-nv-hover'}`}>{label}</button>)}
    </nav>
    <section aria-label={sections.find(([id]) => id === section)?.[1]} className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-auto px-6 py-6 lg:px-10">
      <div className="flex w-full max-w-[760px] flex-col gap-4">
        {section === 'integrations' ? <Integrations onOpenLegacy={onOpenLegacy} /> : <Shortcuts />}
      </div>
    </section>
  </div>;
}
