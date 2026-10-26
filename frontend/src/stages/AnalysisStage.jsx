import { useMemo, useState } from 'react';
import PropellerViewport from '../components/PropellerViewport.jsx';
import { formatValue } from '../lib/blade.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import { Button, Field, Metric, Notice, Section, SelectField, StatusDot } from '../ui/controls.jsx';
import LineChart from '../ui/LineChart.jsx';

const fidelityTone = (fidelity) => fidelity === 'experimental' ? 'text-nv-warn-ink' : fidelity === 'preliminary' ? 'text-nv-accent-soft' : 'text-nv-reference';

export function PolarCharts({ points, title, detail, demonstration }) {
  const sets = useMemo(() => [...new Set((points || []).map((p) => Number(p.reynolds)))].sort((a, b) => a - b), [points]);
  const [chosen, setChosen] = useState(null);
  const reynolds = sets.includes(chosen) ? chosen : sets[Math.floor(sets.length / 2)];
  const rows = (points || []).filter((p) => Number(p.reynolds) === reynolds).sort((a, b) => a.alpha_deg - b.alpha_deg);
  const alphas = rows.map((row) => Number(row.alpha_deg));
  const domain = alphas.length ? [Math.min(...alphas), Math.max(...alphas)] : [0, 1];
  const ticks = alphas.length ? [domain[0], Number(((domain[0] + domain[1]) / 2).toFixed(1)), domain[1]] : [0, 1];
  return <section aria-labelledby="polar-title">
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
      <h2 id="polar-title" className="m-0 text-[15px] font-semibold">{title} {detail && <span className="font-normal text-nv-muted">· {detail}</span>}</h2>
      {sets.length > 1 && <div className="w-44"><SelectField inline ariaLabel="Reynolds number shown" value={reynolds} onChange={(v) => setChosen(Number(v))} options={sets.map((re) => [re, `Re ${formatValue(re)}`])} /></div>}
    </div>
    {demonstration && <div className="mb-4"><Notice>Synthetic demonstration polars, not measurements.</Notice></div>}
    <div className="grid gap-8 lg:grid-cols-2">
      <LineChart title="Lift" unit="Cl" xDomain={domain} xTicks={ticks} xLabel="α °" empty="Select or import polars to preview them."
        series={[{ id: 'cl', color: '#4CC9F0', points: rows.map((r) => ({ x: Number(r.alpha_deg), y: Number(r.cl) })) }]} />
      <LineChart title="Drag" unit="Cd" xDomain={domain} xTicks={ticks} xLabel="α °" digits={3} empty="Select or import polars to preview them."
        series={[{ id: 'cd', color: '#F2A93B', points: rows.map((r) => ({ x: Number(r.alpha_deg), y: Number(r.cd) })) }]} />
    </div>
  </section>;
}

function LastRun({ context, onOpen, onRun, runDisabled }) {
  const run = context?.lastRun;
  if (!run) return <section aria-labelledby="last-run" className="flex flex-col gap-2">
    <h2 id="last-run" className="m-0 text-[15px] font-semibold">Last run</h2>
    <p className="m-0 text-[13px] text-nv-muted">{context?.simulation ? 'This simulation has not been run yet.' : 'Save or run the draft to start its history.'}</p>
  </section>;
  const analysis = run.result.analyses[0];
  const performance = analysis?.performance || {};
  return <section aria-labelledby="last-run" className="flex flex-col gap-4">
    <div className="flex items-baseline justify-between gap-3">
      <h2 id="last-run" className="m-0 text-[15px] font-semibold">Last run <span className="text-[13px] font-normal text-nv-muted">· {(analysis?.model || '').toUpperCase()} · {analysis?.convergence ? (analysis.convergence.converged ? 'converged' : 'not converged') : 'no convergence data'}</span></h2>
      <button type="button" className="text-[13px] text-nv-accent hover:text-nv-accent-soft" onClick={() => onOpen(run)}>Open results →</button>
    </div>
    {context.lastRunStale && <Notice role="status" action={<Button className="!h-7 !px-2.5" disabled={runDisabled} onClick={onRun}>Run again</Button>}>
      Out of date: {context.changedSinceRun.join(', ')} changed since this run.</Notice>}
    <dl className={`m-0 grid grid-cols-3 gap-x-6 gap-y-[18px] ${context.lastRunStale ? 'opacity-60' : ''}`}>
      <Metric size="md" label="Thrust" value={formatValue(performance.thrust_n, 4)} unit="N" />
      <Metric size="md" label="Torque" value={formatValue(performance.torque_nm, 3)} unit="N·m" />
      <Metric size="md" label="Power" value={formatValue(performance.power_w, 4)} unit="W" />
      <Metric size="md" label="Figure of merit" value={formatValue(performance.efficiency, 3)} />
      <Metric size="md" label="Speed" value={formatValue(analysis?.operating_point?.rpm, 4)} unit="rpm" />
      <Metric size="md" label="Run" value={run.id.slice(0, 8)} />
    </dl>
  </section>;
}

