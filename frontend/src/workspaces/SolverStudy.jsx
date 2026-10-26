import { useEffect, useState } from 'react';
import { download, request } from '../backend.js';
import { formatValue, stationSeries } from '../lib/blade.js';
import { Button, Disclosure, Notice, SelectField, StatusDot } from '../ui/controls.jsx';
import LineChart from '../ui/LineChart.jsx';
import SimulationComparison from './SimulationComparison.jsx';

export const caseColors = ['#4CC9F0', '#B49CFB', '#F2A93B', '#46D19A', '#F27C7C', '#C4CAD2', '#8FDDF6', '#F2C46D'];
const solverIds = ['bemt', 'llt', 'vlm', 'bem'];
const active = (run) => ['queued', 'running', 'cancelling'].includes(run?.state);
const percent = (row, metric) => {
  const value = row.baseline_differences_pct?.[metric];
  if (value != null) return `${value > 0 ? '+' : ''}${formatValue(value, 3)} %`;
  const reason = row.baseline_difference_reasons?.[metric];
  return reason === 'zero_baseline' ? 'Undefined: zero reference' : reason === 'baseline_failed' ? 'Unavailable: reference failed' : reason === 'case_failed' ? 'Unavailable: case failed' : '—';
};
// Case caption: the solver for a one-simulation comparison, the simulation otherwise.
export const caseLabel = (run, row) => run?.comparison?.kind === 'solver' ? (row.model || '').toUpperCase() : row.simulation_name;

export function comparisonCases(run) {
  return (run?.result?.cases || []).map((sample, index) => {
    const row = (run.result.rows || []).find((item) => item.case_index === sample.index) || {};
    return { index: sample.index, sample, row, color: caseColors[index % caseColors.length], label: caseLabel(run, row) || sample.simulation_name,
      analysis: sample.state === 'succeeded' ? sample.result.analyses[0] : null };
  });
}

