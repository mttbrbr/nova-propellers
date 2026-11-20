import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Play, Save } from 'lucide-react';
import { request } from '../backend.js';
import { formatValue, niceTicks } from '../lib/blade.js';
import LineChart from '../ui/LineChart.jsx';
import { CampbellChart } from '../ui/ModalCharts.jsx';
import ModeViewport from '../ui/ModeViewport.jsx';
import { Button, Disclosure, Notice, SelectField, StatusDot } from '../ui/controls.jsx';
import ModesView, { entries } from './ModesView.jsx';

// Structure workspace: the structural data of the open version (blade; hub, nacelle and tower for wind
// turbines) and its structural runs on a chosen aerodynamic run. The aerodynamic geometry is read only.

const SHELL_MATERIALS = {
  glass: { label: 'Glass/epoxy', shell: { E_pa: 2.0e10, G_pa: 4.0e9, density_kg_m3: 1900 }, cap: { E_pa: 4.0e10, G_pa: 4.0e9, density_kg_m3: 1950 } },
  carbon: { label: 'Carbon spar caps, glass shell', shell: { E_pa: 2.0e10, G_pa: 4.0e9, density_kg_m3: 1900 }, cap: { E_pa: 1.2e11, G_pa: 5.0e9, density_kg_m3: 1550 } },
};
const field = 'h-8 w-full min-w-0 rounded-md border border-nv-edge bg-nv-chrome px-2 font-mono text-[12.5px] text-nv-ink focus:border-nv-accent focus:outline-none';

// Number in display units (scale: SI = display × scale); empty stays null ("not given").
function NumberInput({ label, unit, value, scale = 1, onChange, placeholder = 'not given' }) {
  const shown = value == null ? '' : String(Number((value / scale).toPrecision(6)));
  const [text, setText] = useState(shown);
  useEffect(() => { setText(shown); }, [shown]);
  return <label className="grid grid-cols-[124px_minmax(0,1fr)_40px] items-center gap-2 text-[12.5px] text-nv-muted">{label}
    <input aria-label={label} inputMode="decimal" className={`${field} ${value == null ? 'border-nv-warn/40' : ''}`} value={text} placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => { const t = text.trim(); const n = Number(t); onChange(t === '' ? null : Number.isFinite(n) ? n * scale : value); }} />
    <span className="text-xs">{unit}</span></label>;
}

function Section({ title, summary, tone, children, defaultOpen }) {
  return <Disclosure title={<span className="inline-flex items-center gap-2"><StatusDot tone={tone} />{title}</span>} summary={summary} defaultOpen={defaultOpen}>
    <div className="flex flex-col gap-2">{children}</div></Disclosure>;
}

const complete = (item) => item && Object.entries(item).every(([k, v]) => ['youngs_modulus_pa', 'density_kg_m3', 'damping_pct', 'shape'].includes(k) || v != null);

