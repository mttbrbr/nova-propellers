import { Search, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { request } from '../backend.js';
import { formatValue, stationSeries } from '../lib/blade.js';
import { Button, Notice, Segmented } from '../ui/controls.jsx';
import LineChart, { useElementWidth } from '../ui/LineChart.jsx';
import { caseColors } from './SolverStudy.jsx';

const letters = ['A', 'B', 'C', 'D'];
const SAVED = 'nova.designComparisons';
// Only finished native single-run analyses can be compared as designs.
const comparable = (run) => run.state === 'succeeded' && run.result?.analyses?.length && !run.study && !run.comparison && !run.optimization && !run.external_job;

export function savedDesignComparisons() {
  try { return JSON.parse(window.localStorage.getItem(SAVED) || '[]'); } catch { return []; }
}
function storeDesignComparison(entry) {
  try { window.localStorage.setItem(SAVED, JSON.stringify([entry, ...savedDesignComparisons().filter((item) => item.id !== entry.id)].slice(0, 30))); } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event('nova:preferences'));
}

const perf = (analysis) => analysis?.performance || {};
const pct = (value, reference) => reference ? 100 * (value - reference) / Math.abs(reference) : null;
const signed = (value) => value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${formatValue(value, 3)} %`;

function Planform({ designs }) {
  const [box, width] = useElementWidth(480);
  const height = Math.round(width * 0.56);
  const tip = Math.max(...designs.map((d) => d.geometry?.diameter_m / 2 || 0), 1e-9);
  const maxChord = Math.max(...designs.flatMap((d) => (d.geometry?.stations || []).map((s) => s.chord_m)), 1e-9);
  const left = 30, right = width - 20, mid = height / 2;
  const sx = (radius) => left + radius / tip * (right - left);
  // Same scale on both axes, unless the chord would not fit vertically.
  const scale = Math.min((right - left) / tip, (height * 0.42) / maxChord);
  return <div ref={box}>
    <svg width={width} height={height} role="img" aria-label="Blade planforms overlaid at the same scale" className="block rounded-xl border border-nv-line bg-[#0A0C0F]">
      <line x1={left} x2={right} y1={mid} y2={mid} stroke="#2A303A" strokeDasharray="3 4" />
      {designs.map((design) => {
        const stations = design.geometry?.stations || [];
        if (!stations.length) return null;
        const leading = stations.map((s) => `${sx(s.radius_m)},${mid - s.chord_m * 0.35 * scale}`);
        const trailing = [...stations].reverse().map((s) => `${sx(s.radius_m)},${mid + s.chord_m * 0.65 * scale}`);
        return <polygon key={design.letter} points={[...leading, ...trailing].join(' ')} fill={`${design.color}14`} stroke={design.color} strokeWidth="1.8" strokeLinejoin="round" />;
      })}
      <circle cx={left} cy={mid} r={12} fill="#1C2027" stroke="#3A424E" />
      <text x={left} y={height - 8} className="fill-nv-muted font-mono text-[11px]">hub</text>
      <text x={right} y={height - 8} textAnchor="end" className="fill-nv-muted font-mono text-[11px]">tip · R {formatValue(tip * 1000)} mm</text>
    </svg>
  </div>;
}

export function DesignChecks({ designs }) {
  if (designs.length < 2) return <p className="m-0 text-[13px] text-nv-muted">Add at least two results to compare their planforms.</p>;
  const reference = perf(designs[0].analysis);
  return <>
    <section aria-labelledby="planform-title"><h2 id="planform-title" className="m-0 mb-3 text-[15px] font-semibold">Planform, to scale</h2><Planform designs={designs} /></section>
    <section aria-labelledby="design-spread"><h2 id="design-spread" className="m-0 mb-3.5 text-[15px] font-semibold">Thrust and power vs A</h2>
      <div className="flex flex-col gap-3.5">{designs.slice(1).map((design) => {
        const thrust = pct(perf(design.analysis).thrust_n, reference.thrust_n), power = pct(perf(design.analysis).power_w, reference.power_w);
        return <div key={design.letter}><div className="mb-1.5 flex justify-between text-[13px]"><span>{design.letter} · thrust / power</span><span className="font-mono">{signed(thrust)} / {signed(power)}</span></div>
          <div className="flex gap-1"><div className="h-2 rounded" style={{ width: `${Math.min(50, Math.abs(thrust ?? 0) / 2)}%`, background: design.color }} /><div className="h-2 rounded opacity-50" style={{ width: `${Math.min(50, Math.abs(power ?? 0) / 2)}%`, background: design.color }} /></div></div>;
      })}</div>
      <p className="m-0 mt-3.5 text-xs leading-relaxed text-nv-muted">Solid bar thrust, faded bar power; 100 % fills half the track.</p>
    </section>
  </>;
}

// Hook rather than component: the result list feeds the left column and the report the centre.
export default function useDesignStudy({ projectId, request: studyRequest, onOpenSource }) {
  const [runs, setRuns] = useState([]);
  const [index, setIndex] = useState([]);
  const [selected, setSelected] = useState([]);
  const [scope, setScope] = useState('project');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const [station, setStation] = useState(0.7);
  useEffect(() => {
    let valid = true;
    Promise.all([request('/v1/runs'), request('/v2/project-index')]).then(([allRuns, projects]) => {
      if (valid) { setRuns(allRuns.filter(comparable)); setIndex(projects); }
    }).catch((caught) => { if (valid) setError(caught.message); });
    return () => { valid = false; };
  }, []);
  // Requests from Library or history preselect results (latest run of each project, or exact runs).
  useEffect(() => {
    if (!studyRequest || !runs.length) return;
    if (studyRequest.runIds) setSelected(studyRequest.runIds.filter((id) => runs.some((run) => run.id === id)).slice(0, 4));
    if (studyRequest.projectIds) {
      setScope('all');
      setSelected(studyRequest.projectIds.map((id) => runs.find((run) => run.project_id === id)?.id).filter(Boolean).slice(0, 4));
    }
  }, [studyRequest, runs]);
  const names = useMemo(() => Object.fromEntries(index.map((row) => [row.id, row.name])), [index]);
  const runsById = useMemo(() => Object.fromEntries(runs.map((run) => [run.id, run])), [runs]);
  const designs = selected.map((id, position) => runsById[id] && ({ letter: letters[position], color: caseColors[position], run: runsById[id],
    analysis: runsById[id].result.analyses[0], geometry: runsById[id].result.geometry, project: names[runsById[id].project_id] || 'Unsaved project' })).filter(Boolean);
  const term = query.trim().toLowerCase();
  const candidates = runs.filter((run) => !selected.includes(run.id) && (scope === 'all' || run.project_id === projectId))
    .filter((run) => !term || [names[run.project_id], run.simulation_name, run.result.analyses[0].model, run.id].some((value) => value?.toLowerCase().includes(term)))
    .slice(0, 30);
  const reference = designs[0];
  const conditions = [
    ['Solver', (d) => (d.analysis.model || '').toUpperCase()],
    ['Rotation speed', (d) => `${formatValue(d.analysis.operating_point?.rpm, 5)} rpm`],
    ['Air density', (d) => formatValue(d.analysis.operating_point?.air_density_kg_m3)],
    ['Polars', (d) => d.run.polar_asset?.filename || (d.analysis.model === 'bemt' ? 'imported' : 'analytic sections')],
  ];
  const mismatches = reference ? designs.slice(1).flatMap((design) => conditions.filter(([, get]) => get(design) !== get(reference)).map(([label]) => ({ design, label }))) : [];
  const exportCsv = () => {
    const header = ['design', 'project', 'simulation', 'run_id', 'model', 'rpm', 'thrust_n', 'torque_nm', 'power_w', 'figure_of_merit', 'diameter_m', 'blades'];
    const lines = designs.map((d) => [d.letter, d.project, d.run.simulation_name || '', d.run.id, d.analysis.model, d.analysis.operating_point?.rpm, perf(d.analysis).thrust_n, perf(d.analysis).torque_nm, perf(d.analysis).power_w, perf(d.analysis).efficiency, d.geometry?.diameter_m, d.geometry?.blades]
      .map((value) => `"${String(value ?? '').replaceAll('"', '""')}"`).join(','));
    const url = URL.createObjectURL(new Blob([`${header.join(',')}\n${lines.join('\n')}\n`], { type: 'text/csv' }));
    const link = document.createElement('a'); link.href = url; link.download = 'design-comparison.csv'; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const save = () => {
    const name = designs.map((d) => d.project === designs[0].project ? d.run.simulation_name : d.project).join(' vs ');
    storeDesignComparison({ id: selected.join('|'), name, runIds: selected, created_at: new Date().toISOString(), projectIds: [...new Set(designs.map((d) => d.run.project_id))] });
    setSaved(`Saved “${name}” in the history on this computer.`);
  };

  return {
    designs,
    picker: <section aria-labelledby="design-add" className="flex flex-col gap-2.5">
      <h2 id="design-add" className="m-0 text-[13px] font-semibold">Add a result <span className="font-normal text-nv-muted">· {designs.length}/4</span></h2>
      <Segmented label="Search scope" value={scope} onChange={setScope} options={[['project', 'This project', !projectId], ['all', 'All projects']]} />
      <label className="flex h-[34px] items-center gap-2 rounded-md border border-nv-edge bg-nv-chrome px-2.5 focus-within:border-nv-accent">
        <Search size={15} className="text-nv-muted" aria-hidden="true" />
        <input aria-label="Search results" placeholder="Project, simulation or solver…" value={query} onChange={(event) => setQuery(event.target.value)} className="h-8 min-w-0 flex-1 bg-transparent text-[13px] outline-none" />
      </label>
      <div className="-mx-2.5 flex max-h-[360px] flex-col gap-0.5 overflow-y-auto">
        {candidates.map((run) => <button key={run.id} type="button" disabled={selected.length >= 4} aria-label={`Add run ${run.id.slice(0, 8)}`}
          onClick={() => setSelected((list) => [...list, run.id])} className="rounded-lg px-2.5 py-2 text-left hover:bg-nv-raised disabled:opacity-40">
          <span className="block truncate text-[13px]">{names[run.project_id] || 'Unsaved project'} · {run.simulation_name || 'Unassigned'}</span>
          <span className="block truncate text-xs text-nv-muted">{(run.result.analyses[0].model || '').toUpperCase()} · {formatValue(perf(run.result.analyses[0]).thrust_n, 4)} N · {formatValue(run.inputs?.rpm, 5)} rpm · {run.id.slice(0, 8)}</span>
        </button>)}
        {!candidates.length && <p className="m-0 px-2.5 text-[13px] text-nv-muted">{runs.length ? 'No finished result matches.' : 'No finished results yet. Run a simulation first.'}</p>}
      </div>
      <p className="m-0 text-xs text-nv-muted">Only finished single runs appear. Up to 4 results.</p>
    </section>,
    main: <>
      {error && <Notice tone="err" role="alert">{error}</Notice>}
      {!designs.length && <p className="m-0 text-[13px] text-nv-muted">Add two to four results from the list on the left. They can come from this project or from any other saved project.</p>}
      {designs.length > 0 && <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">{designs.map((design) => <div key={design.letter} className="grid min-w-0 grid-cols-[26px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-[10px] border px-3.5 py-3" style={{ borderColor: design.color }}>
        <span className="grid h-6 w-6 place-items-center rounded-md text-xs font-semibold text-nv-accent-ink" style={{ background: design.color }}>{design.letter}</span>
        <span className="min-w-0"><span className="block truncate">{design.project}</span><span className="block truncate text-xs text-nv-muted">{design.run.simulation_name || 'Unassigned'} · {(design.analysis.model || '').toUpperCase()} r{design.run.simulation_revision || '—'}{design.letter === 'A' ? ' · reference' : ''}</span></span>
        <button type="button" aria-label={`Remove ${design.letter}`} className="text-nv-muted hover:text-nv-ink" onClick={() => setSelected((list) => list.filter((id) => id !== design.run.id))}><X size={15} aria-hidden="true" /></button>
      </div>)}</div>}
      {designs.length > 1 && <>
        <section aria-labelledby="design-conditions" className="flex flex-col gap-3">
          <h2 id="design-conditions" className="m-0 text-[15px] font-semibold">Are they comparable?</h2>
          <div className="overflow-x-auto"><table aria-label="Design conditions" className="w-full border-collapse text-[13px]">
            <thead><tr className="text-xs text-nv-muted"><th scope="col" className="pb-2.5 text-left font-medium">Condition</th>{designs.map((d) => <th key={d.letter} scope="col" className="px-3 pb-2.5 text-right font-medium">{d.letter}</th>)}</tr></thead>
            <tbody className="font-mono tabular">{conditions.map(([label, get]) => <tr key={label} className="border-t border-nv-line"><td className="py-2.5 font-sans">{label}</td>
              {designs.map((d) => <td key={d.letter} className={`px-3 text-right ${get(d) !== get(reference) ? 'text-nv-warn-ink' : ''}`}>{get(d)}</td>)}</tr>)}</tbody>
          </table></div>
          {[...new Set(mismatches.map((item) => item.design.letter))].map((letter) => {
            const design = designs.find((d) => d.letter === letter);
            const what = mismatches.filter((item) => item.design.letter === letter).map((item) => item.label.toLowerCase());
            return <Notice key={letter} action={<Button className="!h-7 !px-2.5" onClick={() => onOpenSource(design.run)}>Open {letter} to re-run</Button>}>
              {letter} differs from A in {what.join(', ')}, so its numbers are not like-for-like.</Notice>;
          })}
        </section>
        <section aria-labelledby="design-performance" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-3"><h2 id="design-performance" className="m-0 text-[15px] font-semibold">Performance <span className="font-normal text-nv-muted">· difference from A</span></h2>
            <span className="flex gap-4"><button type="button" className="text-[13px] text-nv-accent hover:text-nv-accent-soft" onClick={save}>Save comparison</button><button type="button" className="text-[13px] text-nv-accent hover:text-nv-accent-soft" onClick={exportCsv}>Export comparison CSV</button></span></div>
          {saved && <p role="status" className="m-0 text-[13px] text-nv-ok-ink">{saved}</p>}
          <div className="overflow-x-auto"><table aria-label="Design comparison results" className="w-full min-w-[760px] border-collapse text-[13px]">
            <thead><tr className="text-xs text-nv-muted">{['Design', 'Thrust [N]', 'Δ', 'Power [W]', 'Δ', 'FoM', 'Ø [mm]', 'Blades'].map((title, position) => <th key={position} scope="col" className={`pb-2.5 font-medium ${position ? 'px-3 text-right' : 'text-left'}`}>{title}</th>)}</tr></thead>
            <tbody className="whitespace-nowrap font-mono tabular">{designs.map((d, position) => <tr key={d.letter} className="border-t border-nv-line">
              <td className="py-2.5 font-sans"><span className="inline-flex items-center gap-2"><span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ background: d.color }} />{d.letter} · {d.project}</span>{mismatches.some((item) => item.design === d) && <span className="ml-1.5 text-nv-warn-ink" title="Not like-for-like">⚠</span>}</td>
              <td className="px-3 text-right">{formatValue(perf(d.analysis).thrust_n, 4)}</td><td className="px-3 text-right text-nv-reference">{position ? signed(pct(perf(d.analysis).thrust_n, perf(reference.analysis).thrust_n)) : '—'}</td>
              <td className="px-3 text-right">{formatValue(perf(d.analysis).power_w, 4)}</td><td className="px-3 text-right text-nv-reference">{position ? signed(pct(perf(d.analysis).power_w, perf(reference.analysis).power_w)) : '—'}</td>
              <td className="px-3 text-right">{formatValue(perf(d.analysis).efficiency, 3)}</td><td className="px-3 text-right">{formatValue((d.geometry?.diameter_m || 0) * 1000, 4)}</td><td className="px-3 text-right">{d.geometry?.blades ?? '—'}</td>
            </tr>)}</tbody>
          </table></div>
        </section>
        <section aria-labelledby="design-along" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-baseline justify-between gap-3"><h2 id="design-along" className="m-0 text-[15px] font-semibold">Geometry and loading along the blade</h2>
            <span className="flex gap-4 text-xs text-nv-muted">{designs.map((d) => <span key={d.letter} className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3.5" style={{ background: d.color }} />{d.letter}</span>)}</span></div>
          <div className="grid gap-x-8 gap-y-7 md:grid-cols-2 2xl:grid-cols-3">
            <LineChart title="Chord" unit="mm" height={190} selection={station} onSelect={setStation} series={designs.map((d) => ({ id: d.letter, color: d.color, points: stationSeries(d.geometry?.stations, 'chord_m', 1000) }))} />
            <LineChart title="Twist" unit="°" height={190} selection={station} onSelect={setStation} series={designs.map((d) => ({ id: d.letter, color: d.color, points: stationSeries(d.geometry?.stations, 'twist_deg') }))} />
            <LineChart title="Local thrust" unit="N" height={190} selection={station} onSelect={setStation} series={designs.map((d) => ({ id: d.letter, color: d.color, points: stationSeries(d.analysis?.stations, 'd_thrust_n') }))} />
          </div>
          <p className="m-0 text-xs text-nv-muted">Span 0 is each blade's root section and 1 its tip; the planform on the right shows the real sizes.</p>
        </section>
      </>}
    </>,
  };
}
