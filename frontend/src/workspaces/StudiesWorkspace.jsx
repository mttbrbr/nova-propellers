import { useEffect, useRef, useState } from 'react';
import { download, request } from '../backend.js';
import { usePreferences } from '../components/ProjectPicker.jsx';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import { StatusDot } from '../ui/controls.jsx';
import useDesignStudy, { DesignChecks, savedDesignComparisons } from './DesignStudy.jsx';
import SolverStudy, { ComparisonChecks } from './SolverStudy.jsx';
import StudyGrid from './StudyGrid.jsx';

const button = 'inline-flex h-[34px] items-center rounded-[7px] border border-nv-edge px-3 text-[13px] hover:bg-nv-hover disabled:opacity-40';
const field = 'h-[34px] rounded-md border border-nv-edge bg-nv-chrome px-2.5 text-[13px]';
const active = (run) => ['queued', 'running', 'cancelling'].includes(run?.state);
const number = (value) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumSignificantDigits: 6 });

function PerformanceTable({ rows, onInspect, label = 'Performance results' }) {
  return <div className="overflow-x-auto"><table aria-label={label} className="w-full text-left text-xs"><thead className="text-nv-muted"><tr>
    {['Case/value', 'State/model', 'Polar data', 'RPM', 'Airfoil', 'Density [kg/m³]', 'Viscosity [Pa·s]', 'Diameter [m]', 'Thrust [N]', 'Torque [N·m]', 'Power [W]', 'Figure of merit', 'Result'].map((title) => <th key={title} className="p-2 font-normal">{title}</th>)}
  </tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.run_id}-${row.case_index}-${row.node_id}-${index}`} className="border-t border-nv-line">
    <td className="p-2">{row.value == null ? row.run_id.slice(0, 8) : <>{row.parameter}: {number(row.value)} [{row.parameter_units}]{row.secondary_parameter && <span className="mt-1 block">{row.secondary_parameter}: {number(row.secondary_value)} [{row.secondary_units}]</span>}</>}</td>
    <td className="p-2">{row.state === 'succeeded' ? `${row.model} · ${row.fidelity}${row.run_state === 'cancelled' ? ' · cancelled study' : ''}` : row.state}{row.error && <div className="mt-1 max-w-xs text-nv-err-ink">{row.error}</div>}</td>
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
  return <div className="rounded border border-nv-line p-4">
    <div className="flex justify-between text-xs text-nv-muted"><span>Thrust [N]: {number(ymin)}–{number(ymax)}</span><select aria-label="Plot analysis node" className={field} value={selected} onChange={(e) => setSelection(e.target.value)}>{ids.map((id) => <option key={id}>{id}</option>)}</select></div>
    <svg viewBox="0 0 600 200" role="img" aria-label="Thrust versus sweep parameter" className="mt-3 max-h-64 w-full"><path d="M30 20V175H575" fill="none" stroke="#3A424E"/><polyline points={coordinates} fill="none" stroke="#4CC9F0" strokeWidth="2"/></svg>
    <p className="text-xs text-nv-muted">{parameter} [{units}]: {number(xmin)}–{number(xmax)}. Failed cases are excluded from the curve and retained in the table.</p>
  </div>;
}

const types = [
  ['solver', 'Solver comparison', 'Same blade and conditions, different models'],
  ['design', 'Design comparison', 'Different blades, in this or other projects'],
  ['sweep', 'Parameter sweep', 'One or two inputs over a range'],
];
const describe = (run) => run.comparison ? `${run.comparison.kind === 'solver' ? 'Solver' : 'Saved simulations'} · ${run.comparison.simulations.map((s) => s.workflow.nodes.find((n) => n.type === 'analysis')?.config?.model?.toUpperCase() || s.name).join(', ')}`
  : `Sweep · ${run.study.parameter}${run.study.secondary ? ` × ${run.study.secondary.parameter}` : ''}`;

export default function StudiesWorkspace({ projectId, projectControls, onInspect, onInverseDesign, onExecutionChange, activeStudy, configurationBusy = false, selectedRun = null,
  methods = [], studyRequest = null, onOpenSource }) {
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
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const projectScope = useRef(projectId);
  const [type, setType] = useState(studyRequest?.type || (selectedRun?.study ? 'sweep' : selectedRun?.comparison ? 'solver' : 'solver'));
  const [designRequest, setDesignRequest] = useState(studyRequest?.type === 'design' ? studyRequest : null);
  const { version: preferenceVersion } = usePreferences();
  useEffect(() => {
    if (!studyRequest) return;
    setType(studyRequest.type);
    if (studyRequest.type === 'design') setDesignRequest(studyRequest);
  }, [studyRequest]);
  useEffect(() => { if (selectedRun?.study) setType('sweep'); else if (selectedRun?.comparison) setType('solver'); }, [selectedRun]);
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
    setCurrent((previous) => previous?.project_id === projectId ? previous : null); setRows([]); setComparison(null);
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

  const inspectComparison = (run, sample) => {
    if (sample?.state !== 'succeeded') return;
    const snapshot = sample.snapshot;
    onInspect(sample.result, snapshot.inputs, run.id, sample.index, {
      ...run, simulation_id: sample.simulation_id, simulation_name: run.comparison.kind === 'solver' ? snapshot.name : sample.simulation_name,
      simulation_revision: sample.simulation_revision, geometry_id: snapshot.geometry_id, geometry_revision: snapshot.geometry_revision,
      inputs: snapshot.inputs, workflow: snapshot.workflow, conditions: snapshot.conditions, polar_asset_id: snapshot.polar_asset_id,
    });
  };
  const design = useDesignStudy({ projectId, request: designRequest, onOpenSource });
  const startComparison = (run) => { onExecutionChange?.(run); if (run.project_id === projectScope.current) { setCurrent(run); setComparison(null); } };
  const history = runs.filter((r) => r.study || r.comparison).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  // Saved design comparisons live in this computer's storage; the version re-reads them after a save.
  const designHistory = preferenceVersion >= 0 ? savedDesignComparisons().filter((item) => !projectId || item.projectIds?.includes(projectId)) : [];
  const sweep = <>
    <section aria-labelledby="sweep-setup" className="flex flex-col gap-4">
      <h2 id="sweep-setup" className="m-0 text-[15px] font-semibold">Parameter sweep</h2>
      <p className="m-0 text-[13px] text-nv-muted">Run the current workflow at 2–32 distinct values or over a two-axis Cartesian grid with at most 32 cases. Up to 128 analysis evaluations are allowed. Inputs and selected data are frozen for the study.</p>
      <div className="flex flex-wrap gap-3"><label className="flex flex-col gap-1.5 text-[13px] text-nv-muted">Parameter<select aria-label="Sweep parameter" className={field} value={parameter} onChange={(e) => setParameter(e.target.value)}>{Object.entries(parameters).map(([id, p]) => <option key={id} value={id}>{p.label} [{p.units}]</option>)}</select></label>
        <label className="flex min-w-[240px] flex-1 flex-col gap-1.5 text-[13px] text-nv-muted">Values<input aria-label="Sweep values" className={`${field} w-full font-mono`} value={values} onChange={(e) => setValues(e.target.value)} /></label></div>
      <label className="flex items-center gap-2 text-[13px] text-nv-muted"><input aria-label="Use second sweep axis" type="checkbox" className="accent-nv-accent" checked={twoAxes} onChange={(e) => setTwoAxes(e.target.checked)} />Add a second parameter axis</label>
      {twoAxes && <div className="flex flex-col gap-3 border-l-2 border-nv-edge pl-4"><div className="flex flex-wrap gap-3"><label className="flex flex-col gap-1.5 text-[13px] text-nv-muted">Second parameter<select aria-label="Second sweep parameter" className={field} value={secondaryParameter} onChange={(e) => setSecondaryParameter(e.target.value)}>{Object.entries(parameters).map(([id, p]) => <option key={id} value={id} disabled={id === parameter}>{p.label} [{p.units}]</option>)}</select></label><label className="flex min-w-[240px] flex-1 flex-col gap-1.5 text-[13px] text-nv-muted">Second axis values<input aria-label="Second sweep values" className={`${field} w-full font-mono`} value={secondaryValues} onChange={(e) => setSecondaryValues(e.target.value)} /></label></div><p className="m-0 text-xs text-nv-muted">Every primary value is evaluated with every secondary value. Use different parameters; the complete grid is limited to 32 cases and 128 analysis evaluations. Results use a discrete cell grid for each analysis node.</p>{parameter === secondaryParameter && <p className="m-0 text-xs text-nv-warn-ink">Choose different parameters for the two axes.</p>}</div>}
      {(parameter === 'diameter' || (twoAxes && secondaryParameter === 'diameter')) && <p className="m-0 text-xs text-nv-warn-ink">When diameter varies, chord and twist inputs are held fixed; geometry limits still apply. Use manual sizing so the values are not overwritten.</p>}
      <div className="flex gap-2"><button className={button} disabled={configurationBusy || busy || active(current) || active(activeStudy) || (twoAxes && parameter === secondaryParameter)} onClick={start}>Run sweep</button>
        <button className={button} onClick={onInverseDesign}>Inverse design</button></div>
    </section>
    {current?.study && <section className="flex flex-col gap-2">
      <p className="m-0 text-[13px] text-nv-muted">Study from {current.simulation_name || 'unassigned configuration'}{current.simulation_revision ? ` · r${current.simulation_revision}` : ''} · {current.inputs.rpm} rpm baseline · {current.workflow.nodes.filter((n) => n.type === 'analysis').map((n) => (n.config.model || 'bemt').toUpperCase()).join(' + ')}</p>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]"><span>{current.result?.study_status || current.state} · {Math.round(current.progress * 100)}%</span>
        {current.result?.cases.length > 0 && <button className={button} onClick={() => act(() => download(`/v1/runs/${current.id}/study.csv`, 'study.csv'))}>Export study CSV</button>}</div>
      {current.result && <p className="m-0 text-[13px] text-nv-muted">{current.result.completed_cases}/{current.result.total_cases} completed · {current.result.failed_cases} failed</p>}
      {current.error && <p className="m-0 text-[13px] text-nv-err-ink">{current.error}</p>}
      <details><summary className="cursor-pointer text-xs text-nv-muted">Study logs</summary><pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-[11px] text-nv-muted">{current.logs.join('\n')}</pre></details>
    </section>}
    {current?.study?.secondary && axes.length === 2
      ? <StudyGrid run={current} rows={rows} primary={axes[0]} secondary={axes[1]} onInspect={inspect} />
      : current?.study && <SweepPlot rows={rows} parameter={axes[0]?.parameter || current?.result?.definition?.parameter || parameter} units={axes[0]?.units || current?.result?.units || parameters[parameter]?.units} />}
    {rows.length > 0 && <PerformanceTable rows={rows} onInspect={inspect} label="Sweep results" />}
    {comparison && <PerformanceTable rows={comparison.rows} onInspect={inspect} label="Stored run comparison results" />}
  </>;
  const comparisonRun = current?.comparison ? current : null;
  const content = type === 'solver' ? <SolverStudy projectId={projectId} projectControls={projectControls} methods={methods} current={current} activeJob={activeStudy}
    configurationBusy={configurationBusy} onStart={startComparison} onInspect={inspectComparison} onOpenSaved={startComparison} />
    : type === 'design' ? design.main : sweep;

  return <StageLayout inputsLabel="Studies navigation" contentLabel="Study" sideLabel="Study checks"
    inputs={<>
      <StageTitle title="Studies" detail="Compare results or explore a parameter." />
      <nav aria-label="Study type" className="-mx-3 flex flex-col gap-0.5">{types.map(([id, name, detail]) => <button key={id} type="button" aria-current={type === id ? 'page' : undefined} onClick={() => setType(id)}
        className={`flex flex-col gap-0.5 rounded-lg px-3 py-2.5 text-left ${type === id ? 'bg-nv-hover' : 'hover:bg-nv-raised'}`}>
        <span className={`font-semibold ${type === id ? 'text-nv-ink-strong' : ''}`}>{name}</span><span className="text-[12.5px] text-nv-muted">{detail}</span></button>)}</nav>
      {type === 'design' && design.picker}
      <section aria-labelledby="study-history" className="flex flex-col gap-1.5">
        <div className="flex items-baseline justify-between"><h2 id="study-history" className="m-0 text-[13px] font-semibold">History</h2><span className="text-[12.5px] text-nv-muted">this project · {history.length + designHistory.length}</span></div>
        <div className="-mx-3 flex max-h-[420px] flex-col gap-0.5 overflow-y-auto">
          {history.map((r) => <button key={r.id} type="button" aria-label={`Open study ${r.id.slice(0, 8)}`} aria-current={current?.id === r.id ? 'true' : undefined}
            onClick={() => { setCurrent(r); setType(r.study ? 'sweep' : 'solver'); }}
            className={`grid grid-cols-[10px_minmax(0,1fr)] gap-2.5 rounded-lg px-3 py-2 text-left ${current?.id === r.id ? 'bg-nv-raised' : 'hover:bg-nv-raised'}`}>
            <StatusDot tone={r.state === 'succeeded' ? 'ok' : r.state === 'failed' ? 'err' : 'warn'} className="mt-1.5" />
            <span className="min-w-0"><span className="block truncate text-[13px]">{describe(r)}</span><span className="block truncate text-xs text-nv-muted">{r.simulation_name || r.name} · {r.state} · {String(r.created_at || '').slice(0, 16).replace('T', ' ')}</span></span>
          </button>)}
          {designHistory.map((item) => <button key={item.id} type="button" onClick={() => { setType('design'); setDesignRequest({ type: 'design', runIds: item.runIds, nonce: Date.now() }); }}
            className="grid grid-cols-[10px_minmax(0,1fr)] gap-2.5 rounded-lg px-3 py-2 text-left hover:bg-nv-raised">
            <StatusDot tone="accent" className="mt-1.5" />
            <span className="min-w-0"><span className="block truncate text-[13px]">Design · {item.runIds.length} results</span><span className="block truncate text-xs text-nv-muted">{item.name}</span></span>
          </button>)}
          {!history.length && !designHistory.length && <p className="m-0 px-3 text-[13px] text-nv-muted">No studies in this project yet.</p>}
        </div>
      </section>
      {error && <p role="alert" className="m-0 text-[13px] text-nv-err-ink">{error}</p>}
    </>}
    content={content}
    side={type === 'solver' ? <ComparisonChecks run={comparisonRun} /> : type === 'design' ? <DesignChecks designs={design.designs} /> : null} />;
}
