import { useEffect, useState } from 'react';
import { request } from '../backend.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import LineChart from '../ui/LineChart.jsx';
import { Button, Disclosure, Field, KeyValue, Metric, Notice, Section, Segmented, SelectField } from '../ui/controls.jsx';
import { formatValue, niceTicks } from '../lib/blade.js';

const kinds = [['hawt', 'HAWT'], ['vawt', 'VAWT'], ['propeller', 'Propeller'], ['marine', 'Marine']];
const turbine = (kind) => kind === 'hawt' || kind === 'vawt';
const fmt = (value, digits = 4) => value == null || Number.isNaN(value) ? '—' : formatValue(value, digits);

// Geometry fields per rotor family: [key, label, unit, step].
const geometryFields = {
  hawt: [['blades', 'Blades', '', 1], ['radius_m', 'Tip radius', 'm'], ['hub_radius_m', 'Hub radius', 'm'], ['design_tsr', 'Design λ', ''], ['pitch_deg', 'Pitch', 'deg']],
  vawt: [['blades', 'Blades', '', 1], ['radius_m', 'Radius', 'm'], ['height_m', 'Height', 'm'], ['chord_m', 'Chord', 'm'], ['blade_pitch_deg', 'Blade pitch', 'deg'], ['pitch_axis_fraction', 'Pitch axis', 'x/c']],
  propeller: [['blades', 'Blades', '', 1], ['diameter_m', 'Diameter', 'm'], ['hub_ratio', 'Hub ratio', 'r/R'], ['pitch_ratio', 'Pitch ratio', 'P/D'], ['pitch_deg', 'Collective', 'deg']],
  marine: [['blades', 'Blades', '', 1], ['diameter_m', 'Diameter', 'm'], ['area_ratio', 'Area ratio', 'AE/A0'], ['pitch_ratio', 'Pitch ratio', 'P/D'], ['hub_ratio', 'Hub ratio', 'r/R'], ['pitch_deg', 'Pitch offset', 'deg']],
};
const vawtExtras = [['struts_per_blade', 'Struts/blade', '', 1], ['strut_chord_m', 'Strut chord', 'm'], ['strut_cd', 'Strut Cd', ''], ['shaft_diameter_m', 'Shaft dia.', 'm'], ['shaft_cd', 'Shaft Cd', '']];
const marineFields = [['shaft_depth_m', 'Shaft depth', 'm'], ['wake_fraction', 'Wake w', ''], ['thrust_deduction', 'Thrust ded. t', ''], ['relative_rotative_efficiency', 'ηR', ''], ['keller_k', 'Keller K', '']];
const correctionLabels = {
  tip_loss: 'Tip loss', hub_loss: 'Hub loss', high_induction: 'High induction', rotational_augmentation: '3-D rotation',
  compressibility: 'Compressibility', finite_aspect_ratio: 'Finite AR (tip)', flow_curvature: 'Flow curvature',
  dynamic_stall: 'Dynamic stall', strut_drag: 'Strut drag', shaft_wake: 'Shaft wake (hub)',
};
const optionLabel = (value) => typeof value === 'boolean' ? (value ? 'On' : 'Off') : String(value).replaceAll('_', ' ');
const ticksFor = (lo, hi) => { const t = niceTicks(lo, hi, 4).filter((v) => v >= lo - 1e-9 && v <= hi + 1e-9); return t.length >= 2 ? t : [lo, hi]; };

function useCatalog() {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { request('/v1/rotors/catalog').then(setCatalog).catch((e) => setError(e.message)); }, []);
  return [catalog, error];
}