function BladeInputs({ blade, materials, onChange }) {
  const layup = blade.layup;
  const set = (patch) => onChange({ ...blade, layup: { ...layup, ...patch } });
  const solid = layup.construction === 'solid';
  const materialId = Object.entries(SHELL_MATERIALS).find(([, m]) => m.cap.E_pa === layup.spar_cap?.E_pa)?.[0] || 'glass';
  const solidId = Object.entries(materials || {}).find(([, m]) => m.E_pa === layup.solid?.E_pa)?.[0] || '';
  return <>
    <SelectField label="Construction" value={layup.construction} onChange={(construction) => set({ construction })}
      options={[['thin_wall', 'Thin-walled shell'], ['solid', 'Solid section']]} />
    {solid ? <>
      <SelectField label="Material" value={solidId} onChange={(id) => set({ solid: { E_pa: materials[id].E_pa, G_pa: materials[id].G_pa, density_kg_m3: materials[id].density_kg_m3 } })}
        options={[['', 'Custom'], ...Object.entries(materials || {}).map(([id, m]) => [id, m.label])]} />
      <NumberInput label="Young's modulus" unit="GPa" scale={1e9} value={layup.solid?.E_pa} onChange={(v) => set({ solid: { ...layup.solid, E_pa: v } })} />
      <NumberInput label="Shear modulus" unit="GPa" scale={1e9} value={layup.solid?.G_pa} onChange={(v) => set({ solid: { ...layup.solid, G_pa: v } })} />
      <NumberInput label="Density" unit="kg/m³" value={layup.solid?.density_kg_m3} onChange={(v) => set({ solid: { ...layup.solid, density_kg_m3: v } })} />
    </> : <>
      <SelectField label="Materials" value={materialId} onChange={(id) => set({ shell: { ...layup.shell, ...SHELL_MATERIALS[id].shell }, spar_cap: { ...layup.spar_cap, ...SHELL_MATERIALS[id].cap } })}
        options={Object.entries(SHELL_MATERIALS).map(([id, m]) => [id, m.label])} />
      <NumberInput label="Shell thickness" unit="mm" scale={1e-3} value={layup.shell?.thickness_m} onChange={(v) => set({ shell: { ...layup.shell, thickness_m: v } })} />
      <NumberInput label="Spar cap at root" unit="mm" scale={1e-3} value={layup.spar_cap?.thickness_m} onChange={(v) => set({ spar_cap: { ...layup.spar_cap, thickness_m: v } })} />
      <NumberInput label="Spar cap at tip" unit="mm" scale={1e-3} value={layup.spar_cap?.tip_thickness_m} onChange={(v) => set({ spar_cap: { ...layup.spar_cap, tip_thickness_m: v } })} />
      <NumberInput label="Cap width" unit="% c" scale={0.01} value={layup.spar_cap?.width} onChange={(v) => set({ spar_cap: { ...layup.spar_cap, width: v } })} />
      <label className="grid grid-cols-[124px_minmax(0,1fr)_40px] items-center gap-2 text-[12.5px] text-nv-muted">Webs at
        <input aria-label="Web positions" className={field} defaultValue={(layup.webs || []).map((w) => Math.round(w.position * 100)).join(', ')}
          onBlur={(e) => {
            const positions = e.target.value.split(',').map((t) => Number(t.trim()) / 100).filter((v) => v > 0 && v < 1);
            const template = layup.webs?.[0] || { E_pa: 1e10, G_pa: 4e9, density_kg_m3: 1900, thickness_m: 0.008 };
            set({ webs: positions.map((position) => ({ ...template, position })) });
          }} /><span className="text-xs">% c</span></label>
    </>}
    <NumberInput label="Root cylinder to" unit="% L" scale={0.01} value={layup.root_cylinder_fraction} onChange={(v) => set({ root_cylinder_fraction: v ?? 0 })} />
  </>;
}

function bladeSummary(blade, run) {
  const mass = run?.result?.metrics?.blade_mass_kg;
  const kind = blade.layup?.construction === 'solid' ? 'solid' : 'shell + caps';
  return mass ? `${kind} · ${formatValue(mass, 3)} kg` : kind;
}

function axis(values) {
  const lo = Math.min(...values), hi = Math.max(...values);
  const ticks = niceTicks(lo, hi, 3).filter((t) => t >= lo - 1e-9 && t <= hi + 1e-9);
  return { domain: [lo, hi], ticks: ticks.length > 1 ? ticks : [lo, hi] };
}

function Sections({ rows }) {
  if (!rows?.length) return <p className="m-0 text-xs text-nv-muted">Station table input: no section properties to plot.</p>;
  const x = rows.map((r) => r.fraction);
  const { domain, ticks } = axis(x);
  const series = (key, color, scale = 1, label, dashed) => ({ id: key, color, label, dashed, points: rows.map((r) => ({ x: r.fraction, y: r[key] * scale })) });
  return <div className="grid grid-cols-1 gap-5 2xl:grid-cols-2">
    <LineChart title="Bending stiffness" unit="kN·m²" xLabel="r/L" xDomain={domain} xTicks={ticks} legend
      series={[series('EI_flap_nm2', '#FF8533', 1e-3, 'flap'), series('EI_edge_nm2', '#4CC9F0', 1e-3, 'edge', true)]} />
    <LineChart title="Mass per length" unit="kg/m" xLabel="r/L" xDomain={domain} xTicks={ticks} series={[series('mass_kg_m', '#FF8533')]} />
    <LineChart title="Torsional stiffness GJ" unit="kN·m²" xLabel="r/L" xDomain={domain} xTicks={ticks} series={[series('GJ_nm2', '#B49CFB', 1e-3)]} />
    <LineChart title="Elastic axis behind ¼ chord" unit="mm" xLabel="r/L" xDomain={domain} xTicks={ticks}
      series={[{ id: 'ea', color: '#7BD88F', points: rows.map((r) => ({ x: r.fraction, y: (r.elastic_centre_m[0] - 0.25 * r.chord_m) * 1000 })) }]} />
  </div>;
}

