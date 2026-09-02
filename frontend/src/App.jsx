import { Activity, AlertCircle, Database, Download, FileText, Gauge, Layers3, Loader2, Play, Save } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { api } from './backend.js';
import PropellerViewport from './components/PropellerViewport.jsx';

const initial = {
  project_name: 'New propeller', propeller_type: 'traditional', diameter_mode: 'manual',
  thrust_target: 10, disk_loading: 220, diameter: 0.25, rpm: 5000, blades: 2,
  airfoil: 'NACA 4412', geometry_method: 'bezier',
};
const bezierDefaults = (diameter) => ({
  chord_points: [
    { x: 0, y: diameter * .105 }, { x: .32, y: diameter * .115 },
    { x: .72, y: diameter * .065 }, { x: 1, y: diameter * .018 },
  ],
  twist_points: [{ x: 0, y: 34 }, { x: .33, y: 25 }, { x: .72, y: 14 }, { x: 1, y: 7 }],
});
const phases = [
  ['sizing', 'Initial sizing', Gauge], ['geometry', 'Geometry', Layers3],
  ['forces', 'Force analysis', Activity], ['report', 'Report', FileText],
  ['database', 'Database', Database],
];

function Field({ label, value, onChange, unit, text = false, disabled = false }) {
  return <label className="block">
    <span className="mb-1.5 block text-xs text-zinc-400">{label}</span>
    <div className="flex rounded-md border border-zinc-800 bg-zinc-950">
      <input className="min-w-0 flex-1 bg-transparent px-3 py-2 text-sm outline-none disabled:opacity-50"
        type={text ? 'text' : 'number'} step="any" value={value} disabled={disabled}
        onChange={(event) => onChange(text ? event.target.value : Number(event.target.value))} />
      {unit && <span className="px-3 py-2 text-xs text-zinc-600">{unit}</span>}
    </div>
  </label>;
}

function Select({ label, value, onChange, options }) {
  return <label className="block"><span className="mb-1.5 block text-xs text-zinc-400">{label}</span>
    <select className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm"
      value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map(([id, name, disabled]) => <option key={id} value={id} disabled={disabled}>{name}</option>)}
    </select>
  </label>;
}

function Card({ title, children }) {
  return <section className="rounded-xl border border-white/[0.07] bg-zinc-900/65 p-4 shadow-xl shadow-black/25 backdrop-blur-sm">
    {title && <h2 className="mb-4 text-sm font-medium tracking-tight text-zinc-100">{title}</h2>}{children}
  </section>;
}

function CurveEditor({ label, points, max, unit, onChange }) {
  const width = 360, height = 140, pad = 18;
  const coords = points.map((point) => ({
    x: pad + point.x * (width - 2 * pad), y: height - pad - point.y / max * (height - 2 * pad),
  }));
  const drag = (index, event) => {
    if (event.buttons !== 1) return;
    const box = event.currentTarget.ownerSVGElement.getBoundingClientRect();
    const value = Math.max(0, Math.min(max, (box.bottom - event.clientY - pad) / (box.height - 2 * pad) * max));
    onChange(points.map((point, i) => i === index ? { ...point, y: value } : point));
  };
  return <Card><div className="mb-2 flex justify-between text-xs text-zinc-400"><span>{label}</span><span>{unit}</span></div>
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full select-none">
      {[.25, .5, .75].map((y) => <line key={y} x1={pad} x2={width - pad} y1={pad + y * (height - 2 * pad)} y2={pad + y * (height - 2 * pad)} stroke="#27272a" />)}
      <polyline points={coords.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#a1a1aa" strokeWidth="2" />
      {coords.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="7" fill="#fafafa" stroke="#09090b"
        strokeWidth="3" className="cursor-ns-resize" onPointerMove={(event) => drag(i, event)} />)}
    </svg>
  </Card>;
}

function DistributionChart({ title, stations, field, unit = '', color = '#e4e4e7' }) {
  const rows = stations.filter((station) => Number.isFinite(Number(station[field])));
  if (!rows.length) return <div className="rounded border border-zinc-800 p-3 text-xs text-zinc-600">{title}: no data available</div>;
  const values = rows.map((station) => Number(station[field]));
  const min = Math.min(...values), max = Math.max(...values), range = Math.max(max - min, 1e-9);
  const points = values.map((value, index) => `${index / Math.max(values.length - 1, 1) * 100},${42 - (value - min) / range * 34}`).join(' ');
  return <div className="rounded-lg border border-zinc-800 bg-zinc-950/65 p-3">
    <div className="mb-2 flex justify-between text-xs"><span className="text-zinc-300">{title}</span>
      <span className="text-zinc-600">{min.toFixed(2)}–{max.toFixed(2)} {unit}</span></div>
    <svg className="h-20 w-full" viewBox="0 0 100 48" preserveAspectRatio="none">
      <line x1="0" y1="43" x2="100" y2="43" stroke="#27272a" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  </div>;
}

function PolarChart({ rows }) {
  const grouped = useMemo(() => {
    if (!rows.length) return [];
    const reynolds = [...new Set(rows.map((row) => Number(row.reynolds)))].sort((a, b) => a - b);
    const selected = reynolds[Math.floor(reynolds.length / 2)];
    return rows.filter((row) => Number(row.reynolds) === selected).sort((a, b) => Number(a.alpha_deg) - Number(b.alpha_deg));
  }, [rows]);
  if (!grouped.length) return null;
  const make = (field) => {
    const values = grouped.map((row) => field === 'ratio' ? Number(row.cl) / Math.max(Number(row.cd), 1e-6) : Number(row[field]));
    const min = Math.min(...values), max = Math.max(...values), range = Math.max(max - min, 1e-9);
    return values.map((value, index) => `${index / Math.max(values.length - 1, 1) * 100},${42 - (value - min) / range * 34}`).join(' ');
  };
  return <div className="rounded-lg border border-zinc-800 bg-zinc-950/65 p-4">
    <div className="mb-2 flex justify-between text-xs text-zinc-400"><span>Polar curves</span><span>Re {grouped[0].reynolds}</span></div>
    <svg className="h-32 w-full" viewBox="0 0 100 48" preserveAspectRatio="none">
      <polyline points={make('cl')} fill="none" stroke="#67e8f9" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      <polyline points={make('cd')} fill="none" stroke="#fbbf24" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      <polyline points={make('ratio')} fill="none" stroke="#a7f3d0" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
    <div className="flex gap-4 text-[10px]"><span className="text-cyan-200">Cl</span><span className="text-amber-200">Cd</span><span className="text-emerald-200">Cl/Cd</span></div>
  </div>;
}

function AirfoilShapeChart({ coordinates, title = 'Normalized coordinates' }) {
  if (!coordinates?.length) return <div className="rounded border border-dashed border-zinc-800 p-6 text-center text-xs text-zinc-600">No DAT coordinates imported.</div>;
  const points = coordinates.map(([x, y]) => `${8 + Number(x) * 184},${60 - Number(y) * 360}`).join(' ');
  return <div className="rounded-xl border border-white/[0.07] bg-zinc-950/70 p-4 shadow-xl shadow-black/20">
    <div className="mb-2 text-xs text-zinc-400">{title}</div>
    <svg viewBox="0 0 200 120" className="h-40 w-full">
      <line x1="8" x2="192" y1="60" y2="60" stroke="#3f3f46" />
      <polyline points={points} fill="rgba(255,255,255,.04)" stroke="#f4f4f5" strokeWidth="1.5" />
    </svg>
  </div>;
}