export default function RotorsWorkspace() {
  const [catalog, catalogError] = useCatalog();
  const [kind, setKind] = useState('hawt');
  const [specs, setSpecs] = useState({});
  const [curveRange, setCurveRange] = useState({});
  const [result, setResult] = useState(null);
  const [curve, setCurve] = useState(null);
  const [reference, setReference] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const spec = specs[kind] || catalog?.defaults?.[kind];
  const update = (group, key, value) => setSpecs((all) => {
    const current = all[kind] || catalog.defaults[kind];
    return { ...all, [kind]: key == null ? { ...current, [group]: value } : { ...current, [group]: { ...current[group], [key]: value } } };
  });
  const variable = turbine(kind) ? 'tip_speed_ratio' : 'advance_ratio';
  const range = curveRange[kind] || (turbine(kind) ? { start: 1, stop: kind === 'vawt' ? 7 : 13, points: 25 } : { start: 0.05, stop: kind === 'marine' ? 1.1 : 0.9, points: 25 });

  const run = async () => {
    setBusy(true); setError('');
    try {
      const values = Array.from({ length: range.points }, (_, i) => range.start + (range.stop - range.start) * i / (range.points - 1));
      const [point, sweep] = await Promise.all([request('/v1/rotors/analyze', { spec }), request('/v1/rotors/curve', { spec, variable, values })]);
      setResult(point); setCurve(sweep);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  // Results describe the specification they were computed for; switching family clears them.
  useEffect(() => { setResult(null); setCurve(null); setReference(null); }, [kind]);

  if (!spec) return <StageLayout inputsLabel="Rotor inputs" contentLabel="Rotor performance" inputs={<StageTitle title="Rotors" detail="Loading models…" />}
    content={catalogError ? <Notice tone="err" role="alert">{catalogError}</Notice> : null} />;

  const operating = spec.operating || {};
  const setOperating = (key, value) => update('operating', null, { ...operating, [key]: value });
  const corrections = turbine(kind) && kind === 'vawt' ? catalog.vertical_corrections : catalog.axial_corrections;

  const inputs = <>
    <StageTitle title="Rotors" detail="Momentum models for wind, tidal and propulsion rotors, with selectable corrections." />
    <Segmented label="Rotor family" value={kind} options={kinds} onChange={setKind} />
    <Section title="Geometry">
      {geometryFields[kind].map(([key, label, unit, step]) => <Field key={key} label={label} unit={unit} step={step || 'any'}
        value={spec.geometry[key] ?? ''} onChange={(v) => update('geometry', key, v)} />)}
      {kind === 'vawt' && <SelectField label="Blade shape" value={spec.geometry.shape} options={[['straight', 'Straight (H-rotor)'], ['troposkien', 'Troposkien (Φ-rotor)']]}
        onChange={(v) => update('geometry', 'shape', v)} />}
      <SelectField label="Section" value={spec.section.name} options={catalog.sections.map((s) => [s, s])}
        onChange={(v) => update('section', null, { name: v })} />
    </Section>
    <Section title="Operating point">
      <SelectField label="Fluid" value={spec.fluid.preset} options={catalog.fluids.map((f) => [f, optionLabel(f)])}
        onChange={(v) => update('fluid', null, { preset: v })} />
      {turbine(kind) ? <>
        <Field label="Free stream" unit="m/s" value={operating.velocity_m_s ?? ''} onChange={(v) => setOperating('velocity_m_s', v)} />
        <Field label="Tip-speed ratio" unit="λ" value={operating.tip_speed_ratio ?? ''} onChange={(v) => setOperating('tip_speed_ratio', v)} />
      </> : <>
        <Field label="Rotation" unit="rpm" value={operating.rpm ?? ''} onChange={(v) => setOperating('rpm', v)} />
        <Field label="Advance ratio" unit="J" value={operating.advance_ratio ?? ''} onChange={(v) => setOperating('advance_ratio', v)} />
      </>}
    </Section>
    <Section title="Method">
      {kind === 'vawt'
        ? <SelectField label="Streamtube model" ariaLabel="VAWT method" value={spec.method} options={catalog.vawt_methods.map((m) => [m.id, m.label])} onChange={(v) => update('method', null, v)} />
        : <p className="m-0 text-[13px] text-nv-muted">Blade-element momentum, solved per station with a bracketed 1-D residual.</p>}
    </Section>
    <Disclosure title="Corrections" summary={Object.entries(spec.corrections).filter(([, v]) => v && v !== 'none').length + ' active'} defaultOpen>
      {Object.entries(corrections).map(([key, options]) => <SelectField key={key} label={correctionLabels[key] || key} ariaLabel={`Correction ${key}`}
        value={String(spec.corrections[key])} options={options.map((o) => [String(o), optionLabel(o)])}
        onChange={(v) => update('corrections', key, typeof options[0] === 'boolean' ? v === 'true' : v)} />)}
    </Disclosure>
    {kind === 'vawt' && <Disclosure title="Struts & shaft" summary="parasitic losses">
      {vawtExtras.map(([key, label, unit, step]) => <Field key={key} label={label} unit={unit} step={step || 'any'} value={spec.geometry[key] ?? ''} onChange={(v) => update('geometry', key, v)} />)}
    </Disclosure>}
    {kind === 'marine' && <Disclosure title="Hull & immersion" summary={`w ${spec.marine.wake_fraction} · t ${spec.marine.thrust_deduction}`}>
      {marineFields.map(([key, label, unit]) => <Field key={key} label={label} unit={unit} value={spec.marine[key] ?? ''} onChange={(v) => update('marine', key, v)} />)}
    </Disclosure>}
    <Disclosure title="Curve range" summary={`${turbine(kind) ? 'λ' : 'J'} ${range.start}–${range.stop}`}>
      {[['start', 'From'], ['stop', 'To'], ['points', 'Points']].map(([key, label]) => <Field key={key} label={label} step={key === 'points' ? 1 : 'any'}
        value={range[key]} onChange={(v) => setCurveRange((all) => ({ ...all, [kind]: { ...range, [key]: v } }))} />)}
    </Disclosure>
    <div className="flex gap-2"><Button variant="primary" onClick={run} disabled={busy}>{busy ? 'Computing…' : 'Analyse rotor'}</Button>
      <Button disabled={!curve} onClick={() => setReference({ curve, label: describeCorrections(spec.corrections) })}>Keep as reference</Button></div>
    {error && <Notice tone="err" role="alert">{error}</Notice>}
  </>;

  return <StageLayout inputsLabel="Rotor inputs" contentLabel="Rotor performance" sideLabel="Rotor results"
    inputs={inputs}
    content={<PerformanceCurves kind={kind} curve={curve} reference={reference} operating={result} range={range} variable={variable} />}
    side={result ? <OperatingPoint kind={kind} result={result} /> : <p className="m-0 text-[13px] text-nv-muted">Run the analysis to see the operating point, loads and distributions.</p>} />;
}

function describeCorrections(c) {
  return Object.entries(c).filter(([, v]) => v && v !== 'none').map(([k, v]) => v === true ? correctionLabels[k] : `${correctionLabels[k]}: ${optionLabel(v)}`).join(', ') || 'no corrections';
}

function curveSeries(curve, field, color, extra = {}) {
  const x = curve.variable;
  return { id: `${field}-${color}`, color, points: curve.rows.filter((r) => r.state === 'succeeded' && r[field] != null).map((r) => ({ x: r[x], y: r[field] })), ...extra };
}

function PerformanceCurves({ kind, curve, reference, operating, range, variable }) {
  const xDomain = [Number(range.start), Number(range.stop)];
  const xTicks = ticksFor(xDomain[0], xDomain[1]);
  const xLabel = variable === 'tip_speed_ratio' ? 'λ' : 'J';
  const at = operating ? (variable === 'tip_speed_ratio' ? operating.coefficients.TSR : operating.coefficients.J) : null;
  const failed = curve?.rows.filter((r) => r.state !== 'succeeded').length || 0;
  const charts = (() => {
    if (!curve) return [];
    if (turbine(kind)) return [
      { title: 'Power coefficient Cp', unit: '', series: [curveSeries(curve, 'CP', '#4CC9F0', { label: 'Cp' }),
        { id: 'betz', label: 'Betz 16/27', color: '#C4CAD2', dashed: true, width: 1.2, points: [{ x: xDomain[0], y: 16 / 27 }, { x: xDomain[1], y: 16 / 27 }] },
        ...(reference ? [curveSeries(reference.curve, 'CP', '#B49CFB', { label: 'Reference', dashed: true })] : [])] },
      { title: 'Thrust coefficient CT', unit: '', series: [curveSeries(curve, 'CT', '#F2A93B', { label: 'CT' }),
        ...(reference ? [curveSeries(reference.curve, 'CT', '#B49CFB', { label: 'Reference', dashed: true })] : [])] },
      { title: 'Torque coefficient CQ', unit: '', series: [curveSeries(curve, 'CQ', '#46D19A', { label: 'CQ' })] },
    ];
    const eta = kind === 'marine' ? 'open_water_efficiency' : 'efficiency';
    return [
      { title: 'Open-water diagram', unit: 'KT · 10KQ · η', series: [curveSeries(curve, 'KT', '#4CC9F0', { label: 'KT' }),
        { ...curveSeries(curve, 'KQ', '#F2A93B', { label: '10 KQ' }), points: curveSeries(curve, 'KQ', '#F2A93B').points.map((p) => ({ ...p, y: 10 * p.y })) },
        curveSeries(curve, eta, '#46D19A', { label: 'η' }),
        ...(reference ? [curveSeries(reference.curve, eta, '#B49CFB', { label: 'Reference η', dashed: true })] : [])] },
      { title: 'Power coefficient CP = P/(ρn³D⁵)', unit: '', series: [curveSeries(curve, 'CP_prop', '#4CC9F0', { label: 'CP' })] },
    ];
  })();
  return <>
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><h1 className="m-0 text-lg font-semibold">{turbine(kind) ? 'Cp – λ performance' : 'Open-water performance'}</h1>
        <p className="m-0 mt-1.5 text-[13px] text-nv-muted">{turbine(kind) ? 'Fixed free stream, rotational speed varied with the tip-speed ratio λ = ΩR/V.' : 'Fixed rotational speed, advance velocity varied with J = V/(nD).'}</p></div>
      {curve?.optimum && <dl className="m-0 grid grid-cols-2 gap-6"><Metric label={curve.optimum.quantity === 'CP' ? 'Cp max' : 'η max'} value={fmt(curve.optimum.value, 3)} />
        <Metric label={`at ${xLabel}`} value={fmt(curve.optimum[variable], 3)} /></dl>}
    </div>
    {!curve && <div className="grid min-h-[320px] place-items-center rounded-lg border border-dashed border-nv-edge text-[13px] text-nv-muted">No curve yet — choose a rotor and run the analysis.</div>}
    {charts.map((chart) => <LineChart key={chart.title} title={chart.title} unit={chart.unit} series={chart.series} legend height={chart === charts[0] ? 300 : 200}
      xDomain={xDomain} xTicks={xTicks} xLabel={xLabel} selection={at != null && at >= xDomain[0] && at <= xDomain[1] ? at : null} ariaLabel={`${chart.title} versus ${xLabel}`} />)}
    {reference && <p className="m-0 text-xs text-nv-muted">Reference (dashed): {reference.label}</p>}
    {failed > 0 && <Notice tone="warn">{failed} curve point(s) failed and are excluded from the plot.</Notice>}
    {curve && <details className="text-[13px]"><summary className="cursor-pointer text-nv-reference">Curve data ({curve.rows.length} points)</summary>
      <div className="mt-3 overflow-x-auto"><table aria-label="Performance curve data" className="w-full text-left text-xs tabular-nums"><thead className="text-nv-muted"><tr>
        {[xLabel, 'CP', 'CT', 'KT', 'KQ', 'η', 'Power [W]', 'Thrust/drag [N]', 'Converged'].map((h) => <th key={h} className="p-2 font-normal">{h}</th>)}</tr></thead>
        <tbody>{curve.rows.map((r) => <tr key={r[variable]} className="border-t border-nv-line">
          <td className="p-2">{fmt(r[variable], 3)}</td>{[r.CP, r.CT, r.KT, r.KQ, r.efficiency ?? r.open_water_efficiency, r.power_w, r.thrust_n ?? r.streamwise_force_n].map((v, i) => <td key={i} className="p-2">{fmt(v)}</td>)}
          <td className="p-2">{r.state === 'succeeded' ? (r.converged ? 'yes' : 'no') : r.error}</td></tr>)}</tbody></table></div></details>}
  </>;
}

function OperatingPoint({ kind, result }) {
  const p = result.performance, c = result.coefficients, o = result.operating;
  const metrics = turbine(kind)
    ? [['Power', p.power_w, 'W'], ['Torque', p.torque_nm, 'N·m'], [kind === 'vawt' ? 'Streamwise force' : 'Thrust', p.thrust_n ?? p.streamwise_force_n, 'N'], ['Cp', c.CP, ''], ['CT', c.CT, ''], ['λ', c.TSR, ''], ['Rotation', o.rpm, 'rpm'], ['Tip speed', o.tip_speed_m_s, 'm/s']]
    : [['Thrust', p.thrust_n, 'N'], ['Torque', p.torque_nm, 'N·m'], ['Power', p.power_w, 'W'], ['KT', c.KT, ''], ['KQ', c.KQ, ''], ['J', c.J, ''], ['Efficiency', c.efficiency, ''], ['Tip speed', o.tip_speed_m_s, 'm/s']];
  return <>
    <div><h2 className="m-0 text-[15px] font-semibold">Operating point</h2><p className="m-0 mt-1 text-xs text-nv-muted">{result.method_label} · {result.section.name}</p></div>
    <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-4 wide:grid-cols-4">{metrics.map(([label, value, unit]) => <Metric key={label} size="md" label={label} value={fmt(value)} unit={unit} />)}</dl>
    {result.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
    {result.marine && <MarinePanel marine={result.marine} />}
    {result.azimuth ? <AzimuthCharts points={result.azimuth} /> : <RadialCharts stations={result.stations} />}
  </>;
}

function MarinePanel({ marine: m }) {
  return <section aria-label="Marine assessment" className="flex flex-col gap-2 rounded-lg border border-nv-edge p-3.5">
    <h3 className="m-0 text-[13px] font-semibold">Marine assessment</h3>
    {[['KT · 10KQ', `${fmt(m.KT, 3)} · ${fmt(m['10KQ'], 3)}`], ['Open-water η₀', fmt(m.open_water_efficiency, 3)], ['Hull η_H', fmt(m.hull_efficiency, 3)],
      ['Quasi-propulsive η_D', fmt(m.quasi_propulsive_efficiency, 3)], ['Effective thrust', `${fmt(m.effective_thrust_n)} N`], ['σ at 0.7R', fmt(m.cavitation_number_07R, 3)],
      ['Burrill τc', fmt(m.thrust_loading_tau_c, 3)], ['Keller min AE/A0', `${fmt(m.keller_minimum_area_ratio, 3)} (have ${fmt(m.area_ratio, 3)})`],
      ['Min local σ (TDC)', fmt(m.minimum_local_cavitation_number, 3)]].map(([label, value]) => <KeyValue key={label} label={label}>{value}</KeyValue>)}
    <p className="m-0 text-xs text-nv-muted">Read the Burrill limit for σ₀.₇R from your reference chart and enforce it as a workflow constraint.</p>
  </section>;
}

function RadialCharts({ stations }) {
  const series = (field, color) => [{ id: field, color, points: stations.map((s) => ({ x: s.r_over_R, y: s[field] })) }];
  return <>{[['alpha_deg', 'Angle of attack', 'deg', '#4CC9F0'], ['a', 'Axial induction a', '', '#F2A93B'], ['loss_factor', 'Tip × hub loss F', '', '#B49CFB'], ['cl', 'Lift coefficient', '', '#46D19A']]
    .map(([field, title, unit, color]) => <LineChart key={field} title={title} unit={unit} height={150} series={series(field, color)} xLabel="r/R" />)}</>;
}

function AzimuthCharts({ points }) {
  const series = (field, color) => [{ id: field, color, points: points.map((p) => ({ x: p.azimuth_deg, y: p[field] })) }];
  const common = { xDomain: [0, 360], xTicks: [0, 90, 180, 270, 360], xLabel: 'deg', height: 150 };
  return <>
    <p className="m-0 text-xs text-nv-muted">Azimuth 0–180° upwind, 180–360° downwind; equatorial section.</p>
    {[['alpha_deg', 'Angle of attack', 'deg', '#4CC9F0'], ['blade_torque_nm', 'Blade torque', 'N·m', '#46D19A'], ['induction', 'Induction a', '', '#F2A93B'], ['relative_velocity_ratio', 'Relative velocity W/V∞', '', '#B49CFB']]
      .map(([field, title, unit, color]) => <LineChart key={field} title={title} unit={unit} series={series(field, color)} {...common} />)}
  </>;
}