function Deflection({ result }) {
  const d = result.deflection;
  const { domain, ticks } = axis(d.x);
  const curve = result.curve?.rows?.filter((r) => r.state === 'succeeded') || [];
  const lam = curve.length ? axis(curve.map((r) => r.tip_speed_ratio)) : null;
  return <div className="grid grid-cols-1 gap-5 2xl:grid-cols-2">
    <LineChart title={`Deflection under the ${d.source} loads`} unit="mm" xLabel="r/L" xDomain={domain} xTicks={ticks} legend
      series={[{ id: 'flap', color: '#FF8533', label: 'flap', points: d.x.map((x, i) => ({ x, y: d.flap_m[i] * 1000 })) },
        { id: 'edge', color: '#4CC9F0', label: 'edge', dashed: true, points: d.x.map((x, i) => ({ x, y: d.edge_m[i] * 1000 })) }]} />
    {lam && <LineChart title="Cp–λ, deformed blade" xLabel="λ" xDomain={lam.domain} xTicks={lam.ticks} legend
      series={[{ id: 'flex', color: '#FF8533', label: 'aeroelastic', points: curve.map((r) => ({ x: r.tip_speed_ratio, y: r.CP })) },
        { id: 'rigid', color: '#4CC9F0', label: 'rigid', dashed: true, points: curve.map((r) => ({ x: r.tip_speed_ratio, y: r.CP_rigid })) }]} />}
    {result.aeroelastic && <div className="grid grid-cols-2 gap-3 text-[12.5px] sm:grid-cols-4">
      {[['Cp deformed', formatValue(result.aeroelastic.CP, 4)], ['Cp rigid', formatValue(result.aeroelastic.CP_rigid, 4)],
        ['Tip twist', `${formatValue(result.aeroelastic.tip_twist_deg, 3)}°`], ['Tip cone', `${formatValue(result.aeroelastic.tip_cone_deg, 3)}°`]]
        .map(([k, v]) => <div key={k} className="rounded-lg border border-nv-line p-2.5"><div className="text-xs text-nv-muted">{k}</div><div className="font-mono text-nv-ink">{v}</div></div>)}</div>}
  </div>;
}

function ModeTable({ modal }) {
  return <table aria-label="Rotating blade modes" className="w-full text-left text-[12.5px] tabular-nums">
    <thead className="text-nv-muted"><tr><th className="p-2 font-normal">Mode</th><th className="p-2 text-right font-normal">Frequency</th>
      <th className="p-2 text-right font-normal">Damping</th><th className="p-2 text-right font-normal">Nodes</th></tr></thead>
    <tbody>{(modal?.modes || []).map((m) => <tr key={m.id} className="border-t border-nv-line">
      <td className="p-2">{m.label}</td><td className="p-2 text-right font-mono">{formatValue(m.frequency_hz, 4)} Hz</td>
      <td className="p-2 text-right font-mono">{m.damping_ratio ? `${formatValue(m.damping_ratio * 100, 3)} %` : '—'}</td>
      <td className="p-2 text-right font-mono">{m.nodes ?? '—'}</td></tr>)}</tbody></table>;
}