export default function AnalysisStage({ a }) {
  const { inputs, set, preview, context, station } = a;
  const methods = (a.methods.length ? a.methods : [
    { id: 'bemt', name: 'BEMT', fidelity: 'preliminary', description: '' }, { id: 'llt', name: 'LLT', fidelity: 'preliminary', description: '' },
    { id: 'vlm', name: 'VLM', fidelity: 'experimental', description: '' }, { id: 'bem', name: 'BEM', fidelity: 'experimental', description: '' },
  ]).filter((method) => method.role !== 'sizing_reference' && method.id !== 'actuator_disk');
  const current = methods.find((method) => method.id === a.model);
  const stations = preview.canonical?.stations || [];
  const rootFraction = stations.length ? stations[0].radius_m / Math.max(preview.canonical.diameter_m / 2, 1e-9) : 0.14;
  return <StageLayout inputsLabel="Stage inputs" contentLabel="Analysis context" sideLabel="Preview and last run"
    inputs={<>
      <StageTitle title="Analysis" detail="Solver, operating point and airfoil data for this simulation." />
      <fieldset className="m-0 flex flex-col gap-0.5 border-0 p-0">
        <legend className="mb-2 p-0 text-[13px] font-semibold">Solver</legend>
        {methods.map((method) => <label key={method.id} className={`grid cursor-pointer grid-cols-[18px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-lg p-2.5 hover:bg-nv-raised ${a.model === method.id ? 'bg-nv-hover' : ''}`}>
          <input type="radio" name="solver" className="mt-0.5 accent-nv-accent" checked={a.model === method.id} onChange={() => a.chooseModel(method.id)} aria-label={`${method.name}${method.id.toUpperCase() !== method.name ? ` (${method.id.toUpperCase()})` : ''}`} />
          <span className="min-w-0"><span className="block text-[13px]">{method.id.toUpperCase()}</span>{method.description && <span className="mt-0.5 block text-[12.5px] leading-snug text-nv-muted">{method.description}</span>}</span>
          <span className={`text-xs capitalize ${fidelityTone(method.fidelity)}`}>{method.fidelity}</span>
        </label>)}
        <button type="button" className="mx-2.5 mt-2 text-left text-[13px] text-nv-accent hover:text-nv-accent-soft" onClick={a.onCompare}>Compare several solvers in Studies →</button>
      </fieldset>
      <Section title="Operating point">
        <Field label="Speed" ariaLabel="Rotation speed" unit="rpm" value={inputs.rpm} onChange={(v) => set('rpm', v)} />
      </Section>
      <Section title="Airfoil and air data"><div ref={a.slotRef('data')} className="flex flex-col gap-2.5" /></Section>
    </>}
    content={<>
      <PolarCharts key={context?.selectedAsset?.id || 'none'} title="Polars the solver will use" points={context?.selectedAsset?.points}
        detail={context?.selectedAsset && `${context.selectedAsset.filename} · ${context.selectedAsset.airfoil}`} demonstration={context?.selectedAsset?.demonstration} />
      {current && <section aria-labelledby="model-notes" className="flex flex-col gap-3">
        <h2 id="model-notes" className="m-0 text-[15px] font-semibold">About {current.name}</h2>
        {current.description && <p className="m-0 max-w-3xl text-[13px] leading-relaxed text-nv-reference">{current.description}</p>}
        <ul className="m-0 flex flex-col gap-1.5 pl-0 text-[13px] text-nv-muted">
          <li className="flex items-center gap-2"><StatusDot tone={current.fidelity === 'experimental' ? 'warn' : 'accent'} />Maturity: <span className="capitalize">{current.fidelity}</span></li>
          {current.suitable_for && <li className="flex items-center gap-2"><StatusDot />Supported geometry: {current.suitable_for.join(', ')}</li>}
          {(current.warnings || []).map((warning) => <li key={warning} className="flex items-center gap-2 text-nv-warn-ink"><StatusDot tone="warn" />{warning}</li>)}
        </ul>
      </section>}
      <div ref={a.slotRef('explorer')} />
    </>}
    side={<>
      <PropellerViewport geometry={preview.mesh} busy={preview.busy} station={station} rootFraction={rootFraction} label="3D preview of the propeller to be analysed" />
      <LastRun context={context} onOpen={a.openRun} onRun={a.onRun} runDisabled={a.runDisabled} />
      <div ref={a.slotRef('run')} />
    </>} />;
}
