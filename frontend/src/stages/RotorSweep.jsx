import { X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { request } from '../backend.js';
import { formatValue, niceTicks } from '../lib/blade.js';
import LineChart from '../ui/LineChart.jsx';
import { Button, Notice, SelectField, StatusDot } from '../ui/controls.jsx';

// Sweep lens of the design sheet: vary one input of the current rotor, check real
// limits at every point, refine the feasible points with a higher-fidelity model
// where one exists, and adopt the chosen value back into the design.
const fmt = (value, digits = 4) => value == null || Number.isNaN(Number(value)) ? '—' : formatValue(Number(value), digits);
const turbine = (family) => family === 'hawt' || family === 'vawt';
const FIELD_LABELS = {
  'geometry.radius_m': 'Tip radius [m]', 'geometry.hub_radius_m': 'Hub radius [m]', 'geometry.design_tsr': 'Design λ', 'geometry.pitch_deg': 'Pitch [deg]',
  'geometry.blades': 'Blades', 'geometry.height_m': 'Height [m]', 'geometry.chord_m': 'Chord [m]', 'geometry.blade_pitch_deg': 'Blade pitch [deg]',
  'geometry.pitch_axis_fraction': 'Pitch axis [x/c]', 'geometry.diameter_m': 'Diameter [m]', 'geometry.area_ratio': 'Area ratio AE/A0',
  'geometry.pitch_ratio': 'Pitch ratio P/D', 'geometry.hub_ratio': 'Hub ratio', 'operating.velocity_m_s': 'Free stream [m/s]',
  'operating.tip_speed_ratio': 'Tip-speed ratio λ', 'operating.rpm': 'Rotation [rpm]', 'operating.advance_ratio': 'Advance ratio J',
  'marine.shaft_depth_m': 'Shaft immersion [m]', 'marine.wake_fraction': 'Wake fraction w', 'marine.thrust_deduction': 'Thrust deduction t',
};
const QUANTITIES = {
  turbine: [['power_w', 'Power [W]'], ['CP', 'Cp'], ['thrust_n', 'Thrust [N]'], ['streamwise_force_n', 'Streamwise force [N]'], ['torque_nm', 'Torque [N·m]'], ['tip_speed_m_s', 'Tip speed [m/s]']],
  propeller: [['thrust_n', 'Thrust [N]'], ['efficiency', 'Efficiency'], ['open_water_efficiency', 'Open-water η₀'], ['KT', 'KT'], ['power_w', 'Power [W]'],
    ['cavitation_number_07R', 'σ at 0.7R'], ['thrust_loading_tau_c', 'Burrill τc'], ['keller_margin', 'Keller margin']],
};
const BLOCK_TYPE = { hawt: 'rotor_hawt', vawt: 'rotor_vawt', marine: 'rotor_marine', propeller: 'rotor_propeller' };

function sweepableFields(spec) {
  return ['geometry', 'operating', 'marine'].flatMap((group) => Object.entries(spec[group] || {})
    .filter(([, value]) => typeof value === 'number').map(([key]) => `${group}.${key}`)).filter((path) => FIELD_LABELS[path]);
}
const valueAt = (spec, path) => path.split('.').reduce((value, key) => value?.[key], spec);

// The same study as a block workflow: rotor → operating point → corrections → sweep → report.
export function sweepWorkflow(family, spec, path, values, checks) {
  const vertical = family === 'vawt';
  const nodes = [
    { id: 'rotor', type: BLOCK_TYPE[family], config: { geometry: spec.geometry, section: spec.section, method: spec.method, bindings: {} }, position: { x: 0, y: 0 } },
    { id: 'operating', type: 'operating_point', config: { fluid: spec.fluid, operating: spec.operating, bindings: {} }, position: { x: 270, y: 0 } },
    { id: 'corrections', type: vertical ? 'corrections_vertical' : 'corrections_axial', config: spec.corrections, position: { x: 540, y: 0 } },
    ...(family === 'marine' ? [{ id: 'hull', type: 'marine_conditions', config: spec.marine, position: { x: 810, y: 0 } }] : []),
    { id: 'sweep', type: 'sweep', config: { path, values, checks, start: values[0], stop: values.at(-1), count: values.length }, position: { x: 0, y: 330 } },
    { id: 'report', type: 'report', config: { title: `Sweep of ${FIELD_LABELS[path] || path}` }, position: { x: 270, y: 330 } },
  ];
  const chain = ['rotor', 'operating', 'corrections', ...(family === 'marine' ? ['hull'] : []), 'sweep'];
  const edges = chain.slice(1).map((target, index) => ({ source: chain[index], source_port: 'spec', target, target_port: 'spec' }));
  edges.push({ source: 'sweep', source_port: 'table', target: 'report', target_port: 'b' });
  return { schema_version: 2, kind: 'blocks', name: `Sweep · ${FIELD_LABELS[path] || path}`, nodes, edges };
}

export default function RotorSweep({ family, spec, catalog, presets, targets, onAdopt, onOpenWorkflow }) {
  const fields = useMemo(() => sweepableFields(spec), [spec]);
  const [path, setPath] = useState(() => fields.includes('geometry.radius_m') ? 'geometry.radius_m' : fields.includes('geometry.diameter_m') ? 'geometry.diameter_m' : fields[0]);
  const current = Number(valueAt(spec, path)) || 1;
  const [range, setRange] = useState({ from: +(current * 0.8).toPrecision(3), to: +(current * 1.4).toPrecision(3), points: 7 });
  const methods = family === 'vawt' ? catalog.vawt_methods : [{ id: 'bemt', label: 'BEMT' }];
  const [method, setMethod] = useState(family === 'vawt' ? 'single_streamtube' : 'bemt');
  const familyPresets = (presets || []).filter((p) => p.kinds.includes(family));
  // Limits start from the domain presets, seeded with the Sizing requirements where they exist.
  const seed = (p) => ({ preset: p.id, value: p.id === 'rated_power' && spec.requirements?.rated_power_w ? spec.requirements.rated_power_w
    : p.id === 'min_thrust' && spec.requirements?.effective_thrust_n ? spec.requirements.effective_thrust_n : Number(Number(p.value).toPrecision(4)) });
  const [checks, setChecks] = useState(() => familyPresets.slice(0, 2).map(seed));
  const [result, setResult] = useState(null);
  const [refined, setRefined] = useState(null);
  const [refineMethod, setRefineMethod] = useState('double_multiple_streamtube');
  const [quantity, setQuantity] = useState(turbine(family) ? 'power_w' : 'thrust_n');
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const changePath = (next) => {
    setPath(next); setResult(null); setRefined(null); setSelected(null);
    const value = Number(valueAt(spec, next)) || 1;
    setRange({ from: +(value * 0.8).toPrecision(3), to: +(value * 1.4).toPrecision(3), points: 7 });
  };
  const values = () => {
    const count = Math.max(2, Math.min(41, Math.round(range.points) || 2));
    return Array.from({ length: count }, (_, i) => +(range.from + (range.to - range.from) * i / (count - 1)).toPrecision(6));
  };
  const call = async (body) => request('/v1/rotors/sweep', { spec, path, checks, ...body });
  const runSweep = async () => {
    setBusy(true); setError(''); setRefined(null); setSelected(null);
    try { setResult(await call({ values: values(), method })); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const feasible = (result?.rows || []).filter((row) => row.state === 'succeeded' && (checks.length === 0 || row.feasible));
  const refine = async () => {
    setBusy(true); setError('');
    try { setRefined(await call({ values: feasible.map((row) => row.value), method: refineMethod })); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const refinedAt = (value) => refined?.rows.find((row) => row.value === value && row.state === 'succeeded');
  const options = (QUANTITIES[turbine(family) ? 'turbine' : 'propeller']).filter(([key]) => (result?.rows || []).some((row) => row[key] != null));
  const quantityKey = options.some(([key]) => key === quantity) ? quantity : options[0]?.[0];
  const pointsOf = (rows) => (rows || []).filter((row) => row.state === 'succeeded' && row[quantityKey] != null).map((row) => ({ x: row.value, y: row[quantityKey] }));
  const series = result ? [{ id: 'sweep', label: methods.find((m) => m.id === result.method)?.label?.split(' (')[0] || 'BEMT', color: '#FF8533', points: pointsOf(result.rows) },
    ...(refined ? [{ id: 'refined', label: methods.find((m) => m.id === refined.method)?.label?.split(' (')[0], color: '#B49CFB', dashed: true, points: pointsOf(refined.rows) }] : [])] : [];
  const xs = (result?.rows || []).map((row) => row.value);
  const domain = xs.length ? [Math.min(...xs), Math.max(...xs)] : [0, 1];
  const ticks = niceTicks(domain[0], domain[1], 4).filter((t) => t >= domain[0] - 1e-9 && t <= domain[1] + 1e-9);
  const deltas = refined ? feasible.map((row) => { const fine = refinedAt(row.value); return fine && row.power_w ? fine.power_w / row.power_w - 1 : null; }).filter((d) => d != null) : [];
  const meanDelta = deltas.length ? deltas.reduce((a, b) => a + b, 0) / deltas.length : null;
  const changedFeasibility = refined ? refined.rows.filter((row) => row.state === 'succeeded' && row.feasible === false).length : 0;
  // Second column: power, or thrust when power is already the plotted quantity.
  const secondary = quantityKey === 'power_w' ? ['thrust_n', turbine(family) ? 'Thrust [N]' : 'Thrust [N]'] : ['power_w', 'Power [W]'];
  const pick = selected != null ? (result?.rows || []).find((row) => row.value === selected) : null;
  const presetById = Object.fromEntries((presets || []).map((p) => [p.id, p]));

  const content = <div className="flex min-w-0 flex-1 flex-col gap-6 px-6 py-6 lg:px-10" role="region" aria-label="Sweep">
    <div className="flex flex-wrap items-end gap-3 text-[13px]">
      <label className="flex flex-col gap-1 text-xs text-nv-muted">Vary
        <select aria-label="Swept input" value={path} onChange={(e) => changePath(e.target.value)} className="h-[34px] rounded-md border border-nv-edge bg-nv-chrome px-2.5 text-[13px] text-nv-ink">
          {fields.map((field) => <option key={field} value={field} className="bg-nv-panel">{FIELD_LABELS[field]}</option>)}</select></label>
      {[['from', 'From'], ['to', 'To'], ['points', 'Points']].map(([key, label]) => <label key={key} className="flex flex-col gap-1 text-xs text-nv-muted">{label}
        <input aria-label={`Sweep ${label.toLowerCase()}`} type="number" step="any" value={range[key]} onChange={(e) => setRange({ ...range, [key]: Number(e.target.value) })}
          className="h-[34px] w-24 rounded-md border border-nv-edge bg-nv-chrome px-2.5 font-mono text-[13px] text-nv-ink focus:border-nv-accent focus:outline-none" /></label>)}
      <label className="flex flex-col gap-1 text-xs text-nv-muted">Model
        <select aria-label="Sweep model" value={method} onChange={(e) => setMethod(e.target.value)} disabled={methods.length === 1}
          className="h-[34px] rounded-md border border-nv-edge bg-nv-chrome px-2.5 text-[13px] text-nv-ink disabled:opacity-60">
          {methods.map((m) => <option key={m.id} value={m.id} className="bg-nv-panel">{m.label.split(' (')[0]}</option>)}</select></label>
      <Button variant="primary" disabled={busy || !path} onClick={runSweep}>{busy && !refined ? 'Running…' : 'Run sweep'}</Button>
    </div>
    <div className="flex flex-wrap items-center gap-2 text-[13px]">
      <span className="text-xs text-nv-muted">Limits</span>
      {checks.map((check, index) => { const preset = presetById[check.preset]; return <span key={check.preset} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-nv-hover pl-3 pr-1.5">
        <span>{preset?.label}</span><span className="font-mono text-nv-muted">{preset?.operator}</span>
        <input aria-label={`Limit ${preset?.label}`} type="number" step="any" value={check.value} onChange={(e) => setChecks(checks.map((c, i) => i === index ? { ...c, value: Number(e.target.value) } : c))}
          className="h-6 w-20 rounded border border-transparent bg-transparent px-1 font-mono text-[12.5px] hover:border-nv-edge focus:border-nv-accent focus:outline-none" />
        <span className="text-xs text-nv-muted">{preset?.unit !== '-' ? preset?.unit : ''}</span>
        <button type="button" aria-label={`Remove limit ${preset?.label}`} className="grid h-5 w-5 place-items-center rounded-full text-nv-muted hover:bg-nv-active hover:text-nv-ink" onClick={() => setChecks(checks.filter((_, i) => i !== index))}><X size={12} aria-hidden="true" /></button>
      </span>; })}
      <select aria-label="Add limit" value="" onChange={(e) => { const preset = presetById[e.target.value]; if (preset) setChecks([...checks, seed(preset)]); }}
        className="h-8 rounded-full border border-dashed border-nv-edge-strong bg-transparent px-3 text-xs text-nv-muted">
        <option value="">+ limit</option>{familyPresets.filter((p) => !checks.some((c) => c.preset === p.id)).map((p) => <option key={p.id} value={p.id} className="bg-nv-panel">{p.label}</option>)}</select>
    </div>
    {error && <Notice tone="err" role="alert">{error}</Notice>}
    {!result ? <div className="grid min-h-[300px] place-items-center rounded-lg border border-dashed border-nv-edge text-[13px] text-nv-muted">Choose what to vary and run the sweep. The design is not changed until you adopt a point.</div> : <>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="m-0 text-[17px] font-semibold">{options.find(([key]) => key === quantityKey)?.[1]} vs {FIELD_LABELS[path]}</h2>
        <span className="flex items-center gap-3 text-[13px] text-nv-muted">{feasible.length} of {result.rows.length} feasible{refined ? ` · ${refined.rows.length} refined` : ''}
          <SelectField inline ariaLabel="Plotted quantity" value={quantityKey} onChange={setQuantity} options={options} /></span>
      </div>
      <LineChart title={options.find(([key]) => key === quantityKey)?.[1]} series={series} legend height={300} xDomain={domain} xTicks={ticks.length > 1 ? ticks : domain}
        xLabel="" selection={selected} onSelect={(x) => { const near = result.rows.reduce((best, row) => Math.abs(row.value - x) < Math.abs(best.value - x) ? row : best, result.rows[0]); setSelected(near.value); }}
        ariaLabel={`Sweep of ${FIELD_LABELS[path]}`} />
      <div className="overflow-x-auto"><table aria-label="Sweep results" className="w-full text-left text-[13px] tabular-nums">
        <thead className="text-xs text-nv-muted"><tr>{[FIELD_LABELS[path], options.find(([key]) => key === quantityKey)?.[1], secondary[1], refined ? 'Refined' : null, 'Limits', ''].filter((h) => h !== null).map((h, i) => <th key={i} className="px-2 py-2 font-normal">{h}</th>)}</tr></thead>
        <tbody>{result.rows.map((row) => { const fine = refinedAt(row.value); const ok = row.state === 'succeeded' && (checks.length === 0 || row.feasible);
          return <tr key={row.value} className={`border-t border-nv-line ${row.value === selected ? 'bg-nv-raised' : ''} ${ok ? '' : 'text-nv-muted'}`}>
            <td className="px-2 py-2 font-mono">{fmt(row.value)}</td>
            <td className="px-2 py-2 font-mono">{row.state === 'succeeded' ? fmt(row[quantityKey]) : '—'}</td>
            <td className="px-2 py-2 font-mono">{fmt(row[secondary[0]] ?? row.streamwise_force_n)}</td>
            {refined && <td className="px-2 py-2 font-mono text-nv-series2">{fine ? fmt(fine[quantityKey]) : '—'}</td>}
            <td className="px-2 py-2">{row.state !== 'succeeded' ? <span className="text-nv-err-ink">{row.error}</span>
              : ok ? <span className="inline-flex items-center gap-1.5 text-nv-ok-ink"><StatusDot tone="ok" />feasible</span>
                : <span className="text-nv-warn-ink">{row.violations.join(', ')}</span>}</td>
            <td className="px-2 py-2 text-right">{row.state === 'succeeded' && <button type="button" className="text-nv-accent hover:text-nv-accent-soft" onClick={() => setSelected(row.value)}>Select</button>}</td>
          </tr>; })}</tbody></table></div>
    </>}
  </div>;

  const side = <div className="flex flex-col gap-5">
    <section aria-label="Refine" className="flex flex-col gap-3 rounded-[10px] border border-nv-series2/60 p-4">
      <h2 className="m-0 text-[14px] font-semibold">Refine with higher fidelity</h2>
      {family === 'vawt' ? <>
        <p className="m-0 text-[13px] leading-relaxed text-nv-muted">Explore with a fast model, then re-run the feasible points with a more complete one.</p>
        <SelectField label="Refine with" ariaLabel="Refinement model" value={refineMethod} onChange={setRefineMethod}
          options={catalog.vawt_methods.filter((m) => m.id !== result?.method).map((m) => [m.id, m.label.split(' (')[0]])} />
        <Button disabled={busy || !feasible.length} onClick={refine}>{busy && result ? 'Refining…' : `Refine ${feasible.length} feasible point${feasible.length === 1 ? '' : 's'}`}</Button>
        {refined && <div className="grid grid-cols-[1fr_auto] gap-y-1.5 text-[13px]">
          <span className="text-nv-muted">Mean Δ power</span><span className="font-mono text-nv-warn-ink">{meanDelta == null ? '—' : `${meanDelta >= 0 ? '+' : ''}${(meanDelta * 100).toFixed(1)} %`}</span>
          <span className="text-nv-muted">Points no longer feasible</span><span className="font-mono">{changedFeasibility}</span>
        </div>}
      </> : <p className="m-0 text-[13px] leading-relaxed text-nv-muted">Only BEMT exists for this rotor today, so there is nothing higher to refine with. A free-vortex wake model is planned.</p>}
    </section>
    <section aria-label="Selected point" className="flex flex-col gap-3 rounded-[10px] border border-nv-line p-4">
      <h2 className="m-0 text-[14px] font-semibold">{pick ? `Selected · ${FIELD_LABELS[path]} ${fmt(pick.value)}` : 'Selected point'}</h2>
      {pick ? <>
        <dl className="m-0 grid grid-cols-3 gap-3">{(turbine(family) ? [['Power', pick.power_w, 'W'], ['Cp', pick.CP, ''], ['Thrust', pick.thrust_n ?? pick.streamwise_force_n, 'N']]
          : [['Thrust', pick.thrust_n, 'N'], ['η', pick.open_water_efficiency ?? pick.efficiency, ''], ['Power', pick.power_w, 'W']]).map(([label, value, unit]) =>
          <div key={label}><dt className="text-xs text-nv-muted">{label}</dt><dd className="m-0 mt-1 font-mono text-[17px]">{fmt(value)} <span className="text-xs text-nv-muted">{unit}</span></dd></div>)}</dl>
        <Button variant="primary" onClick={() => onAdopt(path, pick.value)}>Adopt {fmt(pick.value)} into the design</Button>
        <p className="m-0 text-xs text-nv-muted">Adopting changes {FIELD_LABELS[path].toLowerCase()} in the open simulation; save or run to keep it.</p>
      </> : <p className="m-0 text-[13px] text-nv-muted">Select a row or click the chart.</p>}
    </section>
    <Button disabled={!path} onClick={() => onOpenWorkflow(sweepWorkflow(family, spec, path, values(), checks))}>Open as workflow</Button>
  </div>;

  return <>
    {targets.content && createPortal(content, targets.content)}
    {targets.side && createPortal(side, targets.side)}
  </>;
}