function downloadDiagnostics(analysis) {
  const payload = {
    exported_at: new Date().toISOString(),
    schema_version: analysis.schema_version || 'legacy',
    solver: analysis.solver || { id: analysis.model },
    operating_point: analysis.operating_point || null,
    performance: analysis.performance || analysis.summary || null,
    units: analysis.units || {},
    warnings: analysis.warnings || [],
    convergence: analysis.convergence || null,
  };
  const url = URL.createObjectURL(new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `nova-${analysis.model || 'solver'}-diagnostics.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function ConvergenceDiagnostics({ analysis }) {
  const convergence = analysis?.convergence;
  const diagnostics = convergence?.diagnostics;
  if (!convergence) return <div className="rounded border border-zinc-800 p-4 text-xs text-zinc-500">This solver does not expose iterative convergence diagnostics.</div>;
  const history = diagnostics?.history || [];
  const residualFields = ['residual', 'axial_residual', 'tangential_residual'];
  const logResiduals = history.flatMap((item) => residualFields.map((field) =>
    Math.log10(Math.max(Number(item[field]), 1e-16))
  ));
  const minLog = Math.min(...logResiduals, -6);
  const maxLog = Math.max(...logResiduals, 0);
  const logRange = Math.max(maxLog - minLog, 1e-9);
  const lastIteration = Math.max(history.at(-1)?.iteration || 1, 1);
  const finalSample = history.at(-1);
  const makePoints = (field) => history.map((item) => {
    const x = 6 + Number(item.iteration) / lastIteration * 188;
    const logValue = Math.log10(Math.max(Number(item[field]), 1e-16));
    const y = 8 + (maxLog - logValue) / logRange * 64;
    return `${x},${y}`;
  }).join(' ');
  const statusColor = convergence.converged ? 'text-emerald-300' : 'text-amber-300';
  return <details className="rounded-xl border border-white/[0.07] bg-zinc-950/70" open={!convergence.converged}>
    <summary className="cursor-pointer px-4 py-3 text-xs text-zinc-300">
      Advanced diagnostics · <span className={statusColor}>{diagnostics?.classification || convergence.termination_reason}</span>
    </summary>
    <div className="space-y-4 border-t border-zinc-800 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[10px] leading-4 text-zinc-500">Diagnostics belong to this exact solver run and are stored with the project.</p>
        <button onClick={() => downloadDiagnostics(analysis)} className="rounded border border-zinc-700 px-3 py-2 text-[10px] text-zinc-300 hover:border-zinc-500">
          <Download size={12} className="mr-1 inline" />Export diagnostics JSON
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
        {[
          ['Converged', convergence.converged ? 'yes' : 'no'],
          ['Iterations', convergence.iterations],
          ['Final residual', Number(convergence.residual).toExponential(3)],
          ['Tolerance', Number(convergence.tolerance).toExponential(1)],
          ['Classification', diagnostics?.classification || 'legacy'],
          ['Relaxation', diagnostics ? `${diagnostics.relaxation_strategy} · ${Number(diagnostics.final_relaxation_factor).toFixed(3)}` : '—'],
        ].map(([label, value]) => <div key={label} className="rounded border border-zinc-800 bg-zinc-900/50 p-3">
          <div className="text-[9px] uppercase text-zinc-600">{label}</div><div className="mt-1 text-xs">{value}</div>
        </div>)}
      </div>
      {history.length > 1 && <div>
        <div className="mb-2 flex justify-between text-[10px] text-zinc-500"><span>Residual history · logarithmic scale</span><span>{diagnostics.history_sampling}</span></div>
        <svg viewBox="0 0 200 80" preserveAspectRatio="none" className="h-36 w-full rounded border border-zinc-800 bg-black/30 p-2">
          <polyline points={makePoints('residual')} fill="none" stroke="#f4f4f5" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <polyline points={makePoints('axial_residual')} fill="none" stroke="#38bdf8" strokeWidth="1.3" vectorEffect="non-scaling-stroke" />
          <polyline points={makePoints('tangential_residual')} fill="none" stroke="#f59e0b" strokeWidth="1.3" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="mt-2 flex flex-wrap gap-4 text-[10px]"><span className="text-zinc-100">Total</span><span className="text-sky-400">Axial</span><span className="text-amber-400">Tangential</span></div>
      </div>}
      {diagnostics && <div className="grid gap-2 text-[10px] text-zinc-500 md:grid-cols-3">
        <span>Total reduction: {Number(diagnostics.total_reduction_ratio).toExponential(3)}</span>
        <span>Recent reduction: {Number(diagnostics.recent_reduction_ratio).toExponential(3)}</span>
        <span>Tail variation: {Number(diagnostics.tail_variation_ratio).toFixed(4)}×</span>
      </div>}
      {finalSample?.polar_context && <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {[
          ['Limiting component', finalSample.limiting_component],
          ['Limiting station', `r/R ${Number(finalSample.limiting_r_over_R).toFixed(3)}`],
          ['Local alpha', `${Number(finalSample.limiting_alpha_deg).toFixed(3)}°`],
          ['Local Reynolds', Number(finalSample.limiting_reynolds).toFixed(0)],
          ['Polar alpha segment', finalSample.polar_context.alpha_segment_deg.join(' → ')],
          ['Polar Re segment', finalSample.polar_context.reynolds_segment.join(' → ')],
          ['Low-Re treatment', finalSample.polar_context.low_re_strategy || 'legacy'],
          ['Tangential cap', finalSample.max_tangential_induction_ratio == null ? 'legacy' : Number(finalSample.max_tangential_induction_ratio).toFixed(2)],
          ['Alpha clipped', finalSample.polar_context.alpha_clipped ? 'yes' : 'no'],
          ['Reynolds clipped', finalSample.polar_context.reynolds_clipped ? 'yes' : 'no'],
        ].map(([label, value]) => <div key={label} className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
          <div className="text-[9px] uppercase text-zinc-600">{label}</div><div className="mt-1 text-xs">{value}</div>
        </div>)}
      </div>}
      {history.length > 0 && <div className="max-h-56 overflow-auto rounded border border-zinc-800">
        <div className="grid min-w-[980px] grid-cols-9 bg-zinc-950 p-2 text-[9px] uppercase text-zinc-600"><span>Iteration</span><span>Residual</span><span>Axial</span><span>Tangential</span><span>r/R</span><span>Alpha</span><span>Re</span><span>Loss F</span><span>Relaxation</span></div>
        {history.map((row) => <div key={row.iteration} className="grid min-w-[980px] grid-cols-9 border-t border-zinc-900 p-2 text-[10px] text-zinc-400">
          <span>{row.iteration}</span><span>{Number(row.residual).toExponential(2)}</span><span>{Number(row.axial_residual).toExponential(2)}</span><span>{Number(row.tangential_residual).toExponential(2)}</span><span>{Number(row.limiting_r_over_R).toFixed(3)}</span><span>{row.limiting_alpha_deg == null ? '—' : Number(row.limiting_alpha_deg).toFixed(2)}</span><span>{row.limiting_reynolds == null ? '—' : Number(row.limiting_reynolds).toFixed(0)}</span><span>{row.limiting_loss_factor == null ? '—' : Number(row.limiting_loss_factor).toFixed(3)}</span><span>{row.relaxation_factor == null ? '—' : Number(row.relaxation_factor).toFixed(3)}</span>
        </div>)}
      </div>}
    </div>
  </details>;
}

function ReportWorkspace({ project, analyses, geometry, selectedModel, onSelectModel, stlUrl }) {
  const analysis = analyses.find((item) => item.model === selectedModel) || analyses[0];
  const stations = analysis?.stations || geometry?.stations?.map((station) => ({
    ...station, chord_mm: Number(station.chord_m) * 1000,
  })) || [];
  return <div className="h-full overflow-auto p-4 sm:p-6 lg:p-8 2xl:p-10">
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><div className="text-xs uppercase tracking-wider text-zinc-600">Technical report</div>
          <h2 className="mt-1 text-2xl font-semibold">{project?.project_name || 'Current project'}</h2>
          <p className="mt-1 text-xs text-zinc-500">{geometry?.method || '—'} · {geometry?.stations?.length || 0} stations · {geometry?.blades || '—'} blades</p></div>
        {stlUrl && <a className="rounded-md border border-zinc-700 px-4 py-2 text-xs" href={stlUrl} download="nova_report_geometry.stl"><Download size={14} className="mr-2 inline" />STL</a>}
      </div>
      <div className="flex flex-wrap gap-2">{analyses.map((item) =>
        <button key={item.model} onClick={() => onSelectModel(item.model)}
          className={`rounded-md border px-3 py-2 text-xs ${analysis?.model === item.model ? 'border-zinc-300 bg-zinc-100 text-zinc-950' : 'border-zinc-800 text-zinc-400'}`}>
          {item.method || item.model} · {item.fidelity || 'legacy'}
        </button>)}</div>
      {analysis ? <>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6 2xl:grid-cols-8">{Object.entries(analysis.summary || {}).slice(0, 12).map(([key, value]) =>
          <div key={key} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"><div className="text-[9px] uppercase text-zinc-600">{key.replaceAll('_', ' ')}</div><div className="mt-1 text-sm">{value}</div></div>)}</div>
        <div className={`rounded-md border p-3 text-xs ${analysis.curve_source === 'native' ? 'border-emerald-900 text-emerald-300' : 'border-amber-900 text-amber-300'}`}>
          Curves {analysis.curve_source === 'native' ? 'provided by the solver' : 'reconstructed from global results'}.
        </div>
        <ConvergenceDiagnostics analysis={analysis} />
      </> : <div className="rounded border border-zinc-800 p-4 text-sm text-zinc-500">No saved analyses.</div>}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        <DistributionChart title="Chord" stations={stations} field="chord_mm" unit="mm" />
        <DistributionChart title="Twist" stations={stations} field="twist_deg" unit="°" color="#a78bfa" />
        <DistributionChart title="Angle of attack" stations={stations} field="alpha_deg" unit="°" color="#38bdf8" />
        <DistributionChart title="Cl" stations={stations} field="cl" color="#67e8f9" />
        <DistributionChart title="Cd" stations={stations} field="cd" color="#fbbf24" />
        <DistributionChart title="Reynolds" stations={stations} field="reynolds" color="#34d399" />
        <DistributionChart title="Circulation" stations={stations} field="circulation" color="#f472b6" />
        <DistributionChart title="Local thrust" stations={stations} field="d_thrust_n" unit="N" color="#fb923c" />
        <DistributionChart title="Local power" stations={stations} field="d_power_w" unit="W" color="#e879f9" />
      </div>
      {stations.length > 0 && <div className="overflow-auto rounded-lg border border-zinc-800">
        <div className="grid min-w-[1050px] grid-cols-11 bg-zinc-950 p-3 text-[9px] uppercase text-zinc-600">
          {['r/R','r [m]','chord [mm]','twist','alpha','Cl','Cd','Re','Γ','dT [N]','dP [W]'].map((label) => <span key={label}>{label}</span>)}
        </div>{stations.map((row, index) => <div key={index} className="grid min-w-[1050px] grid-cols-11 border-t border-zinc-900 p-3 text-[10px] text-zinc-300">
          {[row.r_over_R,row.radius_m,row.chord_mm,row.twist_deg,row.alpha_deg,row.cl,row.cd,row.reynolds,row.circulation,row.d_thrust_n,row.d_power_w].map((value, i) => <span key={i}>{value ?? '—'}</span>)}
        </div>)}
      </div>}
    </div>
  </div>;
}

function AirfoilWorkspace({ detail }) {
  const rows = detail?.polars || [], quality = detail?.polar_quality;
  if (!detail) return <div className="grid h-full place-items-center text-sm text-zinc-600">Select an airfoil from the database.</div>;
  return <div className="h-full overflow-auto p-4 sm:p-6 lg:p-8 2xl:p-10"><div className="w-full space-y-6">
    <div><div className="text-xs uppercase text-zinc-600">Airfoil database</div><h2 className="mt-1 text-2xl font-semibold">{detail.name}</h2>
      <p className="mt-1 text-xs text-zinc-500">{detail.family} · {detail.source}</p></div>
    <div className="grid gap-3 md:grid-cols-4">
      {[['Camber', detail.camber],['Thickness', detail.thickness],['Polar sets', detail.polar_sets?.length || 0],['Points', rows.length]].map(([label,value]) =>
        <div key={label} className="rounded border border-zinc-800 p-3"><div className="text-[9px] uppercase text-zinc-600">{label}</div><div className="mt-1 text-sm">{value}</div></div>)}
    </div>
    <div className={`rounded border p-4 text-xs ${quality?.status === 'ok' ? 'border-emerald-900 text-emerald-300' : 'border-amber-900 text-amber-300'}`}>
      Polar quality: {quality?.status || 'missing'}{quality?.warnings?.length ? ` · ${quality.warnings.join(' · ')}` : ''}
    </div>
    <PolarChart rows={rows} />
    <AirfoilShapeChart coordinates={detail.coordinates} />
    <div className="grid gap-3 md:grid-cols-2">{(detail.polar_sets || []).map((set) =>
      <div key={set.id} className="rounded border border-zinc-800 bg-zinc-900/40 p-3 text-xs">
        <div className="flex justify-between"><span>{set.label}</span><span className="text-zinc-600">#{set.id}</span></div>
        <div className="mt-2 text-zinc-500">{set.method} · Re {set.min_reynolds}–{set.max_reynolds} · {set.points} points</div>
      </div>)}</div>
    <div className="max-h-[420px] overflow-auto rounded border border-zinc-800">
      <div className="grid min-w-[850px] grid-cols-8 bg-zinc-950 p-3 text-[9px] uppercase text-zinc-600">{['Set','Re','Mach','Alpha','Cl','Cd','Cm','Source'].map((x) => <span key={x}>{x}</span>)}</div>
      {rows.map((row, i) => <div key={i} className="grid min-w-[850px] grid-cols-8 border-t border-zinc-900 p-3 text-[10px]">
        {[row.polar_set_id,row.reynolds,row.mach,row.alpha_deg,row.cl,row.cd,row.cm,row.source].map((x,j) => <span key={j}>{x}</span>)}
      </div>)}
    </div>
  </div></div>;
}

function App() {
  const [phase, setPhase] = useState('sizing');
  const [inputs, setInputs] = useState(initial);
  const [bezier, setBezier] = useState(bezierDefaults(initial.diameter));
  const [laguerre, setLaguerre] = useState({
    chord_coefficients: [.02625, .0195, -.01125, -.0045],
    twist_coefficients: [34, 25, -8, 1],
  });
  const [airfoils, setAirfoils] = useState(['NACA 4412']);
  const [coordinateAirfoils, setCoordinateAirfoils] = useState([]);
  const [useAirfoilLoft, setUseAirfoilLoft] = useState(false);
  const [bezierProfileAssignments, setBezierProfileAssignments] = useState(['', '', '', '']);
  const [laguerreProfileAssignments, setLaguerreProfileAssignments] = useState([
    { radial_fraction: 0, airfoil: '' },
    { radial_fraction: 1, airfoil: '' },
  ]);
  const [loftPreview, setLoftPreview] = useState(null);
  const [computationalMethods, setComputationalMethods] = useState([]);
  const [sizing, setSizing] = useState(null);
  const [canonical, setCanonical] = useState(null);
  const [mesh, setMesh] = useState(null);
  const [stlUrl, setStlUrl] = useState('');
  const [displayMode, setDisplayMode] = useState('surface');
  const [model, setModel] = useState('bemt');
  const [designMode, setDesignMode] = useState('direct');
  const [inverseSolver, setInverseSolver] = useState('bemt');
  const [inverseResult, setInverseResult] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [reportModel, setReportModel] = useState('');
  const [reportView, setReportView] = useState('projects');
  const [selectedAirfoil, setSelectedAirfoil] = useState('NACA 4412');
  const [airfoilDetail, setAirfoilDetail] = useState(null);
  const [airfoilForm, setAirfoilForm] = useState({ name: '', family: 'custom', source: 'user', notes: '' });
  const [airfoilEdit, setAirfoilEdit] = useState({ family: '', source: '', notes: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savedId, setSavedId] = useState(null);

  const parameters = inputs.geometry_method === 'bezier' ? bezier : laguerre;
  const activeAirfoilAssignments = inputs.geometry_method === 'bezier'
    ? bezier.chord_points.map((point, index) => ({
        radial_fraction: point.x,
        airfoil: bezierProfileAssignments[index] || '',
      }))
    : laguerreProfileAssignments;
  const payload = useMemo(() => ({
    project_name: inputs.project_name, propeller_type: inputs.propeller_type,
    thrust_target: inputs.thrust_target, rpm: inputs.rpm, diameter: inputs.diameter,
    blades: inputs.blades, airfoil: inputs.airfoil, geometry_method: inputs.geometry_method,
    geometry_parameters: parameters,
    airfoil_assignments: useAirfoilLoft ? activeAirfoilAssignments : [],
  }), [inputs, parameters, useAirfoilLoft, activeAirfoilAssignments]);
  const set = (key, value) => setInputs((current) => ({ ...current, [key]: value }));
  const refresh = () => fetch(api('/propellers')).then((r) => r.ok ? r.json() : []).then(setProjects).catch(() => {});
  const refreshAirfoils = () => fetch(api('/airfoils')).then((r) => r.json()).then((rows) => {
    setAirfoils(rows.map((row) => row.name));
    const available = rows.filter((row) => row.has_coordinates).map((row) => row.name);
    setCoordinateAirfoils(available);
    setBezierProfileAssignments((current) => bezier.chord_points.map((_, index) =>
      available.includes(current[index]) ? current[index] : available[Math.min(index, available.length - 1)] || ''
    ));
    setLaguerreProfileAssignments((current) => current.map((assignment, index) => ({
      ...assignment,
      airfoil: available.includes(assignment.airfoil)
        ? assignment.airfoil
        : available[Math.min(index, available.length - 1)] || '',
    })));
  });

  useEffect(() => {
    refreshAirfoils().catch(() => {});
    fetch(api('/computational-methods')).then((r) => r.json()).then(setComputationalMethods).catch(() => {});
    refresh();
    // Bootstrap once; later refreshes are triggered explicitly after database changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedAirfoil) return;
    fetch(api(`/airfoils/${encodeURIComponent(selectedAirfoil)}`)).then((response) => response.ok ? response.json() : null)
      .then((detail) => {
        setAirfoilDetail(detail);
        if (detail) setAirfoilEdit({ family: detail.family, source: detail.source, notes: detail.notes });
      }).catch(() => setAirfoilDetail(null));
  }, [selectedAirfoil]);

  const post = async (endpoint, body) => {
    const response = await fetch(api(endpoint), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || `HTTP error ${response.status}`);
    }
    return response;
  };
  const run = async (action) => {
    setBusy(true); setError('');
    try { await action(); } catch (caught) { setError(caught.message); } finally { setBusy(false); }
  };

  const estimate = () => run(async () => {
    const result = await (await post('/sizing/actuator-disk', {
      thrust_target: inputs.thrust_target, disk_loading: inputs.disk_loading,
    })).json();
    setSizing(result); set('diameter', result.diameter_m); setBezier(bezierDefaults(result.diameter_m));
  });

  const generate = (geometryPayload = payload) => run(async () => {
    const result = await (await post('/geometries', geometryPayload)).json();
    const response = await post('/geometries/stl', geometryPayload);
    const blob = await response.blob();
    const geometry = new STLLoader().parse(await blob.arrayBuffer());
    if (stlUrl) URL.revokeObjectURL(stlUrl);
    setMesh((current) => { current?.dispose(); return geometry; });
    setStlUrl(URL.createObjectURL(blob)); setCanonical(result.geometry);
    setAnalyses([]); setSavedId(null);
  });

  const optimizeGeometry = () => run(async () => {
    const result = await (await post('/inverse-design', {
      target_thrust: inputs.thrust_target,
      rpm: inputs.rpm,
      diameter: inputs.diameter,
      blades: inputs.blades,
      airfoil: inputs.airfoil,
      solver: inverseSolver,
      chord_points: bezier.chord_points,
      twist_points: bezier.twist_points,
      min_chord_m: Math.max(0.003, inputs.diameter * 0.012),
      max_chord_m: inputs.diameter * 0.16,
      min_twist_deg: 2,
      max_twist_deg: 45,
      max_iterations: inverseSolver === 'vlm' ? 100 : 180,
    })).json();
    setInverseResult(result);
  });

  const applyInverseResult = () => {
    if (!inverseResult) return;
    const optimizedParameters = inverseResult.geometry_parameters;
    setBezier(optimizedParameters);
    set('geometry_method', 'bezier');
    setInverseResult(null);
    generate({
      ...payload,
      geometry_method: 'bezier',
      geometry_parameters: optimizedParameters,
    });
  };

  const setBezierPointCount = (curve, requestedCount) => {
    const count = Math.max(2, Math.min(10, Number(requestedCount)));
    const key = `${curve}_points`;
    const previous = bezier[key];
    const sample = (x) => {
      const right = previous.findIndex((point) => point.x >= x);
      if (right <= 0) return previous[0].y;
      const left = right - 1;
      const weight = (x - previous[left].x) / Math.max(previous[right].x - previous[left].x, 1e-9);
      return previous[left].y * (1 - weight) + previous[right].y * weight;
    };
    const points = Array.from({ length: count }, (_, index) => {
      const x = index / (count - 1);
      return { x, y: sample(x) };
    });
    setBezier({ ...bezier, [key]: points });
    if (curve === 'chord') {
      setBezierProfileAssignments(points.map((point) => {
        const nearest = previous.reduce(
          (best, candidate, index) => Math.abs(candidate.x - point.x) < best.distance
            ? { index, distance: Math.abs(candidate.x - point.x) }
            : best,
          { index: 0, distance: Infinity },
        );
        return bezierProfileAssignments[nearest.index] || coordinateAirfoils[0] || '';
      }));
    }
    setInverseResult(null);
  };

  const importDatFile = (file) => run(async () => {
    const content = await file.text();
    const name = file.name.replace(/\.dat$/i, '');
    const result = await (await post('/airfoils/import-dat', { name, content })).json();
    await refreshAirfoils();
    setSelectedAirfoil(result.airfoil.name);
    setReportView('airfoils');
  });

  const previewLoft = () => run(async () => {
    const result = await (await post('/airfoils/loft', {
      assignments: activeAirfoilAssignments,
      radial_fraction: 0.5,
      method: 'linear',
    })).json();
    setLoftPreview(result.coordinates);
  });

  const addLaguerreProfileStation = () => {
    if (laguerreProfileAssignments.length >= 10) return;
    const sorted = [...laguerreProfileAssignments].sort((a, b) => a.radial_fraction - b.radial_fraction);
    const gaps = sorted.slice(0, -1).map((item, index) => sorted[index + 1].radial_fraction - item.radial_fraction);
    const index = gaps.indexOf(Math.max(...gaps));
    const radial_fraction = (sorted[index].radial_fraction + sorted[index + 1].radial_fraction) / 2;
    setLaguerreProfileAssignments([
      ...sorted,
      { radial_fraction, airfoil: sorted[index].airfoil || coordinateAirfoils[0] || '' },
    ].sort((a, b) => a.radial_fraction - b.radial_fraction));
    setLoftPreview(null);
  };

  const updateLaguerreProfileStation = (index, patch) => {
    setLaguerreProfileAssignments((current) => current.map((assignment, itemIndex) =>
      itemIndex === index ? { ...assignment, ...patch } : assignment
    ).sort((a, b) => a.radial_fraction - b.radial_fraction));
    setLoftPreview(null);
  };

  const analyze = () => run(async () => {
    const result = await (await post('/analyses', { model, inputs: payload, geometry: canonical })).json();
    setAnalyses((current) => [...current.filter((item) => item.model !== model), result]);
    setReportModel(model);
    setSavedId(null);
  });

  const save = () => run(async () => {
    const result = await (await post('/projects', {
      project_name: inputs.project_name, inputs: payload, geometry: canonical, analyses,
    })).json();
    setSavedId(result.id); refresh();
  });

  const open = (id) => run(async () => {
    const detail = await (await fetch(api(`/propellers/${id}`))).json();
    const stored = detail.payload;
    setInputs((current) => ({ ...current, ...stored, project_name: detail.project_name }));
    if (stored.geometry_method === 'bezier') setBezier(stored.geometry_parameters);
    if (stored.geometry_method === 'laguerre') setLaguerre(stored.geometry_parameters);
    if (stored.airfoil_assignments?.length) {
      setUseAirfoilLoft(true);
      if (stored.geometry_method === 'bezier') {
        const sorted = [...stored.airfoil_assignments].sort((a, b) => a.radial_fraction - b.radial_fraction);
        setBezierProfileAssignments(sorted.map((assignment) => assignment.airfoil));
      } else {
        setLaguerreProfileAssignments(stored.airfoil_assignments);
      }
    } else {
      setUseAirfoilLoft(false);
    }
    setCanonical(detail.geometry); setAnalyses(detail.analyses || []); setSavedId(id);
    setSelectedProject(detail); setReportModel(detail.analyses?.[0]?.model || '');
    if (detail.has_stl) {
      const response = await fetch(api(`/propellers/${id}/stl`)); const blob = await response.blob();
      const geometry = new STLLoader().parse(await blob.arrayBuffer());
      if (stlUrl) URL.revokeObjectURL(stlUrl);
      setMesh((current) => { current?.dispose(); return geometry; }); setStlUrl(URL.createObjectURL(blob));
    }
  });

  const remove = async (id) => { await fetch(api(`/propellers/${id}`), { method: 'DELETE' }); refresh(); };
  const createAirfoil = () => run(async () => {
    const response = await post('/airfoils', {
      name: airfoilForm.name, family: airfoilForm.family, source: airfoilForm.source,
      notes: airfoilForm.notes, camber: 0, thickness: 0.12,
    });
    const detail = await response.json();
    setAirfoils((current) => [...new Set([...current, detail.name])].sort());
    setSelectedAirfoil(detail.name); setAirfoilForm({ name: '', family: 'custom', source: 'user', notes: '' });
  });
  const updateAirfoil = () => run(async () => {
    const response = await fetch(api(`/airfoils/${encodeURIComponent(selectedAirfoil)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: selectedAirfoil, ...airfoilEdit, camber: airfoilDetail.camber, thickness: airfoilDetail.thickness }),
    });
    if (!response.ok) throw new Error('Airfoil update failed');
    const updated = await response.json();
    setAirfoilDetail((current) => ({ ...current, ...updated }));
  });
  const deleteAirfoil = () => run(async () => {
    const response = await fetch(api(`/airfoils/${encodeURIComponent(selectedAirfoil)}`), { method: 'DELETE' });
    if (!response.ok) throw new Error('Airfoil deletion failed');
    const remaining = airfoils.filter((name) => name !== selectedAirfoil);
    setAirfoils(remaining); setSelectedAirfoil(remaining[0] || ''); setAirfoilDetail(null);
    await refreshAirfoils();
  });
  const primary = 'flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-zinc-950 shadow-lg shadow-white/10 transition hover:-translate-y-px hover:bg-zinc-100 disabled:opacity-40';
  const secondary = 'flex w-full items-center justify-center gap-2 rounded-lg border border-white/10 bg-zinc-900/80 px-4 py-2.5 text-sm text-zinc-300 shadow-lg shadow-black/20 transition hover:border-white/20 hover:bg-zinc-800';

  return <main className="min-h-screen overflow-x-hidden bg-[#08080a] text-zinc-100 lg:flex lg:h-screen lg:flex-col lg:overflow-hidden">
    <header className="shrink-0 border-b border-white/[0.07] bg-zinc-950/80 px-4 py-4 shadow-2xl shadow-black/30 backdrop-blur-xl sm:px-6"><div className="flex w-full items-center justify-between">
      <div className="text-xs font-medium tracking-[0.24em] text-zinc-500">NOVA propellers</div>
      <span className="hidden self-center text-xs text-zinc-500 sm:block">Independent geometry and models</span>
    </div></header>
    <div className="grid w-full grid-cols-1 lg:min-h-0 lg:flex-1 lg:grid-cols-[clamp(360px,28vw,500px)_minmax(0,1fr)]">
      <aside className="border-b border-white/[0.07] bg-zinc-950/55 p-4 shadow-2xl shadow-black/30 sm:p-5 lg:h-full lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <div className="mb-6 overflow-x-auto pb-1"><nav className="grid min-w-[520px] grid-cols-5 gap-1 lg:min-w-0">{phases.map(([id, label, Icon], i) =>
          <button key={id} onClick={() => setPhase(id)} className={`rounded-lg p-2 text-left transition ${phase === id ? 'bg-white text-zinc-950 shadow-lg shadow-white/10' : 'text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200'}`}>
            <Icon size={15} /><span className="mt-1 block text-[10px]">{i + 1}. {label}</span>
          </button>)}</nav></div>
        <div className="space-y-4">
          {phase === 'sizing' && <>
            <Card title="Project configuration"><div className="space-y-3">
              <Field label="Project name" text value={inputs.project_name} onChange={(v) => set('project_name', v)} />
              <Select label="Propeller type" value={inputs.propeller_type} onChange={(v) => set('propeller_type', v)}
                options={[['traditional', 'Traditional'], ['toroidal', 'Toroidal — coming soon', true]]} />
              <Field label="Target thrust" value={inputs.thrust_target} unit="N" onChange={(v) => set('thrust_target', v)} />
            </div></Card>
            <Card title="Diameter selection"><div className="space-y-3">
              <Select label="Mode" value={inputs.diameter_mode} onChange={(v) => set('diameter_mode', v)}
                options={[['manual', 'Manual diameter'], ['actuator_disk', 'Actuator disk estimate']]} />
              {inputs.diameter_mode === 'manual'
                ? <Field label="Diameter" value={inputs.diameter} unit="m" onChange={(v) => set('diameter', v)} />
                : <><Field label="Disk loading" value={inputs.disk_loading} unit="N/m²" onChange={(v) => set('disk_loading', v)} />
                  <button className={secondary} onClick={estimate}>Estimate diameter</button></>}
              {sizing && <div className="rounded bg-zinc-950 p-3 text-xs text-zinc-400">Ø {sizing.diameter_m} m · vᵢ {sizing.induced_velocity_m_s} m/s · P {sizing.ideal_power_w} W</div>}
              <button className={primary} onClick={() => setPhase('geometry')}>Continue to geometry</button>
            </div></Card>
          </>}

          {phase === 'geometry' && <>
            <Card title="Geometry definition"><div className="grid grid-cols-2 gap-3">
              <Field label="Diameter" value={inputs.diameter} unit="m" onChange={(v) => set('diameter', v)} />
              <Field label="Design RPM" value={inputs.rpm} unit="rpm" onChange={(v) => set('rpm', v)} />
              <Field label="Blade count" value={inputs.blades} onChange={(v) => set('blades', v)} />
              <Select label="Airfoil" value={inputs.airfoil} onChange={(v) => set('airfoil', v)} options={airfoils.map((x) => [x, x])} />
            </div><div className="mt-3"><Select label="Design approach" value={designMode}
              onChange={(value) => {
                setDesignMode(value);
                if (value === 'inverse') set('geometry_method', 'bezier');
                setInverseResult(null);
              }}
              options={[['direct', 'Direct — geometry → performance'], ['inverse', 'Inverse — performance → geometry']]} /></div>
            {designMode === 'direct' && <div className="mt-3"><Select label="Geometry method" value={inputs.geometry_method}
              onChange={(v) => set('geometry_method', v)} options={[['bezier', 'Bézier curves'], ['laguerre', 'Laguerre polynomials']]} /></div>}
            {designMode === 'inverse' && <div className="mt-4 rounded-md border border-sky-900/60 bg-sky-950/20 p-3 text-xs leading-5 text-sky-200">
              The optimizer adjusts Bézier chord and twist to reach the target thrust while respecting the mesh geometry limits.
            </div>}</Card>
            {(designMode === 'inverse' || inputs.geometry_method === 'bezier') ? <>
              <Card title="Bézier control points"><div className="grid grid-cols-2 gap-3">
                {[['chord', 'Chord', bezier.chord_points.length], ['twist', 'Twist', bezier.twist_points.length]].map(([key, label, count]) =>
                  <div key={key} className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-3">
                    <div className="mb-2 text-xs">{label}</div>
                    <select className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs"
                      value={count} onChange={(event) => setBezierPointCount(key, event.target.value)}>
                      {Array.from({ length: 9 }, (_, index) => index + 2).map((value) =>
                        <option key={value} value={value}>{value} points</option>)}
                    </select>
                  </div>)}
              </div>
              {(bezier.chord_points.length > 4 || bezier.twist_points.length > 4) && <div className="mt-3 rounded-lg border border-amber-800/70 bg-amber-950/30 p-3 text-xs leading-5 text-amber-200">
                Manual sandbox active with more than 4 points. Direct geometry remains available, but inverse optimization is blocked by the safety guard.
              </div>}</Card>
              <CurveEditor label="Chord distribution" points={bezier.chord_points} max={inputs.diameter * .16} unit="m"
                onChange={(points) => { setBezier({ ...bezier, chord_points: points }); setInverseResult(null); }} />
              <CurveEditor label="Twist distribution" points={bezier.twist_points} max={45} unit="°"
                onChange={(points) => { setBezier({ ...bezier, twist_points: points }); setInverseResult(null); }} />
            </> : <Card title="Laguerre coefficients">{Object.keys(laguerre).map((key) =>
              <div key={key} className="mb-3"><div className="mb-2 text-xs text-zinc-500">{key.replace('_coefficients', '')}</div>
                <div className="grid grid-cols-4 gap-2">{laguerre[key].map((value, i) =>
                  <input key={i} className="w-full rounded border border-zinc-800 bg-zinc-950 p-2 text-xs" type="number" step="any" value={value}
                    onChange={(e) => setLaguerre({ ...laguerre, [key]: laguerre[key].map((x, j) => j === i ? Number(e.target.value) : x) })} />)}
                </div></div>)}</Card>}
            <Card title="Airfoil loft along the blade"><div className="space-y-3">
              <label className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/70 p-3 text-xs">
                <span>Use distributed DAT airfoils</span>
                <input type="checkbox" checked={useAirfoilLoft} disabled={coordinateAirfoils.length < 1}
                  onChange={(event) => { setUseAirfoilLoft(event.target.checked); setLoftPreview(null); }} />
              </label>
              {coordinateAirfoils.length < 1 && <p className="text-[10px] leading-4 text-zinc-500">Import at least one `.dat` airfoil in the Database section.</p>}
              {useAirfoilLoft && <>
                {inputs.geometry_method === 'bezier' ? <div className="space-y-2">
                  <p className="text-[10px] leading-4 text-zinc-500">Each chord control point also defines an airfoil station.</p>
                  {bezier.chord_points.map((point, index) => <div key={`${point.x}-${index}`} className="grid grid-cols-[90px_1fr] items-end gap-3 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                    <div><div className="mb-1 text-[9px] uppercase text-zinc-600">Station</div><div className="text-xs">r/R {point.x.toFixed(3)}</div></div>
                    <Select label={`Airfoil P${index + 1}`} value={bezierProfileAssignments[index] || coordinateAirfoils[0] || ''}
                      onChange={(value) => setBezierProfileAssignments((current) => current.map((item, itemIndex) => itemIndex === index ? value : item))}
                      options={coordinateAirfoils.map((name) => [name, name])} />
                  </div>)}
                </div> : <div className="space-y-2">
                  <p className="text-[10px] leading-4 text-zinc-500">Define the radial section positions freely for Laguerre geometry.</p>
                  {laguerreProfileAssignments.map((assignment, index) => <div key={index} className="grid grid-cols-[100px_1fr_32px] items-end gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                    <Field label="r/R position" value={assignment.radial_fraction}
                      onChange={(value) => updateLaguerreProfileStation(index, { radial_fraction: Math.max(0, Math.min(1, value)) })} />
                    <Select label="Airfoil" value={assignment.airfoil}
                      onChange={(value) => updateLaguerreProfileStation(index, { airfoil: value })}
                      options={coordinateAirfoils.map((name) => [name, name])} />
                    <button className="mb-0.5 h-9 rounded border border-red-900 text-xs text-red-300"
                      disabled={laguerreProfileAssignments.length <= 2 || index === 0 || index === laguerreProfileAssignments.length - 1}
                      onClick={() => setLaguerreProfileAssignments((current) => current.filter((_, itemIndex) => itemIndex !== index))}>×</button>
                  </div>)}
                  <button className={secondary} disabled={laguerreProfileAssignments.length >= 10} onClick={addLaguerreProfileStation}>Add airfoil station</button>
                </div>}
                <button className={secondary} onClick={previewLoft}>Preview section at r/R = 0.5</button>
                {loftPreview && <AirfoilShapeChart coordinates={loftPreview} title="Interpolated loft at r/R = 0.5" />}
              </>}
            </div></Card>
            {designMode === 'inverse' && <Card title="Optimization target"><div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Target thrust" value={inputs.thrust_target} unit="N" onChange={(v) => { set('thrust_target', v); setInverseResult(null); }} />
                <Field label="Speed" value={inputs.rpm} unit="rpm" onChange={(v) => { set('rpm', v); setInverseResult(null); }} />
              </div>
              <Select label="Solver used in the loss function" value={inverseSolver} onChange={(value) => { setInverseSolver(value); setInverseResult(null); }}
                options={(computationalMethods.length ? computationalMethods : [
                  { id: 'bemt', name: 'BEMT', fidelity: 'preliminary' },
                  { id: 'llt', name: 'LLT', fidelity: 'preliminary' },
                  { id: 'vlm', name: 'VLM', fidelity: 'experimental' },
                  { id: 'bem', name: 'BEM', fidelity: 'experimental' },
                ]).filter((method) => method.id !== 'actuator_disk')
                  .map((method) => [method.id, `${method.name} — ${method.fidelity}`])} />
              {computationalMethods.find((method) => method.id === inverseSolver) && <p className="text-[10px] leading-4 text-amber-300">
                {computationalMethods.find((method) => method.id === inverseSolver).description}
              </p>}
              <button className={primary} onClick={optimizeGeometry}
                disabled={busy || bezier.chord_points.length > 4 || bezier.twist_points.length > 4}>
                {busy ? <><Loader2 className="animate-spin" size={15} /> Optimizing…</> : <><Activity size={15} /> Find candidate geometry</>}
              </button>
            </div></Card>}
            {inverseResult && <Card title="Candidate geometry">
              <div className="mb-3 grid grid-cols-2 gap-2">
                <div className="rounded bg-zinc-950 p-3"><div className="text-[9px] uppercase text-zinc-600">Initial thrust</div>
                  <div className="mt-1 text-sm">{inverseResult.initial_performance.thrust.toFixed(3)} N</div></div>
                <div className="rounded bg-zinc-950 p-3"><div className="text-[9px] uppercase text-zinc-600">Optimized thrust</div>
                  <div className="mt-1 text-sm">{inverseResult.performance.thrust.toFixed(3)} N</div></div>
                <div className="rounded bg-zinc-950 p-3"><div className="text-[9px] uppercase text-zinc-600">Target error</div>
                  <div className="mt-1 text-sm">{(100 * Math.abs(inverseResult.performance.thrust - inputs.thrust_target) / inputs.thrust_target).toFixed(2)}%</div></div>
                <div className="rounded bg-zinc-950 p-3"><div className="text-[9px] uppercase text-zinc-600">Iterations</div>
                  <div className="mt-1 text-sm">{inverseResult.iterations}</div></div>
              </div>
              <div className={`mb-3 rounded p-2 text-xs ${inverseResult.success ? 'bg-emerald-950/40 text-emerald-300' : 'bg-amber-950/40 text-amber-300'}`}>
                {inverseResult.success ? 'Convergence achieved.' : `Usable but non-convergent solution: ${inverseResult.message}`}
              </div>
              <button className={primary} onClick={applyInverseResult} disabled={busy}>Apply and generate STL</button>
              <button className={`${secondary} mt-2`} onClick={() => setInverseResult(null)}>Discard candidate</button>
            </Card>}
            {designMode === 'direct' && <button className={primary} onClick={() => generate()} disabled={busy}>{busy ? 'Generating…' : 'Generate geometry'}</button>}
            {stlUrl && <a className={secondary} href={stlUrl} download={`nova_${inputs.geometry_method}.stl`}><Download size={15} /> Download STL</a>}
            {canonical && <button className={secondary} onClick={() => setPhase('forces')}>Continue to force analysis</button>}
          </>}

          {phase === 'forces' && <>
            <Card title="Computational model"><p className="mb-4 text-xs text-zinc-500">The model uses the canonical geometry without modifying it.</p>
              <Select label="Model" value={model} onChange={setModel} options={(computationalMethods.length ? computationalMethods : [
                { id: 'bemt', name: 'BEMT', fidelity: 'preliminary' },
                { id: 'llt', name: 'LLT', fidelity: 'preliminary' },
                { id: 'vlm', name: 'VLM', fidelity: 'experimental' },
                { id: 'bem', name: 'BEM', fidelity: 'experimental' },
              ]).filter((method) => method.role !== 'sizing_reference' && method.id !== 'actuator_disk')
                .map((method) => [method.id, `${method.name} — ${method.fidelity}`])} />
              {computationalMethods.find((method) => method.id === model) && <div className="mt-3 rounded bg-zinc-950 p-3 text-[10px] leading-4 text-zinc-400">
                {computationalMethods.find((method) => method.id === model).description}
              </div>}
              <button className={`${primary} mt-4`} disabled={!canonical || busy} onClick={analyze}><Play size={15} /> Run model</button>
              {!canonical && <p className="mt-3 text-xs text-amber-400">Generate the geometry first.</p>}
            </Card>
            {analyses.map((analysis) => <Card key={analysis.model} title={analysis.method}>
              <div className="grid grid-cols-2 gap-2">{Object.entries(analysis.summary).slice(0, 10).map(([key, value]) =>
                <div key={key} className="rounded bg-zinc-950 p-2"><div className="text-[9px] text-zinc-600">{key.replaceAll('_', ' ')}</div><div className="text-xs">{value}</div></div>)}</div>
            </Card>)}
            {canonical && <button className={secondary} onClick={() => setPhase('report')}>View report</button>}
          </>}

          {phase === 'report' && <>
            <Card title="Current project report">
              <p className="mb-4 text-xs leading-5 text-zinc-500">This section only shows geometry, results, and curves from the current session.</p>
              <div className="space-y-2">{analyses.map((analysis) =>
                <button key={analysis.model} onClick={() => setReportModel(analysis.model)}
                  className={`w-full rounded border p-3 text-left text-xs ${reportModel === analysis.model ? 'border-zinc-400 bg-zinc-900' : 'border-zinc-800 bg-zinc-950'}`}>
                  <div>{analysis.method || analysis.model}</div>
                  <div className="mt-1 text-[10px] text-zinc-600">{analysis.fidelity || 'legacy'} · curves {analysis.curve_source || 'unavailable'}</div>
                </button>)}</div>
              {!analyses.length && <div className="text-xs text-zinc-600">Run at least one model in the previous step.</div>}
            </Card>
            <button className={secondary} onClick={() => setPhase('database')}><Database size={14} /> Open database</button>
          </>}

          {phase === 'database' && <>
            <div className="grid grid-cols-2 gap-2">
              <button className={reportView === 'projects' ? primary : secondary} onClick={() => setReportView('projects')}>Projects</button>
              <button className={reportView === 'airfoils' ? primary : secondary} onClick={() => setReportView('airfoils')}>Airfoils and polars</button>
            </div>
            {reportView === 'projects' ? <>
              <Card title="Complete project"><p className="mb-4 text-xs text-zinc-500">Save inputs, geometry, STL, curves, and all analyses.</p>
                <button className={primary} disabled={!canonical || busy} onClick={save}><Save size={15} /> {savedId ? `Saved #${savedId}` : 'Save to database'}</button>
              </Card>
              <Card title="Saved projects"><div className="max-h-[480px] space-y-2 overflow-auto">{projects.map((project) =>
                <div key={project.id} className={`rounded border p-3 ${selectedProject?.id === project.id ? 'border-zinc-500 bg-zinc-900' : 'border-zinc-800 bg-zinc-950'}`}>
                  <button className="w-full text-left" onClick={() => open(project.id)}>
                    <div className="flex justify-between text-xs"><span>{project.project_name}</span><span className="text-zinc-600">#{project.id}</span></div>
                    <div className="mt-1 text-[10px] text-zinc-500">{project.geometry_method} · {(project.models || []).join(', ')}</div>
                    <div className="mt-1 text-[9px] text-zinc-700">{project.created_at}</div>
                  </button><div className="mt-2 flex gap-3 text-[10px]"><a href={api(`/propellers/${project.id}/stl`)}>STL</a>
                    <button className="text-red-400" onClick={() => remove(project.id)}>Delete</button></div>
                </div>)}</div></Card>
            </> : <>
              <Card title="Import XFOIL/UIUC coordinates">
                <p className="mb-3 text-xs leading-5 text-zinc-500">The `.dat` file will be cleaned and normalized automatically to 100 points.</p>
                <label className={`${primary} cursor-pointer`}>
                  <span>Select .dat file</span>
                  <input type="file" accept=".dat,text/plain" className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) importDatFile(file);
                      event.target.value = '';
                    }} />
                </label>
              </Card>
              <Card title="Available airfoils"><div className="max-h-56 space-y-1 overflow-auto">{airfoils.map((name) =>
                <button key={name} onClick={() => setSelectedAirfoil(name)}
                  className={`w-full rounded px-3 py-2 text-left text-xs ${selectedAirfoil === name ? 'bg-zinc-100 text-zinc-950' : 'bg-zinc-950 text-zinc-400'}`}>{name}</button>)}</div></Card>
              <Card title="New airfoil"><div className="space-y-2">
                <Field label="Name" text value={airfoilForm.name} onChange={(value) => setAirfoilForm({ ...airfoilForm, name: value })} />
                <Field label="Family" text value={airfoilForm.family} onChange={(value) => setAirfoilForm({ ...airfoilForm, family: value })} />
                <Field label="Source" text value={airfoilForm.source} onChange={(value) => setAirfoilForm({ ...airfoilForm, source: value })} />
                <button className={primary} disabled={!airfoilForm.name || busy} onClick={createAirfoil}>Create airfoil</button>
              </div></Card>
              {airfoilDetail && <Card title="Edit airfoil"><div className="space-y-2">
                <Field label="Family" text value={airfoilEdit.family} onChange={(value) => setAirfoilEdit({ ...airfoilEdit, family: value })} />
                <Field label="Source" text value={airfoilEdit.source} onChange={(value) => setAirfoilEdit({ ...airfoilEdit, source: value })} />
                <Field label="Notes" text value={airfoilEdit.notes} onChange={(value) => setAirfoilEdit({ ...airfoilEdit, notes: value })} />
                <button className={secondary} onClick={updateAirfoil}>Update</button>
                <button className="w-full rounded border border-red-900 p-2 text-xs text-red-300" onClick={deleteAirfoil}>Delete airfoil</button>
              </div></Card>}
            </>}
          </>}
        </div>
        {error && <div className="mt-4 flex gap-2 rounded border border-red-900 bg-red-950/30 p-3 text-xs text-red-300"><AlertCircle size={14} />{error}</div>}
      </aside>
      {phase === 'report' ? <section className="min-w-0 min-h-[620px] bg-zinc-950 lg:h-full lg:min-h-0">
        <ReportWorkspace
          project={{ project_name: inputs.project_name }}
          analyses={analyses}
          geometry={canonical}
          selectedModel={reportModel}
          onSelectModel={setReportModel}
          stlUrl={stlUrl}
        />
      </section> : phase === 'database' ? <section className="min-w-0 min-h-[620px] bg-zinc-950 lg:h-full lg:min-h-0">
        {reportView === 'projects'
          ? selectedProject
            ? <ReportWorkspace
                project={selectedProject}
                analyses={selectedProject.analyses || []}
                geometry={selectedProject.geometry}
                selectedModel={reportModel}
                onSelectModel={setReportModel}
                stlUrl={stlUrl}
              />
            : <div className="grid h-full min-h-[620px] place-items-center text-sm text-zinc-600 lg:min-h-0">Select an archived project.</div>
          : <AirfoilWorkspace detail={airfoilDetail} />}
      </section> : <section className="relative min-w-0 min-h-[620px] overflow-hidden bg-[radial-gradient(circle_at_50%_40%,#27272a_0%,#09090b_52%,#050506_100%)] shadow-inner shadow-black lg:h-full lg:min-h-0">
        <PropellerViewport geometry={mesh} displayMode={displayMode} />
        <div className="absolute right-6 top-6 z-10 flex rounded-xl border border-white/10 bg-zinc-950/75 p-1 shadow-2xl shadow-black/40 backdrop-blur-xl">
          {[['surface', 'Surface'], ['mesh', 'Mesh']].map(([id, label]) =>
            <button key={id} onClick={() => setDisplayMode(id)}
              className={`rounded-lg px-4 py-2 text-xs font-medium transition ${displayMode === id ? 'bg-white text-zinc-950 shadow-md' : 'text-zinc-400 hover:text-white'}`}>
              {label}
            </button>)}
        </div>
        <div className="absolute left-6 top-6 flex gap-2 text-[10px] text-zinc-400">
          <span className="rounded border border-zinc-800 bg-zinc-950/80 px-2 py-1">{inputs.propeller_type}</span>
          <span className="rounded border border-zinc-800 bg-zinc-950/80 px-2 py-1">geometry: {inputs.geometry_method}</span>
          <span className="rounded border border-zinc-800 bg-zinc-950/80 px-2 py-1">model: {model}</span>
        </div>
        {!mesh && <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-zinc-600">Generate geometry to view the blade</div>}
        {busy && <div className="absolute inset-0 grid place-items-center bg-zinc-950/35"><div className="flex gap-2 rounded bg-zinc-950 p-3 text-xs"><Loader2 className="animate-spin" size={15} /> Processing</div></div>}
        <div className="absolute inset-x-0 bottom-0 border-t border-zinc-900 bg-zinc-950/80 px-6 py-3 text-xs text-zinc-500">
          {canonical ? `${canonical.stations.length} stations · ${inputs.blades} blades · Ø ${inputs.diameter} m` : 'No canonical geometry generated'}
        </div>
      </section>
      }
    </div>
  </main>;
}

export default App;
