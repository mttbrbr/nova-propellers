import { X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { request } from '../backend.js';
import { formatValue, niceTicks } from '../lib/blade.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import LineChart from '../ui/LineChart.jsx';
import { Button, Notice, Section, Segmented, SelectField, StatusDot } from '../ui/controls.jsx';

// Compare runs from any project: overlay the curves they share, tabulate the key
// results against a baseline and list which inputs differ, so a difference can be
// attributed (or not) to a single cause.
const PALETTE = ['#FF8533', '#4CC9F0', '#B49CFB', '#46D19A', '#F2B544', '#E879A6'];
const SAVED = 'nova.comparisons';
const fmt = (value, digits = 4) => value == null || Number.isNaN(Number(value)) ? '—' : formatValue(Number(value), digits);
const readSaved = () => { try { return JSON.parse(window.localStorage.getItem(SAVED) || '[]'); } catch { return []; } };
const writeSaved = (list) => { try { window.localStorage.setItem(SAVED, JSON.stringify(list)); } catch { /* storage unavailable */ } };

const familyOf = (run) => run.simulation_kind === 'rotor' || run.result?.kind === 'rotor' ? run.result?.rotor_kind : run.result?.analyses?.length ? 'native' : null;
const familyName = { native: 'air propeller', propeller: 'air propeller (rotor engine)', marine: 'marine propeller', hawt: 'HAWT', vawt: 'VAWT' };
const turbine = (family) => family === 'hawt' || family === 'vawt';
const comparable = (run) => run.state === 'succeeded' && !run.study && !run.comparison && !run.optimization && !run.external_job && familyOf(run);
const modelOf = (run) => familyOf(run) === 'native' ? (run.result.analyses[0]?.model || '').toUpperCase()
  : run.result.analysis?.method === 'bemt' ? 'BEMT' : run.result.analysis?.method_label?.split(' (')[0] || 'BEMT';

function metricsOf(run) {
  const family = familyOf(run);
  if (family === 'native') {
    const p = run.result.analyses[0]?.performance || {};
    return { power: p.power_w, thrust: p.thrust_n, torque: p.torque_nm, figure: p.efficiency, figureLabel: 'FoM' };
  }
  const a = run.result.analysis, optimum = run.result.curve?.optimum;
  const p = a.performance, c = a.coefficients;
  return { power: p.power_w, thrust: p.thrust_n ?? p.streamwise_force_n, torque: p.torque_nm,
    figure: turbine(family) ? c.CP : (family === 'marine' ? a.marine?.open_water_efficiency : c.efficiency), figureLabel: turbine(family) ? 'Cp' : 'η',
    best: optimum?.value, bestAt: optimum?.[run.result.curve.variable], bestLabel: optimum ? `${optimum.quantity === 'CP' ? 'Cp' : 'η'} max` : null };
}

// Curves a run can contribute, as {x, y} points.
const QUANTITIES = [
  { id: 'cp', label: 'Cp – λ', xLabel: 'λ', applies: (f) => turbine(f), points: (run) => curve(run, 'CP') },
  { id: 'ct', label: 'CT – λ', xLabel: 'λ', applies: (f) => turbine(f), points: (run) => curve(run, 'CT') },
  { id: 'kt', label: 'KT – J', xLabel: 'J', applies: (f) => f === 'propeller' || f === 'marine', points: (run) => curve(run, 'KT') },
  { id: 'eta', label: 'η – J', xLabel: 'J', applies: (f) => f === 'propeller' || f === 'marine',
    points: (run) => curve(run, familyOf(run) === 'marine' ? 'open_water_efficiency' : 'efficiency') },
  { id: 'thrust', label: 'Thrust along the blade', xLabel: 'r/R', applies: (f) => f && f !== 'vawt',
    points: (run) => stations(run, familyOf(run) === 'native' ? 'd_thrust_n' : 'd_thrust_n_m') },
  { id: 'alpha', label: 'Angle of attack along the blade', xLabel: 'r/R', applies: (f) => f && f !== 'vawt', points: (run) => stations(run, 'alpha_deg') },
];
function curve(run, field) {
  const c = run.result.curve;
  return (c?.rows || []).filter((r) => r.state === 'succeeded' && r[field] != null).map((r) => ({ x: r[c.variable], y: r[field] })).sort((a, b) => a.x - b.x);
}
function stations(run, field) {
  const list = familyOf(run) === 'native' ? run.result.analyses[0]?.stations : run.result.analysis?.stations;
  return (list || []).filter((s) => s[field] != null).map((s) => ({ x: Number(s.r_over_R), y: Number(s[field]) }));
}

// Inputs flattened to comparable "path → value" pairs.
function inputsOf(run) {
  if (familyOf(run) !== 'native') {
    const out = {}; const spec = run.inputs?.spec || {};
    const walk = (value, path) => {
      if (value && typeof value === 'object' && !Array.isArray(value)) Object.entries(value).forEach(([k, v]) => walk(v, path ? `${path}.${k}` : k));
      else out[path] = Array.isArray(value) ? value.join(', ') : value;
    };
    walk({ type: familyName[spec.kind], ...spec, kind: undefined, curve: undefined }, '');
    Object.keys(out).forEach((key) => out[key] === undefined && delete out[key]);
    return out;
  }
  const i = run.inputs || {}, analysis = (run.workflow?.nodes || []).find((n) => n.type === 'analysis');
  return { type: 'air propeller', model: (analysis?.config?.model || run.result.analyses[0]?.model || '').toUpperCase(), diameter: i.diameter, blades: i.blades, rpm: i.rpm,
    airfoil: i.airfoil, 'geometry method': i.geometry_method, 'air density': run.conditions?.air_density_kg_m3, polars: run.polar_asset_id ? run.polar_asset_id.slice(0, 8) : 'none' };
}
const shown = (value) => typeof value === 'number' ? formatValue(value, 4) : value === undefined || value === null || value === '' ? '—' : String(value);

export default function ComparisonsWorkspace({ onOpenRun }) {
  const [projects, setProjects] = useState([]);
  const [items, setItems] = useState([]); // { run, projectName }
  const [baselineId, setBaselineId] = useState(null);
  const [pickProject, setPickProject] = useState('');
  const [projectRuns, setProjectRuns] = useState([]);
  const [quantity, setQuantity] = useState('');
  const [saved, setSaved] = useState(readSaved);
  const [saveName, setSaveName] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { request('/v2/project-index').then(setProjects).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    if (!pickProject) { setProjectRuns([]); return; }
    request(`/v2/projects/${pickProject}/runs`).then((runs) => setProjectRuns(runs.filter(comparable)
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))))).catch((e) => setError(e.message));
  }, [pickProject]);

  const projectName = (id) => projects.find((p) => p.id === id)?.name || 'Project';
  const add = (run) => {
    if (items.some((item) => item.run.id === run.id) || items.length >= PALETTE.length) return;
    setItems((list) => [...list, { run, projectName: projectName(run.project_id) }]);
    if (!baselineId) setBaselineId(run.id);
  };
  const remove = (id) => {
    const rest = items.filter((item) => item.run.id !== id);
    setItems(rest); if (baselineId === id) setBaselineId(rest[0]?.run.id || null);
  };
  const openSaved = async (entry) => {
    setError('');
    try {
      const byProject = {};
      for (const ref of entry.items) byProject[ref.projectId] ||= await request(`/v2/projects/${ref.projectId}/runs`);
      const loaded = entry.items.map((ref) => byProject[ref.projectId].find((run) => run.id === ref.runId)).filter(Boolean);
      setItems(loaded.map((run) => ({ run, projectName: projectName(run.project_id) })));
      setBaselineId(loaded.find((run) => run.id === entry.baselineId)?.id || loaded[0]?.id || null);
      if (loaded.length < entry.items.length) setError('Some runs of this comparison no longer exist.');
    } catch (e) { setError(e.message); }
  };
  const saveCurrent = () => {
    const name = saveName.trim() || `Comparison ${saved.length + 1}`;
    const next = [{ name, baselineId, items: items.map(({ run }) => ({ projectId: run.project_id, runId: run.id })) }, ...saved.filter((s) => s.name !== name)].slice(0, 20);
    setSaved(next); writeSaved(next); setSaveName('');
  };

  const colored = items.map((item, index) => ({ ...item, color: PALETTE[index], family: familyOf(item.run) }));
  const families = [...new Set(colored.map((item) => item.family))];
  const available = QUANTITIES.filter((q) => colored.some((item) => q.applies(item.family)));
  const active = available.find((q) => q.id === quantity) || available[0];
  const series = active ? colored.filter((item) => active.applies(item.family)).map((item) => ({ id: item.run.id, label: item.projectName, color: item.color,
    dashed: item.run.id !== baselineId, points: active.points(item.run) })).filter((s) => s.points.length > 1) : [];
  const xs = series.flatMap((s) => s.points.map((p) => p.x));
  const domain = xs.length ? [Math.min(...xs), Math.max(...xs)] : [0, 1];
  const ticks = niceTicks(domain[0], domain[1], 4).filter((t) => t >= domain[0] - 1e-9 && t <= domain[1] + 1e-9);
  const baseline = colored.find((item) => item.run.id === baselineId);
  const baseMetrics = baseline ? metricsOf(baseline.run) : null;
  const diffs = useMemo(() => {
    if (!baseline) return { rows: [], counts: {} };
    const base = inputsOf(baseline.run);
    const all = colored.map((item) => inputsOf(item.run));
    const keys = [...new Set(all.flatMap((entry) => Object.keys(entry)))].filter((key) => all.some((entry) => shown(entry[key]) !== shown(base[key])));
    const counts = Object.fromEntries(colored.map((item, index) => [item.run.id, keys.filter((key) => shown(all[index][key]) !== shown(base[key])).length]));
    return { rows: keys.slice(0, 24).map((key) => [key, all.map((entry) => shown(entry[key])), shown(base[key])]), counts, hidden: Math.max(0, keys.length - 24) };
    // Recompute when the selection or baseline changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, baselineId]);
  const ambiguous = colored.filter((item) => item.run.id !== baselineId && diffs.counts[item.run.id] > 1);

  return <StageLayout inputsLabel="Runs in the comparison" contentLabel="Comparison charts" sideLabel="What differs"
    inputs={<>
      <StageTitle title="Comparisons" detail="Runs from any project, open or saved. Only the quantities they share are overlaid." />
      <Section title={`Runs · ${items.length}`}>
        {colored.length ? colored.map((item) => <div key={item.run.id} className={`flex items-start gap-2.5 rounded-lg border p-2.5 ${item.run.id === baselineId ? 'border-nv-accent/70' : 'border-nv-edge'}`}>
          <span className="mt-2 h-0.5 w-5 shrink-0" style={{ background: item.color }} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-medium">{item.projectName} · {item.run.simulation_name}</div>
            <div className="text-xs text-nv-muted">{modelOf(item.run)} · {familyName[item.family]} · {new Date(item.run.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}</div>
            <div className="mt-1.5 flex gap-3 text-xs">
              {item.run.id === baselineId ? <span className="text-nv-accent">baseline</span>
                : <button type="button" className="text-nv-reference hover:text-nv-ink" onClick={() => setBaselineId(item.run.id)}>Set as baseline</button>}
              <button type="button" className="text-nv-reference hover:text-nv-ink" onClick={() => onOpenRun(item.run)}>Open in a tab</button>
            </div>
          </div>
          <button type="button" aria-label={`Remove ${item.projectName} ${item.run.simulation_name}`} className="text-nv-muted hover:text-nv-ink" onClick={() => remove(item.run.id)}><X size={14} aria-hidden="true" /></button>
        </div>) : <p className="m-0 text-[13px] text-nv-muted">Add runs from one or more projects to compare them.</p>}
      </Section>
      <Section title="Add a run">
        <SelectField label="Project" ariaLabel="Project to add runs from" value={pickProject} onChange={setPickProject}
          options={[['', projects.length ? 'Choose a project…' : 'No saved projects'], ...projects.map((p) => [p.id, p.name])]} />
        {pickProject && (projectRuns.length ? <div className="flex max-h-56 flex-col gap-1 overflow-auto">{projectRuns.map((run) => {
          const added = items.some((item) => item.run.id === run.id);
          return <button key={run.id} type="button" disabled={added || items.length >= PALETTE.length} onClick={() => add(run)}
            className="flex items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-[13px] hover:bg-nv-hover disabled:opacity-40">
            <span className="min-w-0 truncate">{run.simulation_name} · {modelOf(run)}</span>
            <span className="shrink-0 font-mono text-xs text-nv-muted">{added ? 'added' : new Date(run.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}</span>
          </button>;
        })}</div> : <p className="m-0 text-xs text-nv-muted">No completed runs in this project.</p>)}
      </Section>
      <Section title="Saved comparisons">
        <div className="flex gap-2"><input aria-label="Comparison name" placeholder="Name" value={saveName} onChange={(e) => setSaveName(e.target.value)}
          className="h-[34px] min-w-0 flex-1 rounded-md border border-nv-edge bg-nv-chrome px-2.5 text-[13px] focus:border-nv-accent focus:outline-none" />
          <Button disabled={items.length < 2} onClick={saveCurrent}>Save comparison</Button></div>
        {saved.map((entry) => <div key={entry.name} className="flex items-center justify-between gap-2 text-[13px]">
          <button type="button" className="truncate text-left text-nv-accent hover:text-nv-accent-soft" onClick={() => openSaved(entry)}>{entry.name} · {entry.items.length} runs</button>
          <button type="button" aria-label={`Delete comparison ${entry.name}`} className="text-nv-muted hover:text-nv-ink" onClick={() => { const next = saved.filter((s) => s !== entry); setSaved(next); writeSaved(next); }}><X size={14} aria-hidden="true" /></button>
        </div>)}
      </Section>
      {error && <Notice tone="err" role="alert">{error}</Notice>}
    </>}
    content={<>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="m-0 text-lg font-semibold">{active ? active.label : 'Comparison'}</h1>
          <p className="m-0 mt-1.5 text-[13px] text-nv-muted">{colored.length ? `${colored.length} runs · ${families.map((f) => familyName[f]).join(', ')} · baseline solid, others dashed` : 'No runs selected yet.'}</p></div>
        {available.length > 1 && <div className="max-w-full"><Segmented label="Quantity" size="sm" value={active.id} onChange={setQuantity} options={available.map((q) => [q.id, q.label])} /></div>}
      </div>
      {families.length > 1 && <Notice tone="info">Different rotor types: curves are drawn only for runs that have them; the table keeps the quantities they share.</Notice>}
      {series.length ? <LineChart title={active.label} series={series} legend height={320} xDomain={domain} xTicks={ticks.length > 1 ? ticks : domain}
        xLabel={active.xLabel} ariaLabel={`${active.label} for ${series.length} runs`} /> : colored.length > 0 && <p className="m-0 text-[13px] text-nv-muted">The selected runs have no curve for this quantity.</p>}
      {colored.length > 0 && <div className="overflow-x-auto"><table aria-label="Compared results" className="w-full text-left text-[13px] tabular-nums">
        <thead className="text-xs text-nv-muted"><tr>{['Run', 'Model', 'Power [W]', 'Thrust [N]', 'Torque [N·m]', 'Cp / η / FoM', 'Optimum', 'Δ power'].map((h) => <th key={h} className="px-2 py-2 font-normal">{h}</th>)}</tr></thead>
        <tbody>{colored.map((item) => {
          const m = metricsOf(item.run);
          const delta = baseMetrics?.power && item.run.id !== baselineId ? (m.power / baseMetrics.power - 1) * 100 : null;
          return <tr key={item.run.id} className="border-t border-nv-line">
            <td className="px-2 py-2"><span className="inline-flex items-center gap-2"><span className="h-0.5 w-4" style={{ background: item.color }} />{item.projectName} · {item.run.simulation_name}</span></td>
            <td className="px-2 py-2">{modelOf(item.run)}</td>
            <td className="px-2 py-2 font-mono">{fmt(m.power)}</td><td className="px-2 py-2 font-mono">{fmt(m.thrust)}</td><td className="px-2 py-2 font-mono">{fmt(m.torque)}</td>
            <td className="px-2 py-2 font-mono">{m.figureLabel} {fmt(m.figure, 3)}</td>
            <td className="px-2 py-2 font-mono">{m.bestLabel ? `${m.bestLabel} ${fmt(m.best, 3)} @ ${fmt(m.bestAt, 3)}` : '—'}</td>
            <td className={`px-2 py-2 font-mono ${delta == null ? 'text-nv-muted' : delta >= 0 ? 'text-nv-ok-ink' : 'text-nv-warn-ink'}`}>{item.run.id === baselineId ? 'baseline' : delta == null ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} %`}</td>
          </tr>;
        })}</tbody></table></div>}
    </>}
    side={<>
      <h2 className="m-0 text-[15px] font-semibold">What differs from the baseline</h2>
      {colored.length < 2 ? <p className="m-0 text-[13px] text-nv-muted">Add at least two runs.</p> : diffs.rows.length ? <div className="overflow-x-auto">
        <table aria-label="Input differences" className="w-full text-left text-[12.5px]">
          <thead className="text-xs text-nv-muted"><tr><th className="px-1.5 py-1.5 font-normal">Input</th>{colored.map((item) => <th key={item.run.id} className="px-1.5 py-1.5 font-normal">
            <span className="inline-block h-0.5 w-4 align-middle" style={{ background: item.color }} /></th>)}</tr></thead>
          <tbody>{diffs.rows.map(([key, values, base]) => <tr key={key} className="border-t border-nv-line">
            <td className="px-1.5 py-1.5 text-nv-reference">{key}</td>
            {values.map((value, index) => <td key={index} className={`px-1.5 py-1.5 font-mono ${value !== base ? 'text-nv-warn-ink' : ''}`}>{value}</td>)}
          </tr>)}</tbody>
        </table>
        {diffs.hidden > 0 && <p className="m-0 mt-2 text-xs text-nv-muted">{diffs.hidden} more differing inputs not shown.</p>}
      </div> : <p className="m-0 text-[13px] text-nv-muted">All compared inputs are identical; differences come only from the model.</p>}
      {ambiguous.map((item) => <div key={item.run.id} className="flex items-start gap-2 text-[13px] text-nv-warn-ink"><StatusDot tone="warn" className="mt-1.5" />
        <span>{item.projectName} · {item.run.simulation_name} differs in {diffs.counts[item.run.id]} inputs: its Δ cannot be attributed to a single cause.</span></div>)}
    </>} />;
}