export default function StructureWorkspace({ context }) {
  const simulation = context?.simulation;
  const spec = simulation?.configuration?.spec;
  const supported = simulation?.kind === 'rotor' && ['hawt', 'propeller', 'marine'].includes(spec?.kind);
  const wind = spec?.kind === 'hawt';
  const aeroRuns = useMemo(() => (context?.simulationRuns || []).filter((r) => r.simulation_kind === 'rotor' && r.state === 'succeeded' && r.result), [context?.simulationRuns]);
  const [record, setRecord] = useState(null);
  const [config, setConfig] = useState(null);
  const [runs, setRuns] = useState([]);
  const [aeroId, setAeroId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('campbell');
  const [modes, setModes] = useState(null);
  const [selected, setSelected] = useState(null);
  const dirty = record && config && JSON.stringify(record.config) !== JSON.stringify(config);

  const load = useCallback(async () => {
    if (!supported) return;
    setError('');
    try {
      const [stored, previous] = await Promise.all([request(`/v2/simulations/${simulation.id}/structure`), request(`/v2/simulations/${simulation.id}/structure/runs`)]);
      setRecord(stored); setConfig(stored.config); setRuns(previous);
    } catch (e) { setError(e.message); }
  }, [simulation?.id, supported]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!aeroRuns.some((r) => r.id === aeroId)) setAeroId(aeroRuns[0]?.id || ''); }, [aeroRuns, aeroId]);

  if (!simulation) return <div className="grid flex-1 place-items-center p-8 text-[13px] text-nv-muted">Open a project version from the Library to define its structure.</div>;
  if (!supported) return <div className="mx-auto mt-16 max-w-xl p-6"><Notice tone="info">The Structure workspace covers rotors of the rotor engine (HAWT and marine propellers, and propellers set up there).
    The air-propeller design pipeline does not provide a rotor specification to it yet.</Notice></div>;
  if (!config) return <div className="grid flex-1 place-items-center p-8 text-[13px] text-nv-muted">{error || 'Loading the structure…'}</div>;

  const run = runs[0];
  const result = run?.result;
  const set = (key, value) => setConfig((c) => ({ ...c, [key]: value }));
  const save = async () => {
    const saved = await request(`/v2/simulations/${simulation.id}/structure`, { config, expected_revision: record.revision ?? null }, 'PUT');
    setRecord(saved); return saved;
  };
  const execute = async () => {
    setBusy(true); setError('');
    try {
      if (dirty || record.revision == null) await save();
      const done = await request(`/v2/simulations/${simulation.id}/structure/runs`, { aero_run_id: aeroId });
      setRuns((r) => [done, ...r]);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const pseudo = result && { order: ['campbell', 'blade_rotating', 'blade_clamped', ...(result.tower_modes ? ['tower_modes'] : [])],
    blocks: Object.fromEntries([['campbell', result.campbell], ['blade_rotating', result.rotating_modes], ['blade_clamped', result.blade_modes],
      ['tower_modes', result.tower_modes]].filter(([, v]) => v).map(([k, v]) => [k, { status: 'succeeded', outputs: { modal: v } }])) };
  const campbell = result?.campbell?.campbell;
  const list = result ? entries(result.campbell) : [];
  const current = list.find((m) => m.id === selected) || list[0];
  const opIndex = campbell ? campbell.rpm.reduce((b, r, i) => Math.abs(r - (result.campbell.operating_rpm ?? r)) < Math.abs(campbell.rpm[b] - (result.campbell.operating_rpm ?? r)) ? i : b, 0) : 0;
  const metrics = result?.metrics || {};
  const margin = metrics.min_margin_pct;
  const tabs = [['campbell', 'Campbell'], ['sections', 'Sections'], ['deflection', wind ? 'Deflection & Cp' : 'Deflection'], ['modes', 'Blade modes']];
  return <div className="relative flex min-h-0 flex-1 flex-col">
    <header className="flex flex-wrap items-center gap-3 border-b border-nv-line px-4 py-2.5">
      <h2 className="m-0 text-[15px] font-semibold text-nv-ink">Structure</h2>
      <span className="text-[12.5px] text-nv-muted">{context.simulationName} · v {context.version} · {wind ? 'HAWT' : spec.kind === 'marine' ? 'marine propeller' : 'propeller'}</span>
      <span className="rounded-md border border-nv-edge px-2 py-0.5 text-[11.5px] text-nv-muted">aerodynamic geometry from Design · read only</span>
      <span className="ml-auto flex items-center gap-2">
        {dirty && <Button onClick={() => save().catch((e) => setError(e.message))}><Save size={14} aria-hidden="true" />Save</Button>}
        <Button variant="primary" disabled={busy || !aeroId} onClick={execute}><Play size={14} aria-hidden="true" />{busy ? 'Running…' : 'Run structure'}</Button>
      </span>
    </header>
    {error && <div className="px-4 pt-3"><Notice tone="err" role="alert">{error}</Notice></div>}
    <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_auto]">
      <aside aria-label="Structure sheet" className="flex min-h-0 flex-col overflow-y-auto border-r border-nv-line px-4 py-2">
        <Section title="Blade" summary={bladeSummary(config.blade, run)} tone="ok" defaultOpen>
          <BladeInputs blade={config.blade} materials={record.materials || {}} onChange={(blade) => set('blade', blade)} />
        </Section>
        {wind && <Section title="Hub & nacelle" tone={complete(config.hub) && complete(config.nacelle) ? 'ok' : 'warn'}
          summary={complete(config.hub) && complete(config.nacelle) ? `${formatValue(config.hub.mass_kg, 3)} + ${formatValue(config.nacelle.mass_kg, 3)} kg` : 'to fill in'}>
          <NumberInput label="Hub mass" unit="kg" value={config.hub.mass_kg} onChange={(v) => set('hub', { ...config.hub, mass_kg: v })} />
          <NumberInput label="Hub inertia" unit="kg·m²" value={config.hub.inertia_kg_m2} onChange={(v) => set('hub', { ...config.hub, inertia_kg_m2: v })} />
          <NumberInput label="Nacelle mass" unit="kg" value={config.nacelle.mass_kg} onChange={(v) => set('nacelle', { ...config.nacelle, mass_kg: v })} />
          <NumberInput label="Yaw inertia" unit="kg·m²" value={config.nacelle.yaw_inertia_kg_m2} onChange={(v) => set('nacelle', { ...config.nacelle, yaw_inertia_kg_m2: v })} />
          <NumberInput label="Overhang" unit="m" value={config.nacelle.overhang_m} onChange={(v) => set('nacelle', { ...config.nacelle, overhang_m: v })} />
          <NumberInput label="Shaft height" unit="m" value={config.nacelle.tower_top_to_shaft_m} onChange={(v) => set('nacelle', { ...config.nacelle, tower_top_to_shaft_m: v })} />
          <p className="m-0 text-xs text-nv-muted">Overhang is negative for an upwind rotor. Without hub and nacelle only the blade is analysed.</p>
        </Section>}
        {wind && <Section title="Tower" tone={complete(config.tower) ? 'ok' : 'warn'} summary={complete(config.tower) ? `tubular · ${formatValue(config.tower.height_m, 3)} m` : 'to fill in'}>
          <NumberInput label="Height" unit="m" value={config.tower.height_m} onChange={(v) => set('tower', { ...config.tower, height_m: v })} />
          <NumberInput label="Base diameter" unit="m" value={config.tower.base_diameter_m} onChange={(v) => set('tower', { ...config.tower, base_diameter_m: v })} />
          <NumberInput label="Top diameter" unit="m" value={config.tower.top_diameter_m} onChange={(v) => set('tower', { ...config.tower, top_diameter_m: v })} />
          <NumberInput label="Wall" unit="mm" scale={1e-3} value={config.tower.wall_thickness_m} onChange={(v) => set('tower', { ...config.tower, wall_thickness_m: v })} />
          <NumberInput label="Damping" unit="%" value={config.tower.damping_pct} onChange={(v) => set('tower', { ...config.tower, damping_pct: v })} />
        </Section>}
        <Section title="Analysis" tone={aeroId ? 'ok' : 'warn'} summary={aeroId ? 'aero run chosen' : 'run Design first'} defaultOpen>
          {aeroRuns.length ? <SelectField label="Aerodynamic run" value={aeroId} onChange={setAeroId}
            options={aeroRuns.map((r) => [r.id, `${r.result?.analysis?.method_label || 'run'} · ${new Date(r.created_at).toLocaleString()}`])} />
            : <Notice tone="info">This version has no aerodynamic run yet: run it in Design.</Notice>}
          <NumberInput label="Campbell up to" unit="rpm" value={config.analysis?.rpm_max} placeholder="1.25 × operating" onChange={(v) => set('analysis', { ...config.analysis, rpm_max: v })} />
          <p className="m-0 text-xs text-nv-muted">The operating point and the spanwise loads come from the chosen run.</p>
        </Section>
        {run && <p className="mt-3 text-xs text-nv-muted">Last structural run {new Date(run.created_at).toLocaleString()} on {run.aero_run?.method_label || 'an aerodynamic run'}.</p>}
      </aside>
      <main className="flex min-w-0 flex-col gap-4 overflow-y-auto p-5">
        <div role="tablist" aria-label="Structural results" className="flex flex-wrap gap-1.5">
          {tabs.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={`h-8 rounded-md border px-3 text-[12.5px] ${tab === id ? 'border-nv-accent bg-nv-accent/15 text-nv-ink' : 'border-nv-edge bg-nv-chrome text-nv-reference hover:bg-nv-hover'}`}>{label}</button>)}
        </div>
        {!result ? <p className="m-0 text-[13px] text-nv-muted">Fill in the structure and press Run structure.</p>
          : tab === 'campbell' ? <CampbellChart campbell={campbell} operating={result.campbell.operating_rpm} selected={current?.id} onSelect={setSelected} height={520} />
            : tab === 'sections' ? <Sections rows={result.sections} />
              : tab === 'deflection' ? <Deflection result={result} />
                : <ModeTable modal={result.rotating_modes} />}
        {result?.notes?.length > 0 && <details className="text-xs text-nv-muted"><summary className="cursor-pointer text-nv-reference">Model notes</summary>
          <div className="mt-2 flex flex-col gap-1.5">{result.notes.map((n) => <p key={n} className="m-0">{n}</p>)}</div></details>}
      </main>
      <section aria-label="3-D structure" className="flex min-h-0 flex-col gap-3 border-l border-nv-line p-4" style={{ width: 'min(36vw, calc(100vh - 200px))' }}>
        <div className="relative aspect-square w-full overflow-hidden rounded-xl border border-nv-line">
          {result ? <ModeViewport layout={result.layout || result.campbell.layout} mode={current?.shape(opIndex)} amplitude={0.5} label={`${current?.label || ''} at the operating speed`} />
            : <div className="grid h-full place-items-center text-xs text-nv-muted">No structural run yet</div>}
        </div>
        {result && <span className="text-[12.5px] text-nv-ink">{current?.label} <span className="font-mono text-nv-muted">{formatValue(current?.frequency(opIndex), 4)} Hz</span></span>}
        <dl className="m-0 grid grid-cols-2 gap-2.5">
          {[['Blade mass', metrics.blade_mass_kg, 'kg'], ['1st flap (rotating)', metrics.first_flap_hz, 'Hz'], [wind ? '1st tower' : '1st edge (rotating)', wind ? metrics.first_tower_hz : metrics.first_edge_hz, 'Hz'],
            ['Tip deflection', metrics.tip_deflection_m != null ? metrics.tip_deflection_m * 1000 : null, 'mm']].map(([label, value, unit]) =>
            <div key={label} className="rounded-lg border border-nv-line p-2.5"><dt className="text-xs text-nv-muted">{label}</dt>
              <dd className="m-0 font-mono text-[16px] text-nv-ink">{value != null ? formatValue(value, 3) : '—'} <span className="text-xs text-nv-muted">{unit}</span></dd></div>)}
          <div className={`col-span-2 rounded-lg border p-2.5 ${margin != null && margin < 10 ? 'border-nv-warn/50' : 'border-nv-line'}`}>
            <dt className="text-xs text-nv-muted">Smallest margin from the excitations{wind && metrics.cp_loss_pct != null ? ` · Cp loss from deformation ${formatValue(metrics.cp_loss_pct, 3)} %` : ''}</dt>
            <dd className={`m-0 font-mono text-[16px] ${margin != null && margin < 10 ? 'text-nv-warn-ink' : 'text-nv-ink'}`}>{margin != null ? `${formatValue(margin, 3)} %` : '—'}</dd></div>
        </dl>
        {pseudo && <Button onClick={() => setModes('campbell')}><Activity size={14} aria-hidden="true" className="text-nv-accent" />Open mode view</Button>}
      </section>
    </div>
    {modes && pseudo && <ModesView result={pseudo} blockId={modes} onBlock={setModes} onClose={() => setModes(null)} />}
  </div>;
}
