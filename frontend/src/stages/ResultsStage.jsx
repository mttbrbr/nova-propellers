import { AlertTriangle, Check, Download, Play } from 'lucide-react';
import { useState } from 'react';
import PropellerViewport from '../components/PropellerViewport.jsx';
import { formatValue, interpolate, stationSeries } from '../lib/blade.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import { Button, Disclosure, KeyValue, Metric, Section, Segmented, SelectField, StatusDot } from '../ui/controls.jsx';
import LineChart from '../ui/LineChart.jsx';

export const distributionFields = [
  { id: 'd_thrust_n', title: 'Local thrust', unit: 'N', short: 'dT' },
  { id: 'd_power_w', title: 'Local power', unit: 'W', short: 'dP' },
  { id: 'alpha_deg', title: 'Angle of attack', unit: '°', short: 'α' },
  { id: 'cl', title: 'Lift coefficient', unit: '', short: 'Cl' },
  { id: 'reynolds', title: 'Reynolds number', unit: '', short: 'Re' },
  { id: 'circulation', title: 'Circulation', unit: 'm²/s', short: 'Γ' },
];
const tableColumns = [['r_over_R', 'Span'], ['radius_m', 'r [m]'], ['chord_mm', 'c [mm]'], ['twist_deg', 'θ [°]'], ['alpha_deg', 'α [°]'], ['cl', 'Cl'], ['cd', 'Cd'],
  ['reynolds', 'Re'], ['circulation', 'Γ'], ['d_thrust_n', 'dT [N]'], ['d_power_w', 'dP [W]']];

