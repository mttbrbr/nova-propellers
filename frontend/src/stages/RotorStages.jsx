import { useEffect, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { request } from '../backend.js';
import { formatValue, niceTicks } from '../lib/blade.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import LineChart from '../ui/LineChart.jsx';
import { Button, Disclosure, Field, KeyValue, LabeledSegmented, Metric, Notice, Section, SelectField } from '../ui/controls.jsx';

// The rotor family is chosen once, at the start of the Design flow; every stage
// then shows only the inputs, corrections and results that apply to it.
export const families = [
  ['propeller', 'Air propeller'], ['marine', 'Marine propeller'], ['hawt', 'HAWT'], ['vawt', 'VAWT'],
];
export const familyLabel = Object.fromEntries(families);
const turbine = (kind) => kind === 'hawt' || kind === 'vawt';
const fmt = (value, digits = 4) => value == null || Number.isNaN(value) ? '—' : formatValue(value, digits);
const GRAVITY = 9.80665;

export function FamilySelector({ value, onChange, disabled }) {
  return <LabeledSegmented label="Rotor type" value={value} onChange={onChange} disabled={disabled} size="sm"
    options={families.map(([id, label]) => [id, label.replace(' propeller', '')])} />;
}

export const requirementDefaults = {
  hawt: { rated_power_w: 10000, rated_wind_m_s: 11, expected_cp: 0.42, drivetrain_efficiency: 0.92, design_tsr: 7 },
  vawt: { rated_power_w: 1000, rated_wind_m_s: 10, expected_cp: 0.32, drivetrain_efficiency: 0.9, aspect_ratio_h_d: 1.0, solidity: 0.36, blades: 3, design_tsr: 3.5 },
  marine: { effective_thrust_n: 150000, ship_speed_m_s: 6, wake_fraction: 0.2, thrust_deduction: 0.15, rpm: 120, advance_ratio: 0.6, blades: 4, shaft_depth_m: 5 },
};

// Sizing relations. Turbines: P = ½ρAV³·Cp·η. Marine: D = V_A/(nJ) with Keller's minimum area ratio.
export function sizeRotor(kind, req, fluid) {
  const rho = fluid.density_kg_m3;
  if (kind === 'hawt') {
    const radius = Math.sqrt(2 * req.rated_power_w / (rho * Math.PI * req.expected_cp * req.drivetrain_efficiency * req.rated_wind_m_s ** 3));
    const rpm = req.design_tsr * req.rated_wind_m_s / radius * 60 / (2 * Math.PI);
    return { radius, area: Math.PI * radius ** 2, rpm, tipSpeed: req.design_tsr * req.rated_wind_m_s };
  }
  if (kind === 'vawt') {
    const area = req.rated_power_w / (0.5 * rho * req.expected_cp * req.drivetrain_efficiency * req.rated_wind_m_s ** 3);
    const radius = Math.sqrt(area / (4 * req.aspect_ratio_h_d));
    const rpm = req.design_tsr * req.rated_wind_m_s / radius * 60 / (2 * Math.PI);
    return { radius, height: 2 * radius * req.aspect_ratio_h_d, chord: req.solidity * radius / req.blades, area, rpm, tipSpeed: req.design_tsr * req.rated_wind_m_s };
  }
  const n = req.rpm / 60;
  const advance = req.ship_speed_m_s * (1 - req.wake_fraction);
  const thrust = req.effective_thrust_n / (1 - req.thrust_deduction);
  const diameter = advance / (n * req.advance_ratio);
  const head = fluid.ambient_pressure_pa + rho * GRAVITY * req.shaft_depth_m - fluid.vapour_pressure_pa;
  const keller = (1.3 + 0.3 * req.blades) * thrust / (head * diameter ** 2) + 0.2;
  return { diameter, advance, thrust, kt: thrust / (rho * n * n * diameter ** 4), keller,
    areaRatio: Math.min(1.05, Math.max(0.3, Math.ceil((keller + 0.03) * 20) / 20)), immersionOk: req.shaft_depth_m > diameter / 2 + 0.2 * diameter };
}

const requirementFields = {
  hawt: [['rated_power_w', 'Rated power', 'W'], ['rated_wind_m_s', 'Rated wind', 'm/s'], ['expected_cp', 'Expected Cp', ''], ['drivetrain_efficiency', 'Drivetrain η', ''], ['design_tsr', 'Design λ', '']],
  vawt: [['rated_power_w', 'Rated power', 'W'], ['rated_wind_m_s', 'Rated wind', 'm/s'], ['expected_cp', 'Expected Cp', ''], ['drivetrain_efficiency', 'Drivetrain η', ''], ['aspect_ratio_h_d', 'Aspect H/D', ''], ['solidity', 'Solidity Nc/R', ''], ['blades', 'Blades', ''], ['design_tsr', 'Design λ', '']],
  marine: [['effective_thrust_n', 'Effective thrust', 'N'], ['ship_speed_m_s', 'Ship speed', 'm/s'], ['wake_fraction', 'Wake fraction w', ''], ['thrust_deduction', 'Thrust deduction t', ''], ['rpm', 'Shaft speed', 'rpm'], ['advance_ratio', 'Design J', ''], ['blades', 'Blades', ''], ['shaft_depth_m', 'Shaft immersion', 'm']],
};
const formulas = {
  hawt: [['R = √(2P / ρπCpηV³)', 'Radius from rated power at rated wind.'], ['n = λV / 2πR', 'Rotor speed at the design tip-speed ratio.'], ['Cp ≤ 16/27', 'Betz limit; 0.40–0.48 is realistic.']],
  vawt: [['A = 2RH = P / ½ρCpηV³', 'Swept area from rated power.'], ['H = (H/D) · 2R', 'Height from the chosen aspect ratio.'], ['c = σR / N', 'Chord from solidity and blade count.']],
  marine: [['V_A = V_s (1 − w)', 'Advance speed in the hull wake.'], ['T = T_e / (1 − t)', 'Propeller thrust from the required effective thrust.'], ['D = V_A / (nJ)', 'Diameter at the design advance ratio; Keller sets A_E/A_0.']],
};

function applySizing(kind, spec, sized) {
  const req = spec.requirements;
  if (kind === 'hawt') return { ...spec, geometry: { ...spec.geometry, radius_m: round(sized.radius), hub_radius_m: round(0.1 * sized.radius), design_tsr: req.design_tsr },
    operating: { velocity_m_s: req.rated_wind_m_s, tip_speed_ratio: req.design_tsr } };
  if (kind === 'vawt') return { ...spec, geometry: { ...spec.geometry, radius_m: round(sized.radius), height_m: round(sized.height), chord_m: round(sized.chord), blades: req.blades },
    operating: { velocity_m_s: req.rated_wind_m_s, tip_speed_ratio: req.design_tsr } };
  return { ...spec, geometry: { ...spec.geometry, diameter_m: round(sized.diameter), blades: req.blades, area_ratio: sized.areaRatio },
    operating: { rpm: req.rpm, advance_ratio: req.advance_ratio },
    marine: { ...spec.marine, wake_fraction: req.wake_fraction, thrust_deduction: req.thrust_deduction, shaft_depth_m: req.shaft_depth_m } };
}
const round = (value) => Number(value.toPrecision(4));
const ticksFor = (lo, hi) => { const t = niceTicks(lo, hi, 4).filter((v) => v >= lo - 1e-9 && v <= hi + 1e-9); return t.length >= 2 ? t : [lo, hi]; };

export function RotorSizingStage({ family, onFamily, familyLocked, spec, setSpec, catalog, projectName, onProjectName, onContinue }) {
  const fluid = catalog.fluid_properties[spec.fluid.preset] || catalog.fluid_properties.air;
  const req = { ...requirementDefaults[family], ...(spec.requirements || {}) };
  const sized = sizeRotor(family, req, fluid);
  const setReq = (key, value) => setSpec({ ...spec, requirements: { ...req, [key]: value } });
  const [applied, setApplied] = useState(false);
  useEffect(() => setApplied(false), [family]);
  const apply = () => { setSpec(applySizing(family, { ...spec, requirements: req }, sized)); setApplied(true); };
  const sweep = family === 'marine'
    ? { x: 'advance_ratio', label: 'J', lo: 0.3, hi: 1.0, y: [['Diameter', 'm', (v) => sizeRotor(family, { ...req, advance_ratio: v }, fluid).diameter, '#FF8533'],
      ['Required KT', '', (v) => sizeRotor(family, { ...req, advance_ratio: v }, fluid).kt, '#4CC9F0']] }
    : { x: 'rated_wind_m_s', label: 'm/s', lo: Math.max(3, req.rated_wind_m_s * 0.6), hi: req.rated_wind_m_s * 1.5,
      y: [['Radius', 'm', (v) => sizeRotor(family, { ...req, rated_wind_m_s: v }, fluid).radius, '#FF8533'],
        ['Rotor speed', 'rpm', (v) => sizeRotor(family, { ...req, rated_wind_m_s: v }, fluid).rpm, '#4CC9F0']] };
  const span = Array.from({ length: 40 }, (_, i) => sweep.lo + (sweep.hi - sweep.lo) * i / 39);
  const current = req[sweep.x];
  const metrics = family === 'marine'
    ? [['Diameter', sized.diameter, 'm'], ['Advance speed', sized.advance, 'm/s'], ['Propeller thrust', sized.thrust, 'N'], ['Required KT', sized.kt, ''], ['Keller min AE/A0', sized.keller, ''], ['Proposed AE/A0', sized.areaRatio, '']]
    : [['Radius', sized.radius, 'm'], ...(family === 'vawt' ? [['Height', sized.height, 'm'], ['Chord', sized.chord, 'm']] : [['Diameter', 2 * sized.radius, 'm']]),
      ['Swept area', sized.area, 'm²'], ['Rotor speed', sized.rpm, 'rpm'], ['Tip speed', sized.tipSpeed, 'm/s']];
  return <StageLayout inputsLabel="Stage inputs" contentLabel="Sizing trade-off" sideLabel="Sizing result"
    inputs={<>
      <StageTitle title="Sizing" detail={`${familyLabel[family]}: requirements give the first main dimensions.`} />
      <Section title="Project">
        <Field label="Name" ariaLabel="Project name" text value={projectName} onChange={onProjectName} />
        <FamilySelector value={family} onChange={onFamily} disabled={familyLocked} />
      </Section>
      <Section title="Requirements">
        <SelectField label="Fluid" value={spec.fluid.preset} options={catalog.fluids.filter((f) => family === 'marine' ? f !== 'air' : true).map((f) => [f, f.replace('_', ' ')])}
          onChange={(v) => setSpec({ ...spec, fluid: { preset: v } })} />
        {requirementFields[family].map(([key, label, unit]) => <Field key={key} label={label} unit={unit} value={req[key]} onChange={(v) => setReq(key, v)} />)}
      </Section>
      <Button variant="primary" onClick={apply}>Apply to geometry</Button>
      {applied && <p role="status" className="m-0 text-xs text-nv-ok-ink">Applied: geometry and operating point now follow these requirements.</p>}
      {family === 'marine' && !sized.immersionOk && <Notice tone="warn">Shaft immersion is small for this diameter: risk of ventilation.</Notice>}
      <div className="flex-1" />
      <Button onClick={onContinue}>Continue to Geometry<ArrowRight size={16} aria-hidden="true" /></Button>
    </>}
    content={<>
      <section aria-labelledby="rotor-trade">
        <h2 id="rotor-trade" className="m-0 mb-4 text-[15px] font-semibold">Trade-off <span className="font-normal text-nv-muted">· {spec.fluid.preset.replace('_', ' ')}, ρ {fluid.density_kg_m3} kg/m³</span></h2>
        <div className="grid gap-8 lg:grid-cols-2">{sweep.y.map(([title, unit, f, color]) => <LineChart key={title} title={title} unit={unit} xDomain={[sweep.lo, sweep.hi]}
          xTicks={ticksFor(sweep.lo, sweep.hi)} xLabel={sweep.label} selection={current >= sweep.lo && current <= sweep.hi ? current : null}
          onSelect={(v) => setReq(sweep.x, Number(v.toFixed(2)))} series={[{ id: title, color, points: span.map((x) => ({ x, y: f(x) })) }]} />)}</div>
      </section>
      <section aria-labelledby="rotor-method" className="grid gap-x-10 gap-y-4 sm:grid-cols-3">
        <h2 id="rotor-method" className="m-0 text-[15px] font-semibold sm:col-span-3">How the estimate is made</h2>
        {formulas[family].map(([formula, text]) => <div key={formula} className="flex flex-col gap-1.5"><span className="font-mono text-[15px]">{formula}</span><span className="text-[13px] leading-relaxed text-nv-muted">{text}</span></div>)}
      </section>
    </>}
    side={<>
      <RotorSketch family={family} spec={family === 'marine' ? { ...spec, geometry: { ...spec.geometry, diameter_m: sized.diameter } }
        : family === 'vawt' ? { ...spec, geometry: { ...spec.geometry, radius_m: sized.radius, height_m: sized.height } } : { ...spec, geometry: { ...spec.geometry, radius_m: sized.radius } }} />
      <dl className="m-0 grid grid-cols-3 gap-x-6 gap-y-5">{metrics.map(([label, value, unit]) => <Metric key={label} size="md" label={label} value={fmt(value)} unit={unit} />)}</dl>
    </>} />;
}

// Schematic view: rotor disk for axial machines, front and top view for VAWT.
function RotorSketch({ family, spec }) {
  const g = spec.geometry;
  if (family === 'vawt') {
    const R = g.radius_m, H = g.height_m, scale = 220 / Math.max(2 * R, H);
    const w = 2 * R * scale, h = H * scale, x0 = 300 - w / 2, y0 = 300 - h / 2;
    const curve = Array.from({ length: 21 }, (_, i) => { const z = -H / 2 + H * i / 20; const r = g.shape === 'troposkien' ? R * (1 - (2 * z / H) ** 2) : R; return [r * scale, 300 - z * scale]; });
    return <div className="aspect-square w-full rounded-xl border border-nv-line bg-[#0A0C0F]"><svg viewBox="0 0 600 600" role="img" aria-label={`VAWT ${formatValue(2 * R)} m diameter, ${formatValue(H)} m high`} className="h-full w-full">
      <line x1="300" x2="300" y1={y0 - 30} y2={y0 + h + 40} stroke="#3A424E" strokeWidth="3" />
      {[1, -1].map((side) => <polyline key={side} points={curve.map(([r, y]) => `${300 + side * r},${y}`).join(' ')} fill="none" stroke="#FF8533" strokeWidth="4" />)}
      <text x="300" y={y0 + h + 70} textAnchor="middle" className="fill-nv-muted font-mono text-[18px]">Ø {formatValue(2 * R)} m · H {formatValue(H)} m</text>
      <rect x={x0} y={y0} width={w} height={h} fill="none" stroke="#2A303A" strokeDasharray="6 6" />
    </svg></div>;
  }
  const radius = family === 'marine' ? g.diameter_m / 2 : g.radius_m;
  const blades = g.blades || 3;
  return <div className="aspect-square w-full rounded-xl border border-nv-line bg-[#0A0C0F]"><svg viewBox="0 0 600 600" role="img" aria-label={`${familyLabel[family]} rotor of ${formatValue(2 * radius)} m diameter`} className="h-full w-full">
    <circle cx="300" cy="300" r="220" fill="none" stroke="#2A303A" strokeDasharray="6 6" />
    {Array.from({ length: blades }, (_, i) => { const a = 2 * Math.PI * i / blades - Math.PI / 2; return <path key={i}
      d={`M300 300 Q ${300 + 120 * Math.cos(a - 0.25)} ${300 + 120 * Math.sin(a - 0.25)} ${300 + 215 * Math.cos(a)} ${300 + 215 * Math.sin(a)} Q ${300 + 120 * Math.cos(a + 0.12)} ${300 + 120 * Math.sin(a + 0.12)} 300 300`}
      fill={family === 'marine' ? '#B49CFB33' : '#FF853333'} stroke={family === 'marine' ? '#B49CFB' : '#FF8533'} strokeWidth="2" />; })}
    <circle cx="300" cy="300" r="18" fill="#161A20" stroke="#3A424E" />
    <text x="300" y="560" textAnchor="middle" className="fill-nv-muted font-mono text-[18px]">Ø {formatValue(2 * radius)} m · {blades} blades</text>
  </svg></div>;
}

const geometryFields = {
  hawt: [['blades', 'Blades', '', 1], ['radius_m', 'Tip radius', 'm'], ['hub_radius_m', 'Hub radius', 'm'], ['design_tsr', 'Design λ', ''], ['pitch_deg', 'Pitch', 'deg']],
  vawt: [['blades', 'Blades', '', 1], ['radius_m', 'Radius', 'm'], ['height_m', 'Height', 'm'], ['chord_m', 'Chord', 'm'], ['blade_pitch_deg', 'Blade pitch', 'deg'], ['pitch_axis_fraction', 'Pitch axis', 'x/c']],
  marine: [['blades', 'Blades', '', 1], ['diameter_m', 'Diameter', 'm'], ['area_ratio', 'Area ratio', 'AE/A0'], ['pitch_ratio', 'Pitch ratio', 'P/D'], ['hub_ratio', 'Hub ratio', 'r/R'], ['pitch_deg', 'Pitch offset', 'deg']],
};
const vawtExtras = [['struts_per_blade', 'Struts/blade', '', 1], ['strut_chord_m', 'Strut chord', 'm'], ['strut_cd', 'Strut Cd', ''], ['shaft_diameter_m', 'Shaft dia.', 'm'], ['shaft_cd', 'Shaft Cd', '']];
const geometryNote = {
  hawt: 'Optimum blade (Burton): chord and twist follow the design tip-speed ratio at the section’s best lift-to-drag incidence.',
  vawt: 'Straight H-rotor or troposkien Φ-rotor with constant chord; struts and shaft feed the parasitic-loss corrections.',
  marine: 'Wageningen B-series outline from blade count, expanded area ratio and pitch ratio.',
};

// Debounced evaluation that returns the blade definition for the preview.
function useRotorPreview(spec) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const key = JSON.stringify(spec);
  useEffect(() => {
    const id = ++sequence.current;
    const timer = window.setTimeout(() => {
      const analysisSpec = Object.fromEntries(Object.entries(spec).filter(([k]) => k !== 'curve' && k !== 'requirements'));
      request('/v1/rotors/analyze', { spec: analysisSpec }).then((r) => { if (id === sequence.current) { setPreview(r); setError(''); } })
        .catch((e) => { if (id === sequence.current) setError(e.message); });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return [preview, error];
}

export function RotorGeometryStage({ family, spec, setSpec, catalog, onContinue }) {
  const [preview, error] = useRotorPreview(spec);
  const set = (key, value) => setSpec({ ...spec, geometry: { ...spec.geometry, [key]: value } });
  const blade = preview?.blade;
  const axial = family !== 'vawt';
  return <StageLayout inputsLabel="Stage inputs" contentLabel="Blade definition" sideLabel="Rotor preview"
    inputs={<>
      <StageTitle title="Geometry" detail={geometryNote[family]} />
      <Section title="Blade">
        {geometryFields[family].map(([key, label, unit, step]) => <Field key={key} label={label} unit={unit} step={step || 'any'} value={spec.geometry[key] ?? ''} onChange={(v) => set(key, v)} />)}
        {family === 'vawt' && <SelectField label="Blade shape" value={spec.geometry.shape} options={[['straight', 'Straight (H-rotor)'], ['troposkien', 'Troposkien (Φ-rotor)']]} onChange={(v) => set('shape', v)} />}
        <SelectField label="Section" value={spec.section.name} options={catalog.sections.map((s) => [s, s])} onChange={(v) => setSpec({ ...spec, section: { name: v } })} />
      </Section>
      {family === 'vawt' && <Disclosure title="Struts & shaft" summary="parasitic losses">
        {vawtExtras.map(([key, label, unit, step]) => <Field key={key} label={label} unit={unit} step={step || 'any'} value={spec.geometry[key] ?? ''} onChange={(v) => set(key, v)} />)}
      </Disclosure>}
      {error && <Notice tone="err" role="alert">{error}</Notice>}
      <div className="flex-1" />
      <Button onClick={onContinue}>Continue to Analysis<ArrowRight size={16} aria-hidden="true" /></Button>
    </>}
    content={axial ? <>
      <h1 className="m-0 text-lg font-semibold">Blade distributions</h1>
      {blade ? <>
        <LineChart title="Chord" unit="c/R" xLabel="r/R" series={[{ id: 'chord', color: '#FF8533', points: blade.r_over_R.map((x, i) => ({ x, y: blade.chord_m[i] / blade.tip_radius_m })) }]} />
        <LineChart title="Twist + pitch" unit="deg" xLabel="r/R" series={[{ id: 'twist', color: '#4CC9F0', points: blade.r_over_R.map((x, i) => ({ x, y: blade.twist_deg[i] + (spec.geometry.pitch_deg || 0) })) }]} />
      </> : <p className="m-0 text-[13px] text-nv-muted">Computing blade…</p>}
    </> : <>
      <h1 className="m-0 text-lg font-semibold">Rotor proportions</h1>
      {preview && <dl className="m-0 grid grid-cols-2 gap-6 lg:grid-cols-4">{[['Solidity Nc/R', preview.geometry.solidity, ''], ['Blade aspect ratio', preview.geometry.aspect_ratio, ''],
        ['Swept area', preview.geometry.swept_area_m2, 'm²'], ['Chord/radius', spec.geometry.chord_m / spec.geometry.radius_m, '']].map(([l, v, u]) => <Metric key={l} label={l} value={fmt(v)} unit={u} />)}</dl>}
      <p className="m-0 text-[13px] leading-relaxed text-nv-muted">Solidity above about 0.5 makes single and double streamtube models unreliable; aspect ratio drives the finite-span (tip) correction; c/R above 0.1 makes flow curvature important.</p>
    </>}
    side={<>
      <RotorSketch family={family} spec={spec} />
      {preview && axial && <dl className="m-0 grid grid-cols-3 gap-x-6 gap-y-5">
        <Metric size="md" label="Solidity" value={fmt(preview.solidity)} /><Metric size="md" label="Blades" value={blade?.blades} />
        <Metric size="md" label="Hub/tip" value={fmt(blade.hub_radius_m / blade.tip_radius_m, 3)} /></dl>}
    </>} />;
}

const correctionText = {
  tip_loss: ['Tip loss', 'Finite blade number: circulation drops to zero at the tip (Prandtl; Shen adds a load-dependent factor).'],
  hub_loss: ['Hub loss', 'Same effect at the blade root next to the hub.'],
  high_induction: ['High induction', 'Momentum theory fails above a ≈ 0.4; Glauert, Buhl or Spera replace it with an empirical thrust curve.'],
  rotational_augmentation: ['3-D rotation (Snel)', 'Rotating inboard sections stall later and give extra lift.'],
  compressibility: ['Compressibility', 'Prandtl–Glauert lift correction for section Mach numbers up to 0.7.'],
  finite_aspect_ratio: ['Finite aspect ratio (tip)', 'Lanchester–Prandtl lifting line: lower lift slope and induced drag of a finite blade.'],
  flow_curvature: ['Flow curvature', 'A blade on a circular path sees a virtual camber and incidence (Migliore).'],
  dynamic_stall: ['Dynamic stall', 'Fast incidence changes delay stall (Gormont with Berg blending); important at low λ.'],
  strut_drag: ['Strut drag', 'Parasitic torque of the radial struts.'],
  shaft_wake: ['Shaft wake (hub)', 'Velocity deficit behind the central shaft for downwind passages.'],
};
const optionLabel = (value) => typeof value === 'boolean' ? (value ? 'On' : 'Off') : String(value).replaceAll('_', ' ');

export function RotorAnalysisStage({ family, spec, setSpec, catalog, onRun, runDisabled }) {
  const operating = spec.operating || {};
  const options = family === 'vawt' ? catalog.vertical_corrections : catalog.axial_corrections;
  const applicable = catalog.corrections_by_kind[family];
  const excluded = Object.keys(options).filter((key) => !applicable.includes(key));
  const range = spec.curve || (turbine(family) ? { start: 1, stop: family === 'vawt' ? 7 : 13, points: 25 } : { start: 0.05, stop: family === 'marine' ? 1.1 : 0.9, points: 25 });
  const setOperating = (key, value) => setSpec({ ...spec, operating: { ...operating, [key]: value } });
  return <StageLayout inputsLabel="Stage inputs" contentLabel="Models and corrections" sideLabel="Run"
    inputs={<>
      <StageTitle title="Analysis" detail="Operating point, method and the corrections that apply to this rotor." />
      <Section title="Operating point">
        <SelectField label="Fluid" value={spec.fluid.preset} options={catalog.fluids.filter((f) => family === 'marine' ? f !== 'air' : true).map((f) => [f, f.replace('_', ' ')])}
          onChange={(v) => setSpec({ ...spec, fluid: { preset: v } })} />
        {turbine(family) ? <>
          <Field label="Free stream" unit="m/s" value={operating.velocity_m_s ?? ''} onChange={(v) => setOperating('velocity_m_s', v)} />
          <Field label="Tip-speed ratio" unit="λ" value={operating.tip_speed_ratio ?? ''} onChange={(v) => setOperating('tip_speed_ratio', v)} />
        </> : <>
          <Field label="Rotation" unit="rpm" value={operating.rpm ?? ''} onChange={(v) => setOperating('rpm', v)} />
          <Field label="Advance ratio" unit="J" value={operating.advance_ratio ?? ''} onChange={(v) => setOperating('advance_ratio', v)} />
        </>}
      </Section>
      <Section title="Method">
        {family === 'vawt'
          ? <SelectField label="Streamtube model" ariaLabel="VAWT method" value={spec.method} options={catalog.vawt_methods.map((m) => [m.id, m.label])} onChange={(v) => setSpec({ ...spec, method: v })} />
          : <p className="m-0 text-[13px] text-nv-muted">Blade-element momentum, one bracketed 1-D residual per station.</p>}
      </Section>
      <Section title="Corrections">
        {applicable.map((key) => <SelectField key={key} label={correctionText[key][0]} ariaLabel={`Correction ${key}`} value={String(spec.corrections[key])}
          options={options[key].map((o) => [String(o), optionLabel(o)])}
          onChange={(v) => setSpec({ ...spec, corrections: { ...spec.corrections, [key]: typeof options[key][0] === 'boolean' ? v === 'true' : v } })} />)}
      </Section>
      {family === 'marine' && <Disclosure title="Hull & immersion" summary={`w ${spec.marine.wake_fraction} · t ${spec.marine.thrust_deduction}`}>
        {[['shaft_depth_m', 'Shaft depth', 'm'], ['wake_fraction', 'Wake w', ''], ['thrust_deduction', 'Thrust ded. t', ''], ['relative_rotative_efficiency', 'ηR', ''], ['keller_k', 'Keller K', '']]
          .map(([key, label, unit]) => <Field key={key} label={label} unit={unit} value={spec.marine[key] ?? ''} onChange={(v) => setSpec({ ...spec, marine: { ...spec.marine, [key]: v } })} />)}
      </Disclosure>}
      <Disclosure title="Performance curve" summary={`${turbine(family) ? 'λ' : 'J'} ${range.start}–${range.stop}`}>
        {[['start', 'From'], ['stop', 'To'], ['points', 'Points']].map(([key, label]) => <Field key={key} label={label} step={key === 'points' ? 1 : 'any'}
          value={range[key]} onChange={(v) => setSpec({ ...spec, curve: { ...range, [key]: v } })} />)}
      </Disclosure>
    </>}
    content={<>
      <h1 className="m-0 text-lg font-semibold">Corrections for a {familyLabel[family].toLowerCase()}</h1>
      <div className="grid gap-x-10 gap-y-5 lg:grid-cols-2">{applicable.map((key) => <div key={key} className="flex flex-col gap-1">
        <span className="text-[13px] font-medium">{correctionText[key][0]} <span className="ml-2 font-mono text-xs text-nv-accent">{optionLabel(spec.corrections[key])}</span></span>
        <span className="text-[13px] leading-relaxed text-nv-muted">{correctionText[key][1]}</span></div>)}</div>
      {excluded.length > 0 && <section aria-label="Not applicable" className="flex flex-col gap-2">
        <h2 className="m-0 text-[13px] font-semibold text-nv-muted">Not applicable to this rotor</h2>
        <p className="m-0 text-[13px] leading-relaxed text-nv-muted">{excluded.map((key) => correctionText[key][0]).join(', ')} — {
          family === 'marine' ? 'water is incompressible, propellers never reach windmill-brake induction and Snel models turbine root stall.'
            : family === 'propeller' ? 'propellers never reach windmill-brake induction and Snel models turbine root stall.'
              : family === 'hawt' ? 'turbine tip Mach numbers stay well below compressibility effects.' : ''}</p>
      </section>}
    </>}
    side={<>
      <RotorSketch family={family} spec={spec} />
      <Button variant="primary" onClick={onRun} disabled={runDisabled}>Run analysis</Button>
      <p className="m-0 text-xs leading-relaxed text-nv-muted">Run saves this simulation in the project and computes the operating point and the {turbine(family) ? 'Cp–λ' : 'open-water'} curve.</p>
    </>} />;
}

function curveSeries(curve, field, color, extra = {}) {
  const x = curve.variable;
  return { id: `${field}-${color}`, color, points: curve.rows.filter((r) => r.state === 'succeeded' && r[field] != null).map((r) => ({ x: r[x], y: r[field] })), ...extra };
}
const describeCorrections = (c) => Object.entries(c || {}).filter(([, v]) => v && v !== 'none').map(([k, v]) => v === true ? correctionText[k]?.[0] : `${correctionText[k]?.[0]}: ${optionLabel(v)}`).join(', ') || 'no corrections';

export function RotorResultsStage({ family, run, runs, stale, onRun, runDisabled, onNavigate }) {
  const [compareId, setCompareId] = useState('');
  if (!run) return <StageLayout inputsLabel="Stage inputs" contentLabel="Results" inputs={<StageTitle title="Results" detail="No run yet for this simulation." />}
    content={<div className="flex flex-col items-start gap-3"><p className="m-0 text-[13px] text-nv-muted">Run the analysis to see the operating point and the performance curve.</p>
      <Button variant="primary" onClick={onRun} disabled={runDisabled}>Run analysis</Button></div>} />;
  const result = run.result.analysis, curve = run.result.curve;
  const reference = runs.find((r) => r.id === compareId)?.result?.curve;
  const variable = curve.variable;
  const xs = curve.rows.map((r) => r[variable]);
  const xDomain = [Math.min(...xs), Math.max(...xs)];
  const xLabel = variable === 'tip_speed_ratio' ? 'λ' : 'J';
  const at = variable === 'tip_speed_ratio' ? result.coefficients.TSR : result.coefficients.J;
  const eta = family === 'marine' ? 'open_water_efficiency' : 'efficiency';
  const ref = (field, label) => reference ? [curveSeries({ ...reference, variable }, field, '#B49CFB', { label, dashed: true })] : [];
  const charts = turbine(family) ? [
    ['Power coefficient Cp', '', [curveSeries(curve, 'CP', '#FF8533', { label: 'Cp' }), { id: 'betz', label: 'Betz 16/27', color: '#C4CAD2', dashed: true, width: 1.2, points: [{ x: xDomain[0], y: 16 / 27 }, { x: xDomain[1], y: 16 / 27 }] }, ...ref('CP', 'Compared run')]],
    ['Thrust coefficient CT', '', [curveSeries(curve, 'CT', '#4CC9F0', { label: 'CT' }), ...ref('CT', 'Compared run')]],
    ['Torque coefficient CQ', '', [curveSeries(curve, 'CQ', '#46D19A', { label: 'CQ' }), ...ref('CQ', 'Compared run')]],
  ] : [
    ['Open-water diagram', 'KT · 10KQ · η', [curveSeries(curve, 'KT', '#FF8533', { label: 'KT' }),
      { ...curveSeries(curve, 'KQ', '#4CC9F0', { label: '10 KQ' }), points: curveSeries(curve, 'KQ', '#4CC9F0').points.map((p) => ({ ...p, y: 10 * p.y })) },
      curveSeries(curve, eta, '#46D19A', { label: 'η' }), ...ref(eta, 'Compared η')]],
    ['Power coefficient CP = P/(ρn³D⁵)', '', [curveSeries(curve, 'CP_prop', '#FF8533', { label: 'CP' }), ...ref('CP_prop', 'Compared run')]],
  ];
  const others = runs.filter((r) => r.id !== run.id && r.state === 'succeeded');
  return <StageLayout inputsLabel="Stage inputs" contentLabel="Performance" sideLabel="Operating point"
    inputs={<>
      <StageTitle title="Results" detail={`${result.method_label} · ${result.section.name}`} />
      {stale && <Notice tone="warn" action={<Button onClick={onRun} disabled={runDisabled}>Run again</Button>}>Inputs changed since this run.</Notice>}
      <Section title="This run">
        <KeyValue label="Corrections">{describeCorrections(result.corrections)}</KeyValue>
        <KeyValue label="Fluid">{result.fluid.name.replace('_', ' ')}</KeyValue>
        <KeyValue label="Run">{new Date(run.created_at).toLocaleString()}</KeyValue>
      </Section>
      <Section title="Compare">
        <SelectField label="With run" ariaLabel="Compare with run" value={compareId} onChange={setCompareId}
          options={[['', others.length ? 'None' : 'No other runs'], ...others.map((r) => [r.id, `${new Date(r.created_at).toLocaleTimeString()} · ${describeCorrections(r.result.analysis.corrections)}`])]} />
        <p className="m-0 text-xs leading-relaxed text-nv-muted">Change a correction in Analysis and run again to compare the curves (dashed).</p>
      </Section>
      <div className="flex-1" />
      <Button onClick={() => onNavigate('analysis')}>Back to Analysis</Button>
    </>}
    content={<>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="m-0 text-lg font-semibold">{turbine(family) ? 'Cp – λ performance' : 'Open-water performance'}</h1>
        {curve.optimum && <dl className="m-0 grid grid-cols-2 gap-6"><Metric label={curve.optimum.quantity === 'CP' ? 'Cp max' : 'η max'} value={fmt(curve.optimum.value, 3)} />
          <Metric label={`at ${xLabel}`} value={fmt(curve.optimum[variable], 3)} /></dl>}
      </div>
      {charts.map(([title, unit, series], index) => <LineChart key={title} title={title} unit={unit} series={series} legend height={index === 0 ? 300 : 200}
        xDomain={xDomain} xTicks={ticksFor(xDomain[0], xDomain[1])} xLabel={xLabel} selection={at != null && at >= xDomain[0] && at <= xDomain[1] ? at : null} ariaLabel={`${title} versus ${xLabel}`} />)}
      <details className="text-[13px]"><summary className="cursor-pointer text-nv-reference">Curve data ({curve.rows.length} points)</summary>
        <div className="mt-3 overflow-x-auto"><table aria-label="Performance curve data" className="w-full text-left text-xs tabular-nums"><thead className="text-nv-muted"><tr>
          {[xLabel, 'CP', 'CT', 'KT', 'KQ', 'η', 'Power [W]', 'Thrust/drag [N]', 'Converged'].map((h) => <th key={h} className="p-2 font-normal">{h}</th>)}</tr></thead>
          <tbody>{curve.rows.map((r) => <tr key={r[variable]} className="border-t border-nv-line"><td className="p-2">{fmt(r[variable], 3)}</td>
            {[r.CP, r.CT, r.KT, r.KQ, r[eta], r.power_w, r.thrust_n ?? r.streamwise_force_n].map((v, i) => <td key={i} className="p-2">{fmt(v)}</td>)}
            <td className="p-2">{r.state === 'succeeded' ? (r.converged ? 'yes' : 'no') : r.error}</td></tr>)}</tbody></table></div></details>
    </>}
    side={<><RequirementCheck family={family} requirements={run.inputs?.spec?.requirements} result={result} /><OperatingPoint family={family} result={result} /></>} />;
}

// Closes the loop with Sizing: what was required versus what this run delivers.
function RequirementCheck({ family, requirements: req, result }) {
  if (!req) return null;
  const p = result.performance;
  const rows = family === 'marine'
    ? [['Propeller thrust', req.effective_thrust_n / (1 - req.thrust_deduction), p.thrust_n, 'N',
        'Adjust the pitch ratio P/D in Geometry until the delivered thrust matches the requirement.']]
    : Math.abs((result.operating.wind_speed_m_s ?? result.operating.velocity_m_s) - req.rated_wind_m_s) < 1e-6
      ? [['Shaft power', req.rated_power_w / req.drivetrain_efficiency, p.power_w, 'W',
        'Adjust radius, design λ or pitch in Geometry; the expected Cp used in Sizing may differ from the computed one.']]
      : [];
  if (!rows.length) return <p className="m-0 text-xs text-nv-muted">Requirements were set at a different wind speed than this operating point.</p>;
  return <section aria-label="Requirement check" className="flex flex-col gap-2 rounded-lg border border-nv-edge p-3.5">
    <h3 className="m-0 text-[13px] font-semibold">Requirement check</h3>
    {rows.map(([label, required, delivered, unit, hint]) => { const ratio = delivered / required; const ok = Math.abs(ratio - 1) <= 0.05; return <div key={label} className="flex flex-col gap-1">
      <KeyValue label={`${label} required`}>{fmt(required)} {unit}</KeyValue>
      <KeyValue label="Delivered">{fmt(delivered)} {unit} <span className={ok ? 'text-nv-ok-ink' : 'text-nv-warn-ink'}>({ratio >= 1 ? '+' : ''}{((ratio - 1) * 100).toFixed(1)} %)</span></KeyValue>
      {!ok && <p className="m-0 text-xs leading-relaxed text-nv-muted">{hint}</p>}</div>; })}
  </section>;
}

function OperatingPoint({ family, result }) {
  const p = result.performance, c = result.coefficients, o = result.operating;
  const metrics = turbine(family)
    ? [['Power', p.power_w, 'W'], ['Torque', p.torque_nm, 'N·m'], [family === 'vawt' ? 'Streamwise force' : 'Thrust', p.thrust_n ?? p.streamwise_force_n, 'N'], ['Cp', c.CP, ''], ['CT', c.CT, ''], ['λ', c.TSR, ''], ['Rotation', o.rpm, 'rpm'], ['Tip speed', o.tip_speed_m_s, 'm/s']]
    : [['Thrust', p.thrust_n, 'N'], ['Torque', p.torque_nm, 'N·m'], ['Power', p.power_w, 'W'], ['KT', c.KT, ''], ['KQ', c.KQ, ''], ['J', c.J, ''], ['Efficiency', c.efficiency, ''], ['Tip speed', o.tip_speed_m_s, 'm/s']];
  return <>
    <h2 className="m-0 text-[15px] font-semibold">Operating point</h2>
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
  return <>{[['alpha_deg', 'Angle of attack', 'deg', '#FF8533'], ['a', 'Axial induction a', '', '#4CC9F0'], ['loss_factor', 'Tip × hub loss F', '', '#B49CFB'], ['cl', 'Lift coefficient', '', '#46D19A']]
    .map(([field, title, unit, color]) => <LineChart key={field} title={title} unit={unit} height={150} series={series(field, color)} xLabel="r/R" />)}</>;
}

function AzimuthCharts({ points }) {
  const series = (field, color) => [{ id: field, color, points: points.map((p) => ({ x: p.azimuth_deg, y: p[field] })) }];
  const common = { xDomain: [0, 360], xTicks: [0, 90, 180, 270, 360], xLabel: 'deg', height: 150 };
  return <>
    <p className="m-0 text-xs text-nv-muted">Azimuth 0–180° upwind, 180–360° downwind; equatorial section.</p>
    {[['alpha_deg', 'Angle of attack', 'deg', '#FF8533'], ['blade_torque_nm', 'Blade torque', 'N·m', '#46D19A'], ['induction', 'Induction a', '', '#4CC9F0'], ['relative_velocity_ratio', 'Relative velocity W/V∞', '', '#B49CFB']]
      .map(([field, title, unit, color]) => <LineChart key={field} title={title} unit={unit} series={series(field, color)} {...common} />)}
  </>;
}