function ComparisonResult({ run, onInspect }) {
  const cases = comparisonCases(run);
  const rows = run.result?.rows || [];
  const validation = run.comparison_validation || {};
  const [station, setStation] = useState(0.7);
  return <>
    <section aria-label="Solver comparison execution" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="m-0 text-[15px] font-semibold">{run.comparison.name} <span className="font-normal text-nv-muted">· {run.result?.comparison_status || run.state} · {Math.round((run.progress || 0) * 100)}%</span></h2>
        {rows.length > 0 && <button type="button" className="text-[13px] text-nv-accent hover:text-nv-accent-soft" onClick={() => download(`/v1/runs/${run.id}/comparison.csv`, 'solver-comparison.csv')}>Export solver comparison CSV</button>}
      </div>
      {run.result && <p className="m-0 text-[13px] text-nv-muted">{run.result.completed_cases}/{run.result.total_cases} comparison cases completed · {run.result.failed_cases} failed</p>}
      {run.error && <Notice tone="err" role="alert">{run.error}</Notice>}
      {rows.length > 0 && <div className="overflow-x-auto"><table aria-label="Solver comparison results" className="w-full min-w-[760px] border-collapse text-[13px]">
        <thead><tr className="text-xs text-nv-muted">{['Case', 'Thrust [N]', 'Δ', 'Torque [N·m]', 'Power [W]', 'Δ', 'FoM', 'Convergence', ''].map((title, index) =>
          <th key={index} scope="col" className={`pb-2.5 font-medium ${index === 0 ? 'text-left' : 'px-3 text-right'}`}>{title}</th>)}</tr></thead>
        <tbody className="whitespace-nowrap font-mono tabular">{cases.map(({ row, color, label, sample }, index) => <tr key={sample.index} className="border-t border-nv-line">
          <td className="py-2.5 pr-3 font-sans"><span className="inline-flex items-center gap-2"><span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />{label}</span>
            {index === 0 && <span className="ml-2 text-nv-ok-ink">Reference</span>}<span className="ml-2 text-nv-muted">{row.fidelity}</span>
            {row.error && <span className="mt-1 block text-xs text-nv-err-ink">{row.error}</span>}</td>
          <td className="px-3 text-right">{formatValue(row.thrust_n, 4)}</td><td className="px-3 text-right text-nv-reference">{index ? percent(row, 'thrust_n') : '—'}</td>
          <td className="px-3 text-right">{formatValue(row.torque_nm, 3)}</td><td className="px-3 text-right">{formatValue(row.power_w, 4)}</td>
          <td className="px-3 text-right text-nv-reference">{index ? percent(row, 'power_w') : '—'}</td><td className="px-3 text-right">{formatValue(row.figure_of_merit, 3)}</td>
          <td className={`px-3 text-right ${row.converged ? 'text-nv-ok-ink' : 'text-nv-muted'}`}>{row.state !== 'succeeded' ? row.state : row.converged == null ? 'n/a' : row.converged ? 'converged' : 'not converged'}</td>
          <td className="pl-3 text-right font-sans">{row.state === 'succeeded' && <button type="button" className="text-[13px] text-nv-accent hover:text-nv-accent-soft" aria-label={`Inspect comparison ${row.simulation_name}${run.comparison.kind === 'solver' ? ` ${label}` : ''}`} onClick={() => onInspect(run, sample)}>Open</button>}</td>
        </tr>)}</tbody>
      </table></div>}
      {(validation.warnings || []).map((warning) => <p key={warning} className="m-0 flex items-center gap-2 text-[13px] text-nv-warn-ink"><StatusDot tone="warn" />{warning}</p>)}
      <details><summary className="cursor-pointer text-xs text-nv-muted">Comparison logs</summary><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-nv-muted">{(run.logs || []).join('\n')}</pre></details>
    </section>
    {cases.some((item) => item.analysis) && <section aria-labelledby="solver-along" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3"><h2 id="solver-along" className="m-0 text-[15px] font-semibold">Along the blade</h2>
        <span className="flex flex-wrap gap-4 text-xs text-nv-muted">{cases.map((item) => <span key={item.index} className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3.5" style={{ background: item.color }} />{item.label}</span>)}</span></div>
      <div className="grid gap-x-8 gap-y-7 md:grid-cols-2 2xl:grid-cols-3">
        {[['d_thrust_n', 'Local thrust', 'N'], ['alpha_deg', 'Angle of attack', '°'], ['circulation', 'Circulation', 'm²/s']].map(([field, title, unit]) =>
          <LineChart key={field} title={title} unit={unit} height={190} selection={station} onSelect={setStation}
            series={cases.filter((item) => item.analysis).map((item) => ({ id: String(item.index), color: item.color, points: stationSeries(item.analysis.stations, field) }))} />)}
      </div>
    </section>}
  </>;
}

export function ComparisonChecks({ run }) {
  const cases = comparisonCases(run);
  const rows = run?.result?.rows || [];
  const reference = cases[0];
  const validation = run?.comparison_validation || {};
  const iterative = cases.filter((item) => item.analysis?.convergence);
  const converged = iterative.filter((item) => item.analysis.convergence.converged);
  const polarSources = [...new Set(rows.map((row) => row.polar_data).filter(Boolean))];
  if (!reference) return <p className="m-0 text-[13px] text-nv-muted">Checks appear when a comparison has results.</p>;
  return <>
    <div aria-label="Comparison checks" className="flex flex-col gap-7">
      <section aria-labelledby="solver-checks"><h2 id="solver-checks" className="m-0 mb-3 text-[15px] font-semibold">Like-for-like checks</h2>
        <ul className="m-0 list-none p-0 text-[13px]">
          {[[true, 'Same geometry', `${validation.geometry_hash ? validation.geometry_hash.slice(0, 8) : '—'}`],
            [true, 'Same operating point', validation.operating_conditions ? `${formatValue(validation.operating_conditions.rpm, 4)} rpm · ρ ${formatValue(validation.operating_conditions.air_density_kg_m3)}` : '—'],
            [polarSources.length <= 1, 'Polars', polarSources.join(' · ') || '—'],
            [iterative.length === converged.length, 'Converged', `${converged.length} of ${iterative.length} iterative`]].map(([ok, label, value]) =>
            <li key={label} className="flex justify-between gap-4 border-t border-nv-line py-2.5 last:border-b"><span>{label}</span><span className={ok ? 'text-nv-ok-ink' : 'text-nv-warn-ink'}>{ok ? '✓ ' : ''}{value}</span></li>)}
        </ul>
      </section>
      {cases.length > 1 && <section aria-labelledby="solver-spread"><h2 id="solver-spread" className="m-0 mb-3.5 text-[15px] font-semibold">Difference from {reference.label}</h2>
        <div className="flex flex-col gap-3.5">{cases.slice(1).flatMap((item) => [['thrust_n', 'Thrust'], ['power_w', 'Power']].map(([metric, name]) => {
          const value = item.row.baseline_differences_pct?.[metric];
          return <div key={`${item.index}-${metric}`}><div className="mb-1.5 flex justify-between text-[13px]"><span>{name} · {item.label}</span><span className="font-mono">{percent(item.row, metric)}</span></div>
            <div className="h-2 rounded bg-nv-line"><div className="h-full rounded" style={{ width: `${Math.min(100, Math.abs(value ?? 0) / 2)}%`, background: item.color }} /></div></div>;
        }))}</div>
        <p className="m-0 mt-3.5 text-xs leading-relaxed text-nv-muted">Bars are scaled so 200 % fills the track. A large spread means the models disagree for this blade.</p>
      </section>}
    </div>
  </>;
}

export default function SolverStudy({ projectId, projectControls, methods, current, activeJob, configurationBusy, onStart, onInspect, onOpenSaved }) {
  const [simulations, setSimulations] = useState([]);
  const [simulationId, setSimulationId] = useState('');
  const [models, setModels] = useState(['bemt', 'llt']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const running = active(current) || active(activeJob);
  useEffect(() => {
    setSimulations([]); setSimulationId('');
    if (!projectId) return undefined;
    let valid = true;
    request(`/v1/projects/${projectId}/simulations`).then((items) => {
      if (!valid) return;
      setSimulations(items);
      setSimulationId(items[0]?.id || '');
    }).catch((caught) => { if (valid) setError(caught.message); });
    return () => { valid = false; };
  }, [projectId]);
  const names = Object.fromEntries((methods || []).map((method) => [method.id, method]));
  const toggle = (id) => setModels((list) => list.includes(id) ? list.filter((item) => item !== id) : [...list, id].sort((a, b) => solverIds.indexOf(a) - solverIds.indexOf(b)));
  const run = async () => {
    setBusy(true); setError('');
    try { onStart(await projectControls.current.solverComparison(models, simulationId)); } catch (caught) { setError(caught.message); } finally { setBusy(false); }
  };
  const comparison = current?.comparison ? current : null;
  return <>
      <section aria-labelledby="solver-setup" className="flex flex-col gap-3.5">
        <h2 id="solver-setup" className="m-0 text-[15px] font-semibold">Setup</h2>
        {!projectId ? <p className="m-0 text-[13px] text-nv-muted">Save or open a project to compare solvers on one of its simulations.</p> : <>
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-72"><SelectField inline ariaLabel="Simulation to compare" value={simulationId} onChange={setSimulationId}
              options={simulations.length ? simulations.map((item) => [item.id, `${item.name} · r${item.revision}`]) : [['', 'No saved simulations']]} /></div>
            <div role="group" aria-label="Solvers to compare" className="flex flex-wrap gap-2">{solverIds.map((id) => {
              const checked = models.includes(id);
              return <label key={id} className="flex h-[34px] cursor-pointer items-center gap-2 rounded-full border px-3 text-[13px]" style={{ borderColor: checked ? caseColors[models.indexOf(id)] : '#2A303A' }}>
                <input type="checkbox" className="accent-nv-accent" checked={checked} onChange={() => toggle(id)} aria-label={`Compare with ${names[id]?.name || id.toUpperCase()}`} />
                {id.toUpperCase()}{checked && models[0] === id && <span className="text-[11px] text-nv-muted">ref</span>}{names[id]?.fidelity === 'experimental' && <span className="text-[11px] text-nv-warn-ink">experimental</span>}
              </label>;
            })}</div>
            <Button className="ml-auto" disabled={configurationBusy || busy || running || models.length < 2 || !simulationId} onClick={run}>Run comparison</Button>
          </div>
          <p className="m-0 text-[13px] text-nv-muted">The selected simulation's geometry, operating point, air data and polars are frozen for every solver. The first ticked solver is the reference. No extra simulations are created.</p>
          {error && <Notice tone="err" role="alert">{error}</Notice>}
        </>}
      </section>
      {comparison ? <ComparisonResult run={comparison} onInspect={onInspect} /> : <p className="m-0 text-[13px] text-nv-muted">Results appear here. Earlier comparisons are listed in the history on the left.</p>}
      <Disclosure title="Compare existing saved simulations" summary="one per solver">
        <SimulationComparison projectId={projectId} current={current} activeJob={activeJob} configurationBusy={configurationBusy} showResults={false}
          onInspect={() => {}} onStart={onOpenSaved} />
      </Disclosure>
  </>;
}