export function downloadDiagnostics(analysis) {
  const payload = { exported_at: new Date().toISOString(), schema_version: analysis.schema_version || 'legacy', solver: analysis.solver || { id: analysis.model },
    operating_point: analysis.operating_point || null, performance: analysis.performance || analysis.summary || null, units: analysis.units || {},
    warnings: analysis.warnings || [], convergence: analysis.convergence || null };
  const url = URL.createObjectURL(new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `nova-${analysis.model || 'solver'}-diagnostics.json`; anchor.click();
  URL.revokeObjectURL(url);
}

const performanceOf = (analysis) => analysis?.performance || (analysis?.summary ? {
  thrust_n: analysis.summary.estimated_thrust_n, torque_nm: analysis.summary.torque_nm, power_w: analysis.summary.power_w,
  efficiency: analysis.summary.efficiency ?? analysis.summary.figure_of_merit } : {});

// Thrust and power coefficients from the run's own operating point and diameter.
function coefficients(analysis, diameter) {
  const p = performanceOf(analysis);
  const rpm = analysis?.operating_point?.rpm, rho = analysis?.operating_point?.air_density_kg_m3 ?? 1.225;
  if (!rpm || !diameter || p.thrust_n == null) return {};
  const n = rpm / 60;
  return { ct: p.thrust_n / (rho * n ** 2 * diameter ** 4), cp: p.power_w / (rho * n ** 3 * diameter ** 5) };
}

function ConvergenceDetails({ analysis }) {
  const convergence = analysis?.convergence;
  const diagnostics = convergence?.diagnostics;
  const history = diagnostics?.history || [];
  if (!convergence) return null;
  return <Disclosure title="Convergence details" summary={diagnostics?.classification || convergence.termination_reason}>
    <dl className="m-0 grid grid-cols-2 gap-4 md:grid-cols-3 2xl:grid-cols-6">
      <Metric size="md" label="Converged" value={convergence.converged ? 'yes' : 'no'} />
      <Metric size="md" label="Iterations" value={convergence.iterations} />
      <Metric size="md" label="Final residual" value={Number(convergence.residual).toExponential(2)} />
      <Metric size="md" label="Tolerance" value={Number(convergence.tolerance).toExponential(1)} />
      <Metric size="md" label="Classification" value={diagnostics?.classification || 'legacy'} />
      <Metric size="md" label="Relaxation" value={diagnostics ? `${diagnostics.relaxation_strategy} · ${Number(diagnostics.final_relaxation_factor).toFixed(3)}` : '—'} />
    </dl>
    {diagnostics && <p className="m-0 font-mono text-xs text-nv-muted">Total reduction {Number(diagnostics.total_reduction_ratio).toExponential(2)} · recent {Number(diagnostics.recent_reduction_ratio).toExponential(2)} · tail variation {Number(diagnostics.tail_variation_ratio).toFixed(4)}× · {diagnostics.history_sampling}</p>}
    {history.length > 0 && <div className="max-h-64 overflow-auto rounded-lg border border-nv-line">
      <table aria-label="Iteration history" className="w-full min-w-[860px] border-collapse font-mono text-xs tabular">
        <thead className="sticky top-0 bg-nv-panel text-nv-muted"><tr>{['Iteration', 'Residual', 'Axial', 'Tangential', 'Span', 'α', 'Re', 'Loss F', 'Relaxation'].map((h) => <th key={h} scope="col" className="px-3 py-2 text-right font-sans font-medium first:text-left">{h}</th>)}</tr></thead>
        <tbody>{history.map((row) => <tr key={row.iteration} className="border-t border-nv-line text-right">
          <td className="px-3 py-1.5 text-left">{row.iteration}</td>
          {[row.residual, row.axial_residual, row.tangential_residual].map((v, i) => <td key={i} className="px-3 py-1.5">{Number(v).toExponential(2)}</td>)}
          <td className="px-3 py-1.5">{formatValue(row.limiting_r_over_R)}</td><td className="px-3 py-1.5">{formatValue(row.limiting_alpha_deg)}</td><td className="px-3 py-1.5">{formatValue(row.limiting_reynolds)}</td>
          <td className="px-3 py-1.5">{formatValue(row.limiting_loss_factor)}</td><td className="px-3 py-1.5">{formatValue(row.relaxation_factor)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    <Button className="self-start" onClick={() => downloadDiagnostics(analysis)}><Download size={15} aria-hidden="true" />Export diagnostics JSON</Button>
  </Disclosure>;
}

// Report body shared by Results and the legacy archive viewer in Library.
export function ReportBody({ title, eyebrow = 'Technical report', viewing, analyses, analysis, onSelectAnalysis, geometry, compares = [], station, setStation, showAllStations, setShowAllStations }) {
  const stations = analysis?.stations?.length ? analysis.stations : (geometry?.stations || []).map((s) => ({ ...s, chord_mm: Number(s.chord_m) * 1000 }));
  const performance = performanceOf(analysis);
  // Overlaid runs or solver-comparison cases, shown under each metric and as extra curves.
  const sub = (field, digits) => compares.length ? compares.map((item) => `${item.label} ${formatValue(performanceOf(item.analysis)[field], digits)}`).join('\n') : undefined;
  const { ct, cp } = coefficients(analysis, geometry?.diameter_m);
  const convergence = analysis?.convergence;
  const nearest = stations.reduce((best, row, index) => Math.abs(Number(row.r_over_R) - station) < Math.abs(Number(stations[best]?.r_over_R ?? 99) - station) ? index : best, 0);
  const visibleRows = showAllStations ? stations.map((row, index) => [row, index]) : stations.map((row, index) => [row, index]).slice(Math.max(0, nearest - 2), nearest + 3);
  return <>
    <div className="flex flex-col gap-2">
      <p className="m-0 text-xs uppercase tracking-[0.08em] text-nv-muted">{eyebrow}</p>
      <h2 className="m-0 text-[22px] font-semibold">{title}</h2>
      <p className="m-0 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-nv-muted">
        {convergence && <span className={`inline-flex items-center gap-1.5 ${convergence.converged ? 'text-nv-ok-ink' : 'text-nv-warn-ink'}`}><StatusDot tone={convergence.converged ? 'ok' : 'warn'} />{convergence.converged ? `Converged in ${convergence.iterations} iterations` : `Not converged · ${convergence.termination_reason}`}</span>}
        {analysis && !convergence && <span className="inline-flex items-center gap-1.5"><StatusDot />No convergence data from this solver</span>}
        {analysis && <span>Curves {analysis.curve_source === 'native' ? 'provided by the solver' : 'reconstructed from global results'}</span>}
      </p>
      {viewing && <p className="m-0 font-mono text-xs text-nv-reference">{viewing}</p>}
    </div>
    {analyses.length > 1 && <div className="max-w-xl"><Segmented label="Analysis node" value={analysis?.node_id || analysis?.model} onChange={onSelectAnalysis}
      options={analyses.map((item) => [item.node_id || item.model, `${item.method || item.model} · ${item.fidelity || 'legacy'}`])} /></div>}
    {analysis ? <>
      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-5 border-y border-nv-line py-5 sm:grid-cols-3 2xl:grid-cols-6">
        <Metric label="Thrust" value={formatValue(performance.thrust_n, 4)} unit="N" sub={sub('thrust_n', 4)} />
        <Metric label="Torque" value={formatValue(performance.torque_nm, 3)} unit="N·m" sub={sub('torque_nm', 3)} />
        <Metric label="Power" value={formatValue(performance.power_w, 4)} unit="W" sub={sub('power_w', 4)} />
        <Metric label="Figure of merit" value={formatValue(performance.efficiency, 3)} sub={sub('efficiency', 3)} />
        <Metric label="Cᴛ" value={formatValue(ct, 3)} sub="T / ρn²D⁴" />
        <Metric label="Cᴘ" value={formatValue(cp, 3)} sub="P / ρn³D⁵" />
      </dl>
      {(analysis.warnings || []).length > 0 && <ul aria-label="Solver warnings" className="m-0 flex list-none flex-col gap-1.5 p-0 text-[13px] text-nv-warn-ink">{analysis.warnings.map((warning) => <li key={warning} className="flex items-center gap-2"><StatusDot tone="warn" />{warning}</li>)}</ul>}
      <section aria-labelledby="distributions-title">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
          <h3 id="distributions-title" className="m-0 text-[15px] font-semibold">Along the blade <span className="text-[13px] font-normal text-nv-muted">· selected span {station.toFixed(2)}</span></h3>
          {compares.length > 0 && <span className="flex flex-wrap gap-4 text-xs text-nv-muted"><span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3.5 bg-nv-accent" />This run</span>
            {compares.map((item) => <span key={item.label} className="inline-flex items-center gap-1.5"><span className={`w-3.5 border-t-2 ${item.dashed ? 'border-dashed' : ''}`} style={{ borderColor: item.color }} />{item.label}</span>)}</span>}
        </div>
        <div className="grid gap-x-8 gap-y-7 md:grid-cols-2 2xl:grid-cols-3">
          {distributionFields.map((field) => <LineChart key={field.id} title={field.title} unit={field.unit} height={180} selection={station} onSelect={setStation}
            series={[{ id: 'run', color: '#FF8533', points: stationSeries(stations, field.id) },
              ...compares.map((item) => ({ id: item.label, color: item.color, dashed: item.dashed, points: stationSeries(item.analysis?.stations, field.id) }))]} />)}
        </div>
      </section>
    </> : <p className="m-0 text-[13px] text-nv-muted">No saved analyses.</p>}
    {stations.length > 0 && <section aria-labelledby="stations-title">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 id="stations-title" className="m-0 text-[15px] font-semibold">Stations <span className="text-[13px] font-normal text-nv-muted">· {showAllStations ? `all ${stations.length}` : `around span ${station.toFixed(2)}`}</span></h3>
        <button type="button" className="text-[13px] text-nv-accent hover:text-nv-accent-soft" onClick={() => setShowAllStations(!showAllStations)}>{showAllStations ? 'Show around selection' : `All ${stations.length} stations →`}</button>
      </div>
      <div className={`overflow-auto ${showAllStations ? 'max-h-[420px]' : ''}`}>
        <table aria-label="Station results" className="w-full min-w-[900px] border-collapse font-mono text-[12.5px] tabular">
          <thead className="sticky top-0 bg-nv-canvas"><tr>{tableColumns.map(([, label]) => <th key={label} scope="col" className="px-2.5 pb-2.5 text-right font-sans text-xs font-medium text-nv-muted first:pl-0 first:text-left">{label}</th>)}</tr></thead>
          <tbody>{visibleRows.map(([row, index]) => <tr key={index} onClick={() => setStation(Number(row.r_over_R))}
            className={`cursor-pointer border-t border-nv-line text-right hover:bg-nv-raised ${index === nearest ? 'bg-nv-accent/[.08]' : ''}`}>
            {tableColumns.map(([key], column) => <td key={key} className={`px-2.5 py-2 first:pl-0 first:text-left ${column === 0 && index === nearest ? 'text-nv-accent' : ''}`}>{formatValue(row[key], 4)}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
    </section>}
    <ConvergenceDetails analysis={analysis} />
  </>;
}

function ResidualChart({ analysis }) {
  const history = analysis?.convergence?.diagnostics?.history || [];
  if (history.length < 2) return <p className="m-0 text-[13px] text-nv-muted">{analysis?.convergence ? 'Residual history not recorded for this run.' : 'This solver does not expose iterative convergence diagnostics.'}</p>;
  const series = (field, color, id) => ({ id, color, label: id, points: history.map((row) => ({ x: Number(row.iteration), y: Math.log10(Math.max(Number(row[field]), 1e-16)) })) });
  const last = history.at(-1).iteration;
  const tolerance = Math.log10(analysis.convergence.tolerance);
  const total = series('residual', '#F2F4F6', 'Total');
  return <LineChart title="Residual" unit="" height={190} xDomain={[0, last]} xTicks={[0, Math.round(last / 2), last]} xLabel="it" legend
    formatTick={(value) => `1e${Math.round(value)}`} formatReadout={(value) => (10 ** value).toExponential(2)}
    series={[total, series('axial_residual', '#FF8533', 'Axial'), series('tangential_residual', '#B49CFB', 'Tangential'),
      { id: 'tolerance', color: '#46D19A', dashed: true, width: 1.2, points: [{ x: 0, y: tolerance }, { x: last, y: tolerance }] }]} />;
}

function EmptyResults({ context, onRun, runDisabled, onNavigate }) {
  const asset = context?.selectedAsset;
  const items = [
    [true, 'Geometry', context?.geometry ? `r${context.geometry.geometry_revision}` : 'current draft', 'geometry', 'Edit'],
    [true, 'Solver', (context?.models || []).map((m) => m.toUpperCase()).join(' + ') || '—', 'analysis', 'Change'],
    [Boolean(asset) && !asset.demonstration, 'Airfoil data', asset ? `${asset.filename}${asset.demonstration ? ' · demonstration only' : ''}` : 'none selected', 'analysis', asset ? 'Change' : 'Select polars'],
  ];
  return <div className="flex h-full items-center justify-center py-10">
    <div className="w-full max-w-[560px]">
      <h2 className="m-0 text-[22px] font-semibold">No results yet</h2>
      <p className="m-0 mt-2.5 text-sm leading-relaxed text-nv-muted">Run the simulation to compute thrust, torque, power and the distributions along the blade. It will use:</p>
      <ul className="m-0 mt-7 list-none p-0">{items.map(([ready, label, value, stage, action]) => <li key={label} className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-3.5 border-t border-nv-line py-3.5 text-sm last:border-b">
        {ready ? <Check size={18} className="text-nv-ok" aria-label="Ready" /> : <AlertTriangle size={18} className="text-nv-warn" aria-label="Needs attention" />}
        <span>{label} <span className={ready ? 'text-nv-muted' : 'text-nv-warn-ink'}>{value}</span></span>
        <button type="button" className="text-[13px] text-nv-accent hover:text-nv-accent-soft" onClick={() => onNavigate(stage)}>{action}</button>
      </li>)}</ul>
      <div className="mt-7 flex items-center gap-4">
        <Button variant="primary" className="!h-10 !px-5" disabled={runDisabled} onClick={onRun}><Play size={14} fill="currentColor" aria-hidden="true" />Run now</Button>
        <span className="font-mono text-[12.5px] text-nv-muted">Ctrl+Enter</span>
      </div>
    </div>
  </div>;
}

export default function ResultsStage({ r }) {
  const { analyses, context, resultContext, station, setStation } = r;
  const [colorField, setColorField] = useState('d_thrust_n');
  const [compareId, setCompareId] = useState(null);
  const [showAllStations, setShowAllStations] = useState(false);
  const analysis = analyses.find((item) => (item.node_id || item.model) === r.reportModel) || analyses[0];
  const geometry = r.resultGeometry;
  const runId = resultContext?.runId;
  const candidates = (context?.projectRuns || []).filter((run) => run.id !== runId && run.state === 'succeeded' && run.result?.analyses?.length);
  const sourceSimulation = resultContext?.run?.simulation_id || context?.simulation?.id;
  const solverComparisons = (context?.projectRuns || []).filter((run) => run.comparison?.kind === 'solver' && run.state === 'succeeded' && run.comparison.source_simulation_id === sourceSimulation)
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  // The newest solver comparison of this simulation is overlaid until the user picks something else.
  const selectedCompare = compareId ?? (solverComparisons[0] && analysis ? `cmp:${solverComparisons[0].id}` : '');
  const compareRun = candidates.find((run) => run.id === selectedCompare);
  const comparisonRun = solverComparisons.find((run) => `cmp:${run.id}` === selectedCompare);
  const compares = comparisonRun
    ? (comparisonRun.result.cases || []).filter((sample) => sample.state === 'succeeded' && sample.result.analyses[0].model !== analysis?.model)
      .map((sample, index) => ({ label: sample.result.analyses[0].model.toUpperCase(), analysis: sample.result.analyses[0], color: ['#B49CFB', '#4CC9F0', '#46D19A'][index % 3] }))
    : compareRun ? [{ label: (compareRun.result.analyses[0].model || '').toUpperCase(), analysis: compareRun.result.analyses[0], color: '#C4CAD2', dashed: true }] : [];
  const field = distributionFields.find((item) => item.id === colorField);
  const series = stationSeries(analysis?.stations, colorField);
  const values = series.map((point) => point.y);
  const rootFraction = geometry?.stations?.length ? geometry.stations[0].radius_m / Math.max(geometry.diameter_m / 2, 1e-9) : 0.14;
  const atStation = series.length ? interpolate(series, station) : null;
  const viewing = resultContext ? `Viewing ${resultContext.simulationName}${resultContext.simulationRevision ? ` · r${resultContext.simulationRevision}` : ''} · ${resultContext.models.map((m) => m.toUpperCase()).join(' + ')} · ${resultContext.rpm} rpm · run ${resultContext.runId.slice(0, 8)}${resultContext.caseIndex != null ? ` · case ${resultContext.caseIndex + 1}` : ''}${resultContext.studyCase ? ` · ${resultContext.studyCase.parameter} = ${resultContext.studyCase.value} ${resultContext.studyCase.units || ''}` : ''}${resultContext.studyCase?.secondary_parameter ? ` · ${resultContext.studyCase.secondary_parameter} = ${resultContext.studyCase.secondary_value} ${resultContext.studyCase.secondary_units || ''}` : ''}` : null;
  const run = resultContext?.run;

  return <StageLayout inputsLabel="Runs and provenance" contentLabel="Performance" sideLabel="Blade colored by result"
    inputs={<>
      <StageTitle title="Results" detail="Frozen with the inputs of each run." />
      <Section title={context?.simulation ? `Runs of ${context.simulation.name}` : 'Runs'}>
        {(context?.simulationRuns || []).length ? <div className="-mx-2.5 flex flex-col gap-0.5">{context.simulationRuns.map((item) => <button key={item.id} type="button" aria-current={item.id === runId ? 'true' : undefined}
          onClick={() => r.openRun(item)} className={`grid grid-cols-[10px_minmax(0,1fr)] items-start gap-2.5 rounded-lg p-2.5 text-left hover:bg-nv-raised ${item.id === runId ? 'bg-nv-hover' : ''}`}>
          <StatusDot tone={item.state === 'succeeded' ? 'ok' : item.state === 'failed' ? 'err' : 'warn'} className="mt-1.5" />
          <span className="min-w-0"><span className="block text-[13px]">{formatValue(item.inputs?.rpm, 4)} rpm · geometry r{item.geometry_revision || '—'}</span>
            <span className="block font-mono text-xs text-nv-muted">{item.id.slice(0, 8)} · {item.state}</span></span>
        </button>)}</div> : <p className="m-0 text-[13px] text-nv-muted">No runs of this simulation yet.</p>}
      </Section>
      {analyses.length > 0 && <Section title="Compare with">
        <SelectField inline ariaLabel="Compare with run" value={selectedCompare} onChange={setCompareId}
          options={[['', 'Nothing'], ...solverComparisons.map((item) => [`cmp:${item.id}`, `Solver comparison · ${item.comparison.simulations.map((source) => source.workflow.nodes.find((n) => n.type === 'analysis')?.config?.model?.toUpperCase()).join(', ')}`]),
            ...candidates.map((item) => [item.id, `${item.simulation_name || item.name} · ${(item.result.analyses[0].model || '').toUpperCase()} · ${item.id.slice(0, 8)}`])]} />
      </Section>}
      {analysis && <Section title="Provenance">
        <KeyValue label="Solver"><span title={analysis.method}>{(analysis.model || analysis.method || '').toUpperCase()}</span> · <span className="capitalize">{analysis.fidelity || 'legacy'}</span></KeyValue>
        {run && <KeyValue label="Geometry"><span className="font-mono">r{run.geometry_revision || '—'} · {geometry?.stations?.length || '—'} stations</span></KeyValue>}
        <KeyValue label="Operating point"><span className="font-mono">{formatValue(analysis.operating_point?.rpm, 4)} rpm · ρ {formatValue(analysis.operating_point?.air_density_kg_m3)}</span></KeyValue>
        {run && <KeyValue label="Polars"><span className={run.polar_asset?.demonstration ? 'text-nv-warn-ink' : ''}>{run.polar_asset?.filename || (run.polar_asset_id ? 'imported' : 'not used')}</span></KeyValue>}
        <KeyValue label="Curves">{analysis.curve_source === 'native' ? 'from the solver' : 'reconstructed'}</KeyValue>
      </Section>}
      <div className="flex-1" />
      {analysis && <Section title="Export"><div className="grid grid-cols-3 gap-2">
        <Button className="!px-2" disabled={!runId} onClick={() => r.exportCsv(runId)}>CSV</Button>
        <Button className="!px-2" onClick={() => downloadDiagnostics(analysis)}>JSON</Button>
        <Button className="!px-2" disabled={!r.resultStlUrl} onClick={r.exportStl}>STL</Button>
      </div></Section>}
    </>}
    content={analyses.length ? <ReportBody title={resultContext?.simulationName || r.projectName || 'Current project'} viewing={viewing} analyses={analyses} analysis={analysis}
      onSelectAnalysis={r.setReportModel} geometry={geometry} compares={compares} station={station} setStation={setStation} showAllStations={showAllStations} setShowAllStations={setShowAllStations} />
      : <EmptyResults context={context} onRun={r.onRun} runDisabled={r.runDisabled} onNavigate={r.onNavigate} />}
    side={<>
      <PropellerViewport geometry={r.resultMesh || r.previewMesh} station={station} rootFraction={rootFraction}
        colorField={analysis && values.length ? { points: series, domain: [Math.min(...values), Math.max(...values)], label: `${field.title}${field.unit ? ` [${field.unit}]` : ''}`, unit: field.unit } : null}
        stationLabel={atStation != null ? `span ${station.toFixed(2)} · ${field.short} ${formatValue(atStation)}${field.unit ? ` ${field.unit}` : ''}` : null}
        overlay={analysis ? <Segmented size="sm" label="Color the blade by" value={colorField} onChange={setColorField} options={distributionFields.filter((f) => ['d_thrust_n', 'alpha_deg', 'reynolds', 'cl'].includes(f.id)).map((f) => [f.id, f.short])} /> : null}
        emptyMessage={analyses.length ? 'Loading the run geometry…' : 'After the first run the blade is colored by thrust, angle of attack, Reynolds number or Cl.'}
        label={analysis ? `Propeller colored by ${field.title.toLowerCase()}` : '3D preview of the propeller'} />
      {analysis && <section aria-labelledby="residual-title" className="flex flex-col gap-2">
        <h2 id="residual-title" className="m-0 text-[15px] font-semibold">Convergence</h2>
        <ResidualChart analysis={analysis} />
        {analysis.convergence?.diagnostics?.history?.at(-1)?.limiting_r_over_R != null && (() => {
          const last = analysis.convergence.diagnostics.history.at(-1);
          return <p className="m-0 text-[13px] text-nv-muted">Limiting station <span className="font-mono text-nv-ink">span {formatValue(last.limiting_r_over_R)}</span> · {last.limiting_component} · Re <span className={`font-mono ${last.polar_context?.reynolds_clipped ? 'text-nv-warn-ink' : 'text-nv-ink'}`}>{formatValue(last.limiting_reynolds)}{last.polar_context?.reynolds_clipped ? ' clipped' : ''}</span></p>;
        })()}
      </section>}
    </>} />;
}
