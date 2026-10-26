import { useEffect, useRef, useState } from 'react';
import { download, request } from '../backend.js';

const button = 'rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs disabled:opacity-40';
const field = 'mt-1 block w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm';
const active = (run) => ['queued', 'running', 'cancelling'].includes(run?.state);
const number = (value) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumSignificantDigits: 6 });
const models = (simulation) => (simulation.workflow?.nodes || []).filter((n) => n.type === 'analysis').map((n) => (n.config.model || 'bemt').toUpperCase()).join(' + ');
const difference = (row, metric) => {
  const value = row.baseline_differences_pct?.[metric];
  if (value != null) return `${number(value)}%`;
  const reason = row.baseline_difference_reasons?.[metric];
  return reason === 'zero_baseline' ? 'Undefined: zero reference' : reason === 'baseline_failed' ? 'Unavailable: reference failed' : reason === 'case_failed' ? 'Unavailable: case failed' : '—';
};

export default function SimulationComparison({ projectId, current, onStart, onInspect, activeJob, configurationBusy = false }) {
  const [simulations, setSimulations] = useState([]);
  const [selected, setSelected] = useState([]);
  const [reference, setReference] = useState('');
  const [name, setName] = useState('Solver comparison');
  const [validation, setValidation] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const projectScope = useRef(projectId);
  projectScope.current = projectId;
  const selectedSimulations = selected.map((id) => simulations.find((item) => item.id === id)).filter(Boolean);
  const baseline = selected.includes(reference) ? reference : selected[0];
  const ordered = [baseline, ...selected.filter((id) => id !== baseline)].filter(Boolean);
  const body = { name, simulations: ordered.map((id) => { const item = simulations.find((s) => s.id === id); return { id, expected_revision: item.revision }; }) };
  const selectionStamp = JSON.stringify(body);
  const running = active(current) || active(activeJob);
  useEffect(() => { generation.current += 1; setValidation(null); }, [selectionStamp]);
  useEffect(() => {
    const epoch = ++generation.current;
    setSimulations([]); setSelected([]); setReference(''); setValidation(null); setError('');
    if (!projectId) return undefined;
    let valid = true;
    request(`/v1/projects/${projectId}/simulations`).then((items) => { if (valid && projectId === projectScope.current) setSimulations(items); }).catch((caught) => { if (valid) setError(caught.message); });
    return () => { valid = false; if (generation.current === epoch) generation.current += 1; };
  }, [projectId]);
  const act = async (action) => { setBusy(true); setError(''); try { await action(); } catch (caught) { setError(caught.message); } finally { setBusy(false); } };
  const refresh = () => act(async () => {
    const scope = projectId;
    const items = await request(`/v1/projects/${scope}/simulations`);
    if (scope !== projectScope.current) return;
    setSimulations(items); setSelected((ids) => ids.filter((id) => items.some((s) => s.id === id))); setValidation(null);
  });
  const validate = () => act(async () => {
    const epoch = generation.current; setValidation(null);
    const result = await request(`/v1/projects/${projectId}/comparisons/validate`, body);
    if (epoch === generation.current) setValidation(result);
  });
  const submit = () => act(async () => {
    const run = await request(`/v1/projects/${projectId}/comparisons`, body);
    onStart(run);
  });
  const inspect = (row) => {
    const sample = current.result.cases.find((c) => c.index === row.case_index);
    if (sample?.state !== 'succeeded') return;
    const snapshot = sample.snapshot || current.comparison.simulations.find((s) => s.id === sample.simulation_id);
    onInspect(sample.result, snapshot.inputs, current.id, sample.index, {
      ...current, simulation_id: sample.simulation_id, simulation_name: sample.simulation_name,
      simulation_revision: sample.simulation_revision, geometry_id: snapshot.geometry_id,
      geometry_revision: snapshot.geometry_revision, inputs: snapshot.inputs, workflow: snapshot.workflow,
      conditions: snapshot.conditions, polar_asset_id: snapshot.polar_asset_id,
    });
  };
  const comparisonRun = current?.comparison ? current : null;
  return <section aria-label="Guided solver comparison" className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
    <div><h3 className="text-sm">Compare saved simulations</h3><p className="mt-2 text-xs leading-5 text-zinc-400">Select 2–8 saved configurations to evaluate the same geometry and operating conditions with different native models. Saved revisions are frozen for the batch; current unsaved edits are excluded. Compatible manual guided workflows with one analysis are supported.</p></div>
    {!projectId ? <p className="text-xs text-zinc-400">Save or open a project to compare its simulations.</p> : <>
      <div className="flex flex-wrap gap-3"><label className="min-w-0 flex-1 text-xs text-zinc-400">Comparison name<input aria-label="Comparison name" className={field} value={name} onChange={(e) => setName(e.target.value)} /></label><button className={`${button} self-end`} disabled={busy} onClick={refresh}>Refresh saved configurations</button></div>
      <div className="max-h-72 overflow-auto"><table className="w-full text-left text-xs"><thead className="text-zinc-500"><tr>{['Select', 'Saved configuration', 'Models', 'Geometry revision', 'RPM', 'Airfoil', 'Density [kg/m³]', 'Viscosity [Pa·s]'].map((title) => <th key={title} className="p-2 font-normal">{title}</th>)}</tr></thead><tbody>{simulations.map((item) => <tr key={item.id} className="border-t border-zinc-800">
        <td className="p-2"><input type="checkbox" aria-label={`Compare simulation ${item.name}`} checked={selected.includes(item.id)} disabled={busy || running || (!selected.includes(item.id) && selected.length >= 8)} onChange={(e) => { const checked = e.target.checked; setSelected((ids) => checked ? [...new Set([...ids, item.id])] : ids.filter((id) => id !== item.id)); }} /></td>
        <td className="p-2">{item.name} · r{item.revision}<span className="mt-1 block text-[10px] text-zinc-500">{item.id.slice(0, 8)}</span></td><td className="p-2">{models(item) || 'No analysis'}</td>
        <td className="p-2">{item.geometry_id ? `${item.geometry_id.slice(0, 8)} · r${item.geometry_revision}` : 'Unassigned'}</td><td className="p-2">{number(item.inputs.rpm)}</td><td className="p-2">{item.inputs.airfoil}</td><td className="p-2">{number(item.conditions.air_density_kg_m3)}</td><td className="p-2">{number(item.conditions.air_viscosity_pa_s)}</td>
      </tr>)}</tbody></table></div>
      <label className="block text-xs text-zinc-400">Reference configuration<select aria-label="Comparison reference configuration" className={field} value={baseline || ''} disabled={busy || running || !selected.length} onChange={(e) => setReference(e.target.value)}>{!selected.length && <option value="">Select configurations…</option>}{selectedSimulations.map((item) => <option key={item.id} value={item.id}>{item.name} · r{item.revision}</option>)}</select></label>
      <p className="text-xs text-zinc-500">The reference defines percentage differences; a zero or failed reference produces an explicit unavailable value. Validation requires identical evaluated geometry, operating inputs and conditions, and checks polar requirements; each saved geometry revision remains recorded. It does not silently align incompatible cases.</p>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={busy || running || selected.length < 2 || selected.length > 8} onClick={validate}>Validate comparison</button><button className={button} disabled={configurationBusy || busy || running || !validation?.valid} onClick={submit}>Run solver comparison</button></div>
      {validation?.valid && <div className="space-y-2 text-xs text-emerald-300"><p>Compatible comparison · {validation.simulations.length} frozen configuration revisions</p>{(validation.warnings || []).map((warning, index) => <p key={index} className="text-amber-300">{warning}</p>)}</div>}
    </>}
    {comparisonRun && <div aria-label="Solver comparison execution" className="space-y-3 border-t border-zinc-800 pt-4">
      <h4 className="text-sm">{comparisonRun.comparison.name} · {comparisonRun.result?.comparison_status || comparisonRun.state} · {Math.round((comparisonRun.progress || 0) * 100)}%</h4>
      <p className="text-xs text-zinc-500">Run {comparisonRun.id} · {(comparisonRun.comparison.simulations || []).map((s) => `${s.name} r${s.revision}`).join(' / ')}. The global Cancel command stops an active batch.</p>
      <details><summary className="cursor-pointer text-xs text-zinc-400">Frozen comparison inputs</summary><div className="mt-2 overflow-auto"><table className="w-full text-left text-xs"><thead className="text-zinc-500"><tr>{['Configuration', 'Geometry reference', 'RPM', 'Airfoil', 'Density [kg/m³]', 'Viscosity [Pa·s]', 'Polar asset'].map((title) => <th key={title} className="p-2 font-normal">{title}</th>)}</tr></thead><tbody>{comparisonRun.comparison.simulations.map((source) => <tr key={source.id} className="border-t border-zinc-800"><td className="p-2">{source.name} · r{source.revision}</td><td className="p-2">{source.geometry_id?.slice(0, 8)} · r{source.geometry_revision}</td><td className="p-2">{number(source.inputs.rpm)}</td><td className="p-2">{source.inputs.airfoil}</td><td className="p-2">{number(source.conditions.air_density_kg_m3)}</td><td className="p-2">{number(source.conditions.air_viscosity_pa_s)}</td><td className="p-2">{source.polar_asset?.filename || 'None'}<span className="block text-[10px] text-zinc-500">{source.polar_asset_id?.slice(0, 8)}</span></td></tr>)}</tbody></table></div></details>
      {comparisonRun.result && <p className="text-xs text-zinc-400">{comparisonRun.result.completed_cases}/{comparisonRun.result.total_cases} comparison cases completed · {comparisonRun.result.failed_cases} failed</p>}
      {comparisonRun.error && <p role="alert" className="text-xs text-red-400">{comparisonRun.error}</p>}
      <details><summary className="cursor-pointer text-xs text-zinc-500">Comparison logs</summary><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[10px] text-zinc-400">{(comparisonRun.logs || []).join('\n')}</pre></details>
      {(comparisonRun.result?.rows || []).length > 0 && <><button className={button} onClick={() => act(() => download(`/v1/runs/${comparisonRun.id}/comparison.csv`, 'solver-comparison.csv'))}>Export solver comparison CSV</button>
        <div className="overflow-auto"><table aria-label="Solver comparison results" className="w-full text-left text-xs"><thead className="text-zinc-500"><tr>{['Configuration', 'Model / fidelity', 'State / convergence', 'Polar source', 'Thrust [N]', 'Δ thrust', 'Torque [N·m]', 'Δ torque', 'Power [W]', 'Δ power', 'Figure of merit', 'Δ figure of merit', 'Snapshot'].map((title) => <th key={title} className="p-2 font-normal">{title}</th>)}</tr></thead><tbody>{comparisonRun.result.rows.map((row, index) => <tr key={`${row.simulation_id}-${row.node_id}-${index}`} className="border-t border-zinc-800">
          <td className="p-2">{row.simulation_name} · r{row.simulation_revision}{row.simulation_id === row.baseline_simulation_id && <span className="block text-emerald-400">Reference</span>}<span className="mt-1 block text-[10px] text-zinc-500">{row.simulation_id?.slice(0, 8)}</span></td>
          <td className="p-2">{row.model || '—'} · {row.fidelity || '—'}</td><td className="p-2">{row.state} · {row.converged == null ? 'Convergence not reported' : row.converged ? 'Converged' : 'Not converged'}{row.error && <p className="mt-1 text-red-400">{row.error}</p>}</td><td className="p-2">{row.polar_data || '—'}</td>
          {['thrust_n', 'torque_nm', 'power_w', 'figure_of_merit'].map((metric) => <Metric key={metric} row={row} metric={metric} />)}
          <td className="p-2">{row.state === 'succeeded' && <button className={button} aria-label={`Inspect comparison ${row.simulation_name}`} onClick={() => inspect(row)}>Inspect case</button>}</td>
        </tr>)}</tbody></table></div>
      </>}
    </div>}
    {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
  </section>;
}

function Metric({ row, metric }) {
  return <><td className="p-2 tabular-nums">{number(row[metric])}</td><td className="p-2 tabular-nums">{difference(row, metric)}</td></>;
}
