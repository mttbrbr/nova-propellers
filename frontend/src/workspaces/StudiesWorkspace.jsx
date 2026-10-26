import { useEffect, useRef, useState } from 'react';
import { download, request } from '../backend.js';
import SimulationComparison from './SimulationComparison.jsx';
import StudyGrid from './StudyGrid.jsx';

const button = 'rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs disabled:opacity-40';
const field = 'rounded border border-zinc-700 bg-zinc-950 p-2 text-sm';
const active = (run) => ['queued', 'running', 'cancelling'].includes(run?.state);
const number = (value) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumSignificantDigits: 6 });

function PerformanceTable({ rows, onInspect, label = 'Performance results' }) {
  return <div className="overflow-x-auto"><table aria-label={label} className="w-full text-left text-xs"><thead className="text-zinc-500"><tr>
    {['Case/value', 'State/model', 'Polar data', 'RPM', 'Airfoil', 'Density [kg/m³]', 'Viscosity [Pa·s]', 'Diameter [m]', 'Thrust [N]', 'Torque [N·m]', 'Power [W]', 'Figure of merit', 'Result'].map((title) => <th key={title} className="p-2 font-normal">{title}</th>)}
  </tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.run_id}-${row.case_index}-${row.node_id}-${index}`} className="border-t border-zinc-800">
    <td className="p-2">{row.value == null ? row.run_id.slice(0, 8) : <>{row.parameter}: {number(row.value)} [{row.parameter_units}]{row.secondary_parameter && <span className="mt-1 block">{row.secondary_parameter}: {number(row.secondary_value)} [{row.secondary_units}]</span>}</>}</td>
    <td className="p-2">{row.state === 'succeeded' ? `${row.model} · ${row.fidelity}${row.run_state === 'cancelled' ? ' · cancelled study' : ''}` : row.state}{row.error && <div className="mt-1 max-w-xs text-red-400">{row.error}</div>}</td>
    <td className="p-2">{row.polar_data || '—'}</td><td className="p-2 tabular-nums">{number(row.rpm)}</td><td className="p-2">{row.airfoil || '—'}</td>
    {[row.density_kg_m3, row.viscosity_pa_s, row.diameter_m, row.thrust_n, row.torque_nm, row.power_w, row.figure_of_merit].map((v, i) => <td key={i} className="p-2 tabular-nums">{number(v)}</td>)}
    <td className="p-2">{row.state === 'succeeded' && row.case_index != null && onInspect && <button className={button} onClick={() => onInspect(row)}>Inspect</button>}</td>
  </tr>)}</tbody></table></div>;
}

function SweepPlot({ rows, parameter, units }) {
  const available = rows.filter((r) => r.state === 'succeeded' && r.value != null);
  const ids = [...new Set(available.map((r) => r.node_id || r.model))];
  const [selection, setSelection] = useState('');
  const selected = ids.includes(selection) ? selection : ids[0];
  const points = available.filter((r) => (r.node_id || r.model) === selected).sort((a, b) => a.value - b.value);
  if (points.length < 2) return null;
  const xmin = points[0].value, xmax = points.at(-1).value;
  const ymin = Math.min(...points.map((p) => p.thrust_n)), ymax = Math.max(...points.map((p) => p.thrust_n));
  const coordinates = points.map((p) => `${30 + (p.value - xmin) / Math.max(xmax - xmin, 1e-12) * 540},${170 - (p.thrust_n - ymin) / Math.max(ymax - ymin, 1e-12) * 140}`).join(' ');
  return <div className="rounded border border-zinc-800 p-4">
    <div className="flex justify-between text-xs text-zinc-400"><span>Thrust [N]: {number(ymin)}–{number(ymax)}</span><select aria-label="Plot analysis node" className={field} value={selected} onChange={(e) => setSelection(e.target.value)}>{ids.map((id) => <option key={id}>{id}</option>)}</select></div>
    <svg viewBox="0 0 600 200" role="img" aria-label="Thrust versus sweep parameter" className="mt-3 max-h-64 w-full"><path d="M30 20V175H575" fill="none" stroke="#52525b"/><polyline points={coordinates} fill="none" stroke="#e4e4e7" strokeWidth="2"/></svg>
    <p className="text-xs text-zinc-500">{parameter} [{units}]: {number(xmin)}–{number(xmax)}. Failed cases are excluded from the curve and retained in the table.</p>
  </div>;
}

export default function StudiesWorkspace({ projectId, projectControls, onInspect, onInverseDesign, onExecutionChange, activeStudy, configurationBusy = false, selectedRun = null }) {
  const [parameter, setParameter] = useState('rpm');
  const [values, setValues] = useState('3500, 4250, 5000');
  const [twoAxes, setTwoAxes] = useState(false);
  const [secondaryParameter, setSecondaryParameter] = useState('air_density_kg_m3');
  const [secondaryValues, setSecondaryValues] = useState('1.1, 1.225');
  const [axes, setAxes] = useState([]);
  const [parameters, setParameters] = useState({});
  const [runs, setRuns] = useState([]);
  const [current, setCurrent] = useState(activeStudy?.project_id === projectId ? activeStudy : null);
  const [rows, setRows] = useState([]);
  const [selectedRuns, setSelectedRuns] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const projectScope = useRef(projectId);
  projectScope.current = projectId;

  useEffect(() => { if (current) onExecutionChange?.(current); }, [current, onExecutionChange]);

  useEffect(() => {
    if (selectedRun?.project_id === projectId && (selectedRun.study || selectedRun.comparison)) setCurrent(selectedRun);
  }, [selectedRun, projectId]);
  useEffect(() => {
    if (activeStudy?.project_id !== projectId) return;
    setCurrent((previous) => previous?.id === activeStudy.id ? activeStudy : !previous && !selectedRun ? activeStudy : previous);
  }, [activeStudy, projectId, selectedRun]);

  const refresh = async () => {
    const scope = projectScope.current;
    const all = await request('/v1/runs');
    if (scope === projectScope.current) setRuns(all.filter((r) => !r.external_job && !r.optimization && r.project_id === scope));
  };
  useEffect(() => {
    request('/v1/studies/parameters').then(setParameters).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    let valid = true;
    setCurrent((previous) => previous?.project_id === projectId ? previous : null); setRows([]); setComparison(null); setSelectedRuns([]);
    request('/v1/runs').then((all) => { if (valid) setRuns(all.filter((r) => !r.external_job && !r.optimization && r.project_id === projectId)); }).catch((e) => { if (valid) setError(e.message); });
    return () => { valid = false; };
  }, [projectId]);
  useEffect(() => {
    if (!current || active(current) || current.project_id !== projectScope.current) return;
    refresh().catch((caught) => setError(caught.message));
    projectControls.current.refresh().catch((caught) => setError(caught.message));
    // The application monitors active jobs; this refreshes persisted lists at their terminal checkpoint.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, current?.state]);
  useEffect(() => {
    if (!current?.study || current.project_id !== projectScope.current) { setRows([]); setAxes([]); return undefined; }
    let valid = true;
    request(`/v1/runs/${current.id}/study.rows`).then((document) => {
      if (!valid || current.project_id !== projectScope.current) return;
      // Do not offer inspection for a checkpoint newer than the selected immutable case snapshots.
      setRows(document.rows.filter((row) => current.result?.cases?.some((sample) => sample.index === row.case_index)));
      setAxes(document.axes);
    }).catch((caught) => { if (valid) setError(caught.message); });
    return () => { valid = false; };
  }, [current]);

  const act = async (action) => { setError(''); setBusy(true); try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  const start = () => act(async () => {
    const parse = (text) => {
      const parsed = text.split(',').map((v) => v.trim());
      if (parsed.some((v) => !v || !Number.isFinite(Number(v)))) throw new Error('Enter comma-separated numeric values');
      return parsed.map(Number);
    };
    const definition = { parameter, values: parse(values) };
    if (twoAxes) {
      if (parameter === secondaryParameter) throw new Error('Select different parameters for the two axes');
      definition.secondary = { parameter: secondaryParameter, values: parse(secondaryValues) };
      if (definition.values.length * definition.secondary.values.length > 32) throw new Error('The Cartesian grid must contain at most 32 cases');
    }
    const run = await projectControls.current.study(definition);
    onExecutionChange?.(run);
    if (run.project_id !== projectScope.current) return;
    setCurrent(run); setComparison(null);
  });
  const inspect = (row) => {
    const selectedRun = current?.id === row.run_id ? current : runs.find((r) => r.id === row.run_id);
    const c = selectedRun?.result?.cases[row.case_index];
    if (c?.state === 'succeeded') onInspect(c.result, c.inputs, selectedRun.id, c.index, { ...selectedRun, inputs: c.inputs, conditions: c.conditions, study_case: { parameter: selectedRun.study.parameter, value: c.value, units: selectedRun.result.units, ...(selectedRun.study.secondary ? { secondary_parameter: c.secondary_parameter, secondary_value: c.secondary_value, secondary_units: c.secondary_units } : {}) } });
  };

  return <section className="min-w-0 space-y-5 overflow-auto p-6 lg:p-8">
    <h2 className="text-xl">Studies</h2>
    <SimulationComparison projectId={projectId} current={current} activeJob={activeStudy} configurationBusy={configurationBusy} onInspect={onInspect}
      onStart={(run) => { onExecutionChange?.(run); if (run.project_id === projectScope.current) { setCurrent(run); setComparison(null); } }} />
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <h3 className="mb-3 text-sm">Parameter sweep</h3>
      <p className="mb-4 text-xs text-zinc-400">Run the current workflow at 2–32 distinct values or over a two-axis Cartesian grid with at most 32 cases. Up to 128 analysis evaluations are allowed. Inputs and selected data are frozen for the study.</p>
      <div className="flex flex-wrap gap-3"><label className="text-xs text-zinc-400">Parameter<select aria-label="Sweep parameter" className={`${field} mt-1 block`} value={parameter} onChange={(e) => setParameter(e.target.value)}>{Object.entries(parameters).map(([id, p]) => <option key={id} value={id}>{p.label} [{p.units}]</option>)}</select></label>
        <label className="flex-1 text-xs text-zinc-400">Values<input aria-label="Sweep values" className={`${field} mt-1 block w-full`} value={values} onChange={(e) => setValues(e.target.value)} /></label></div>
      <label className="mt-4 flex items-center gap-2 text-xs text-zinc-400"><input aria-label="Use second sweep axis" type="checkbox" checked={twoAxes} onChange={(e) => setTwoAxes(e.target.checked)} />Add a second parameter axis</label>
      {twoAxes && <div className="mt-3 space-y-3 rounded border border-zinc-800 p-3"><div className="flex flex-wrap gap-3"><label className="text-xs text-zinc-400">Second parameter<select aria-label="Second sweep parameter" className={`${field} mt-1 block`} value={secondaryParameter} onChange={(e) => setSecondaryParameter(e.target.value)}>{Object.entries(parameters).map(([id, p]) => <option key={id} value={id} disabled={id === parameter}>{p.label} [{p.units}]</option>)}</select></label><label className="min-w-0 flex-1 text-xs text-zinc-400">Second axis values<input aria-label="Second sweep values" className={`${field} mt-1 block w-full`} value={secondaryValues} onChange={(e) => setSecondaryValues(e.target.value)} /></label></div><p className="text-xs text-zinc-500">Every primary value is evaluated with every secondary value. Use different parameters; the complete grid is limited to 32 cases and 128 analysis evaluations. Results use a discrete cell grid for each analysis node.</p>{parameter === secondaryParameter && <p className="text-xs text-amber-400">Choose different parameters for the two axes.</p>}</div>}
      {(parameter === 'diameter' || (twoAxes && secondaryParameter === 'diameter')) && <p className="mt-3 text-xs text-amber-400">When diameter varies, chord and twist inputs are held fixed; geometry limits still apply. Use manual sizing so the values are not overwritten.</p>}
      <button className={`${button} mt-4`} disabled={configurationBusy || busy || active(current) || active(activeStudy) || (twoAxes && parameter === secondaryParameter)} onClick={start}>Run sweep</button>
      <button className={`${button} ml-2 mt-4`} onClick={onInverseDesign}>Inverse design</button>
    </div>
    {current?.study && <div className="rounded border border-zinc-800 p-4">
      <p className="mb-3 text-xs text-zinc-400">Study from {current.simulation_name || 'unassigned configuration'}{current.simulation_revision ? ` · r${current.simulation_revision}` : ''} · {current.inputs.rpm} rpm baseline · {current.workflow.nodes.filter((n) => n.type === 'analysis').map((n) => (n.config.model || 'bemt').toUpperCase()).join(' + ')}</p>
      <div className="flex flex-wrap justify-between gap-2 text-sm"><span>{current.result?.study_status || current.state} · {Math.round(current.progress * 100)}%</span>
        {current.result?.cases.length > 0 && <button className={button} onClick={() => act(() => download(`/v1/runs/${current.id}/study.csv`, 'study.csv'))}>Export study CSV</button>}</div>
      {current.result && <p className="mt-2 text-xs text-zinc-400">{current.result.completed_cases}/{current.result.total_cases} completed · {current.result.failed_cases} failed</p>}
      {current.error && <p className="mt-2 text-xs text-red-400">{current.error}</p>}
      <details className="mt-3"><summary className="cursor-pointer text-xs text-zinc-500">Study logs</summary><pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-[10px] text-zinc-500">{current.logs.join('\n')}</pre></details>
    </div>}
    {current?.study?.secondary && axes.length === 2
      ? <StudyGrid run={current} rows={rows} primary={axes[0]} secondary={axes[1]} onInspect={inspect} />
      : !current?.study?.secondary && <SweepPlot rows={rows} parameter={axes[0]?.parameter || current?.result?.definition?.parameter || parameter} units={axes[0]?.units || current?.result?.units || parameters[parameter]?.units} />}
    {rows.length > 0 && <PerformanceTable rows={rows} onInspect={inspect} label="Sweep results" />}
    <div className="rounded border border-zinc-800 p-4"><h3 className="mb-3 text-sm">Stored runs and comparisons</h3>
      <div className="max-h-56 space-y-2 overflow-auto">{runs.map((r) => <div key={r.id} className="flex items-center gap-3 text-xs">
        <input aria-label={`Compare run ${r.id.slice(0, 8)}`} type="checkbox" disabled={Boolean(r.comparison)} checked={selectedRuns.includes(r.id)} onChange={(e) => {
          const checked = e.target.checked;
          setSelectedRuns((ids) => checked ? [...new Set([...ids, r.id])] : ids.filter((id) => id !== r.id));
        }} />
        <button onClick={() => { if (r.study || r.comparison) setCurrent(r); }}>{r.comparison ? `Solver comparison: ${r.comparison.name}` : r.study ? `Sweep ${r.study.parameter}${r.study.secondary ? ` × ${r.study.secondary.parameter}` : ''}` : 'Analysis'} · {r.state} · {r.created_at}</button>
      </div>)}</div>
      <button className={`${button} mt-3`} disabled={busy || selectedRuns.length < 2 || selectedRuns.length > 8} onClick={() => act(async () => setComparison(await request('/v1/runs/compare', { run_ids: selectedRuns })))}>Compare selected runs</button>
      <p className="mt-3 text-xs text-zinc-500">Comparisons retain each model’s fidelity and operating conditions. Only static rotor results with compatible native units are combined.</p>
      {comparison && <PerformanceTable rows={comparison.rows} onInspect={inspect} label="Stored run comparison results" />}
    </div>
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
  </section>;
}
