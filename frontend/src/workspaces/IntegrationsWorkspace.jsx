import { useEffect, useState } from 'react';
import { download, fileBase64, request } from '../backend.js';
import WindFarmLayout from '../components/WindFarmLayout.jsx';
import OpenFASTCaseInspection from './OpenFASTCaseInspection.jsx';

const button = 'rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs disabled:opacity-40';
const field = 'mt-1 block w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-sm';
const panel = 'space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4';
const active = (run) => ['queued', 'running', 'cancelling'].includes(run?.state);
const format = (value) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumSignificantDigits: 7 });
const numbers = (text, label) => {
  const values = text.split(',').map((v) => v.trim());
  if (values.some((v) => !v || !Number.isFinite(Number(v)))) throw new Error(`${label}: enter comma-separated numbers`);
  return values.map(Number);
};

function Input({ label, value, onChange, type = 'text' }) {
  return <label className="block text-xs text-zinc-400">{label}<input aria-label={label} className={field} type={type} step={type === 'number' ? 'any' : undefined} value={value} onChange={(e) => onChange(e.target.value)} /></label>;
}

export function OpenFastResult({ data }) {
  const [selection, setSelection] = useState('');
  const channels = data.channels || [];
  const selected = channels.findIndex((c) => c.name === selection);
  const index = selected < 0 ? 0 : selected;
  const channel = channels[index];
  const points = (data.time_s || []).map((t, row) => [t, data.values?.[row]?.[index]]).filter(([t, y]) => Number.isFinite(t) && Number.isFinite(y));
  if (!channel || !points.length) return <p className="text-xs text-zinc-400">No channel samples available.</p>;
  let low = Infinity, high = -Infinity;
  for (const [, y] of points) { low = Math.min(low, y); high = Math.max(high, y); }
  const first = points[0][0], last = points.at(-1)[0];
  // Bound SVG size while keeping extrema and every sample in the summary and CSV.
  const stride = Math.max(1, Math.ceil(points.length / 998));
  const displayed = points.filter((_, i) => i % stride === 0 || i === points.length - 1);
  const line = displayed.map(([t, y]) => `${65 + (t - first) / Math.max(last - first, 1e-12) * 500},${175 - (y - low) / Math.max(high - low, 1e-12) * 140}`).join(' ');
  return <div className="space-y-3">
    <label className="block text-xs text-zinc-400">Output channel<select aria-label="OpenFAST output channel" className={field} value={channel.name} onChange={(e) => setSelection(e.target.value)}>{channels.map((c) => <option key={c.name} value={c.name}>{c.name} {c.units}</option>)}</select></label>
    <div className="flex flex-wrap gap-4 text-xs text-zinc-400"><span>Minimum: {format(low)} {channel.units}</span><span>Maximum: {format(high)} {channel.units}</span><span>{points.length} samples · {format(first)}–{format(last)} s</span></div>
    <svg viewBox="0 0 600 220" role="img" aria-label={`${channel.name} versus time`} className="max-h-72 w-full rounded border border-zinc-800 bg-zinc-950">
      <path d="M65 25V180H570" fill="none" stroke="#52525b" /><polyline points={line} fill="none" stroke="#a5b4fc" strokeWidth="1.5" />
      <text x="5" y="40" fill="#a1a1aa" fontSize="10">{format(high)}</text><text x="5" y="178" fill="#a1a1aa" fontSize="10">{format(low)}</text>
      <text x="65" y="200" fill="#a1a1aa" fontSize="10">{format(first)} s</text><text x="515" y="200" fill="#a1a1aa" fontSize="10">{format(last)} s</text>
    </svg>
    <p className="text-xs text-zinc-500">{channel.name} {channel.units} · Original output units and channel names are retained. Reference frames and signs remain unspecified unless supplied by the source. {stride > 1 && 'Plot samples are reduced for display; CSV retains all samples.'}</p>
    <p className="text-xs text-zinc-400">{data.description}</p>
    {data.source && <p className="break-all text-[10px] text-zinc-500">Source: {data.source.filename} · {data.source.format} · SHA256 {data.source.sha256}</p>}
  </div>;
}

export function PyWakeResult({ data }) {
  const turbines = (data.aep_gwh || []).map((aep, index) => ({ index, aep_gwh: aep, baseline_aep_gwh: data.aep_without_wakes_gwh?.[index], x_m: data.layout?.x_m[index], y_m: data.layout?.y_m[index] }));
  const conditions = turbines.flatMap((t) => (data.directions_deg || []).flatMap((direction, d) => (data.speeds_m_s || []).map((speed, s) => ({ turbine_index: t.index, direction_deg: direction, speed_m_s: speed, probability: data.probabilities?.[d]?.[s], effective_speed_m_s: data.effective_speed_m_s?.[t.index]?.[d]?.[s], power_w: data.power_w?.[t.index]?.[d]?.[s] }))));
  return <div className="space-y-4 text-xs">
    <h4 className="text-sm">Wind farm performance</h4>
    <p className="text-zinc-400">Total AEP: {format(data.total_aep_gwh)} GWh/year · {data.wake_model || 'NOJ'} wake model. AEP depends on the supplied discrete probability distribution. Without wakes: {format(data.total_aep_without_wakes_gwh)} GWh/year · Wake loss: {data.wake_loss_fraction == null ? '—' : `${format(data.wake_loss_fraction * 100)}%`}.</p>
    <div className="overflow-x-auto"><table className="w-full text-left"><thead className="text-zinc-500"><tr>{['Turbine', 'x [m]', 'y [m]', 'AEP [GWh/year]', 'Without wakes [GWh/year]'].map((name) => <th className="p-2" key={name}>{name}</th>)}</tr></thead><tbody>{turbines.map((t, i) => <tr className="border-t border-zinc-800" key={i}><td className="p-2">{t.index ?? i}</td><td className="p-2">{format(t.x_m)}</td><td className="p-2">{format(t.y_m)}</td><td className="p-2">{format(t.aep_gwh)}</td><td className="p-2">{format(t.baseline_aep_gwh)}</td></tr>)}</tbody></table></div>
    <p className="text-zinc-500">PyWake {data.program_version} · {(data.assumptions || []).join('; ')}</p>
    <h4 className="text-sm">Condition results</h4>
    <div className="max-h-72 overflow-auto"><table className="w-full text-left"><thead className="text-zinc-500"><tr>{['Turbine', 'Direction [°]', 'Wind speed [m/s]', 'Probability', 'Effective speed [m/s]', 'Power [W]'].map((name) => <th className="p-2" key={name}>{name}</th>)}</tr></thead><tbody>{conditions.map((c, i) => <tr key={i} className="border-t border-zinc-800">{[c.turbine_index, c.direction_deg, c.speed_m_s, c.probability, c.effective_speed_m_s, c.power_w].map((v, j) => <td key={j} className="p-2">{format(v)}</td>)}</tr>)}</tbody></table></div>
  </div>;
}

export default function IntegrationsWorkspace({ activeExecution, onExecutionChange, draft = {}, onDraftChange }) {
  const [adapters, setAdapters] = useState([]);
  const [configurations, setConfigurations] = useState([]);
  const [selected, setSelected] = useState(draft.selected || '');
  const [configurationId, setConfigurationId] = useState(draft.configurationId || '');
  const [executable, setExecutable] = useState(draft.executable || '');
  const [environment, setEnvironment] = useState(draft.environment || 'local_executable');
  const [probe, setProbe] = useState(draft.probe || null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState([]);
  const [current, setCurrent] = useState(activeExecution || null);
  const [layout, setLayout] = useState(draft.layout || [{ x: '0', y: '0' }, { x: '500', y: '0' }]);
  const [curve, setCurve] = useState(draft.curve || [{ speed: '3', power: '0', ct: '0.8' }, { speed: '8', power: '1000000', ct: '0.8' }, { speed: '12', power: '3000000', ct: '0.7' }, { speed: '25', power: '3000000', ct: '0.1' }]);
  const [turbine, setTurbine] = useState(draft.turbine || { name: 'Demonstration turbine', diameter: '100', height: '100' });
  const [wind, setWind] = useState(draft.wind || { directions: '270', speeds: '8, 12', probabilities: '[[0.5, 0.5]]', turbulence: '0.1' });
  const [caseDirectory, setCaseDirectory] = useState(draft.caseDirectory || '');
  const [inputFile, setInputFile] = useState(draft.inputFile || '');
  const [outputFile, setOutputFile] = useState(draft.outputFile || '');
  const [timeout, setTimeoutValue] = useState(draft.timeout || '300');
  const [caseAssets, setCaseAssets] = useState([]);
  const [caseAssetId, setCaseAssetId] = useState(draft.caseAssetId || '');
  const [caseName, setCaseName] = useState(draft.caseName || 'Wind farm case');
  const [caseNotes, setCaseNotes] = useState(draft.caseNotes || '');
  const [caseDemonstration, setCaseDemonstration] = useState(draft.caseDemonstration ?? true);
  const [caseMessage, setCaseMessage] = useState('');
  useEffect(() => {
    onDraftChange?.({ selected, configurationId, executable, environment, probe, layout, curve, turbine, wind, caseDirectory, inputFile, outputFile, timeout, caseAssetId, caseName, caseNotes, caseDemonstration });
  }, [selected, configurationId, executable, environment, probe, layout, curve, turbine, wind, caseDirectory, inputFile, outputFile, timeout, caseAssetId, caseName, caseNotes, caseDemonstration, onDraftChange]);
  const refreshRuns = async () => setRuns(await request('/v1/external-runs'));
  useEffect(() => {
    let valid = true;
    Promise.all([request('/v1/adapters'), request('/v1/integrations'), request('/v1/external-runs'), request('/v1/external-cases')]).then(([a, c, r, cases]) => { if (valid) { setAdapters(a); setConfigurations(c); setRuns(r); setCaseAssets(cases); setCurrent((previous) => previous || r.find(active) || null); } }).catch((e) => { if (valid) setError(e.message); });
    return () => { valid = false; };
  }, []);
  useEffect(() => { if (current) onExecutionChange?.(current); }, [current, onExecutionChange]);
  useEffect(() => {
    if (activeExecution) setCurrent((previous) => !previous || previous.id === activeExecution.id ? activeExecution : previous);
  }, [activeExecution]);
  const currentId = current?.id, currentState = current?.state;
  useEffect(() => {
    if (!currentId || ['queued', 'running', 'cancelling'].includes(currentState)) return undefined;
    let valid = true;
    request('/v1/external-runs').then((records) => { if (valid) setRuns(records); }).catch((e) => { if (valid) setError(e.message); });
    return () => { valid = false; };
  }, [currentId, currentState]);
  const descriptor = adapters.find((a) => a.id === selected);
  const act = async (action) => {
    setBusy(true); setError('');
    try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const selectAdapter = (id) => {
    const adapter = adapters.find((a) => a.id === id);
    setSelected(id); setEnvironment(adapter?.environments[0] || 'local_executable'); setExecutable(''); setConfigurationId(''); setProbe(null);
  };
  const selectConfiguration = (id) => {
    setConfigurationId(id);
    const saved = configurations.find((c) => c.id === id);
    if (saved) { setSelected(saved.adapter_id); setEnvironment(saved.environment_kind); setExecutable(saved.executable); setProbe(saved.probe); }
  };
  const configure = (save) => act(async () => {
    const result = await request(`/v1/adapters/${selected}/${save ? 'configure' : 'probe'}`, { executable, environment_kind: environment, options: {} });
    setProbe(save ? result.probe : result);
    if (save) { setConfigurations(await request('/v1/integrations')); setConfigurationId(result.id); }
  });
  const pywakeCase = () => {
      const directions = numbers(wind.directions, 'Wind directions'), speeds = numbers(wind.speeds, 'Wind speeds');
      const probabilities = JSON.parse(wind.probabilities);
      if (!Array.isArray(probabilities) || probabilities.length !== directions.length || probabilities.some((row) => !Array.isArray(row) || row.length !== speeds.length || row.some((p) => typeof p !== 'number' || !Number.isFinite(p) || p < 0))) throw new Error('Probabilities must be a direction × speed matrix of nonnegative numbers');
      const sum = probabilities.flat().reduce((a, b) => a + b, 0);
      if (Math.abs(sum - 1) > 1e-9) throw new Error('Wind probabilities must sum to 1');
      const numeric = (value) => { if (String(value).trim() === '' || !Number.isFinite(Number(value))) throw new Error('Complete every turbine and layout numeric field'); return Number(value); };
      return { turbine: { name: turbine.name, diameter_m: numeric(turbine.diameter), hub_height_m: numeric(turbine.height), wind_speed_m_s: curve.map((r) => numeric(r.speed)), power_w: curve.map((r) => numeric(r.power)), ct: curve.map((r) => numeric(r.ct)) },
        layout: { x_m: layout.map((r) => numeric(r.x)), y_m: layout.map((r) => numeric(r.y)) }, wind: { directions_deg: directions, speeds_m_s: speeds, probabilities, turbulence_intensity: numeric(wind.turbulence) }, wake_model: 'noj', timeout_seconds: numeric(timeout) };
  };
  const saveCase = () => act(async () => {
    const saved = await request('/v1/external-cases', { name: caseName, case: pywakeCase(), notes: caseNotes, demonstration: caseDemonstration });
    setCaseAssets(await request('/v1/external-cases')); setCaseAssetId(saved.id);
    setCaseMessage(`Saved case copy: ${saved.name}. The earlier saved case is unchanged.`);
  });
  const loadCase = () => act(async () => {
    const saved = await request(`/v1/external-cases/${caseAssetId}`);
    const { turbine: t, wind: w, layout: l } = saved.case;
    setTurbine({ name: t.name, diameter: String(t.diameter_m), height: String(t.hub_height_m) });
    setCurve(t.wind_speed_m_s.map((speed, i) => ({ speed: String(speed), power: String(t.power_w[i]), ct: String(t.ct[i]) })));
    setLayout(l.x_m.map((x, i) => ({ x: String(x), y: String(l.y_m[i]) })));
    setWind({ directions: w.directions_deg.join(', '), speeds: w.speeds_m_s.join(', '), probabilities: JSON.stringify(w.probabilities), turbulence: String(w.turbulence_intensity) });
    setTimeoutValue(String(saved.case.timeout_seconds ?? 300)); setCaseName(saved.name); setCaseNotes(saved.notes); setCaseDemonstration(saved.demonstration);
    setCaseMessage(`Loaded saved inputs: ${saved.name}. Local software selection is unchanged.`);
  });
  const runCase = () => act(async () => {
    if (!configurationId) throw new Error('Select a saved configuration before running');
    const definition = selected === 'pywake' ? pywakeCase() : { case_directory: caseDirectory, input_file: inputFile, output_file: outputFile, timeout_seconds: Number(timeout) };
    setCurrent(await request('/v1/external-runs', { integration_id: configurationId, case: definition }));
    await refreshRuns();
  });
  const importOutput = (file) => act(async () => {
    setCurrent(await request('/v1/openfast/import', { filename: file.name, content_base64: await fileBase64(file) }));
    await refreshRuns();
  });
  const importArchive = (file) => act(async () => {
    setCurrent(await request('/v1/external-runs/import', { content_base64: await fileBase64(file, 128 * 1024 * 1024) }));
    await refreshRuns();
  });
  const updateRow = (setter, index, key, value) => setter((rows) => rows.map((row, i) => i === index ? { ...row, [key]: value } : row));
  const result = current?.result;
  const executing = active(current) || active(activeExecution);
  return <section className="min-w-0 space-y-5 overflow-auto p-6 lg:p-8"><h2 className="text-xl">Integrations</h2>
    <p className="text-sm text-zinc-400">External software is installed independently. NOVA prepares isolated cases, captures logs and preserves normalized results alongside source files.</p>
    <div className={panel}><h3 className="text-sm">Portable external results</h3>
      <p className="text-xs text-zinc-400">Open a .nova-run archive to recover results, source files and provenance. Executable paths and local software configurations are excluded; importing an archive does not run a solver.</p>
      <label className={`${button} inline-block cursor-pointer`}>Open external archive<input aria-label="Open external archive" type="file" accept=".nova-run" className="hidden" disabled={busy || active(current)} onChange={(e) => { const file = e.target.files?.[0]; if (file) importArchive(file); e.target.value = ''; }} /></label>
    </div>
    <div className={panel}><h3 className="text-sm">OpenFAST result import</h3>
      <p className="text-xs text-zinc-400">Import ASCII .out or binary .outb output without installing OpenFAST. Original channel names, units and source provenance are preserved.</p>
      <label className={`${button} inline-block cursor-pointer`}>Import OpenFAST output<input aria-label="Import OpenFAST output" type="file" accept=".out,.outb" className="hidden" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; if (file) importOutput(file); e.target.value = ''; }} /></label>
    </div>
    <div className={panel}><h3 className="text-sm">External software configuration</h3>
      <label className="block text-xs text-zinc-400">Adapter<select aria-label="External adapter" className={field} value={selected} onChange={(e) => selectAdapter(e.target.value)}><option value="">Select adapter…</option>{adapters.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
      {adapters.length === 0 && <p className="text-xs text-zinc-400">No executable adapters are available. Result import remains available.</p>}
      {descriptor && <>
        <p className="text-xs text-zinc-400">{descriptor.description}</p>
        <label className="block text-xs text-zinc-400">Saved configuration<select aria-label="Saved integration configuration" className={field} value={configurationId} onChange={(e) => selectConfiguration(e.target.value)}><option value="">New configuration…</option>{configurations.filter((c) => c.adapter_id === selected).map((c) => <option key={c.id} value={c.id}>{c.executable} · {c.probe?.version || 'version unknown'}</option>)}</select></label>
        <Input label={selected === 'pywake' ? 'Python environment interpreter' : 'Solver executable'} value={executable} onChange={(value) => { setExecutable(value); setConfigurationId(''); setProbe(null); }} />
        <label className="block text-xs text-zinc-400">Environment<select aria-label="Execution environment" className={field} value={environment} onChange={(e) => { setEnvironment(e.target.value); setConfigurationId(''); setProbe(null); }}>{descriptor.environments.map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select></label>
        <div className="flex gap-2"><button className={button} disabled={busy || !executable} onClick={() => configure(false)}>Detect and validate</button><button className={button} disabled={busy || !executable} onClick={() => configure(true)}>Save configuration</button></div>
        {probe && <div className="text-xs text-zinc-400"><p>{probe.available ? 'Detected' : 'Unavailable'} · {probe.compatible ? 'Compatible' : 'Incompatible'} · {probe.version || 'unknown version'}</p><p>{probe.message}</p></div>}
      </>}
    </div>
    {selected === 'pywake' && <div className={panel}><h3 className="text-sm">PyWake wind farm case</h3>
      <div className="space-y-3 rounded border border-zinc-800 p-3"><h4 className="text-sm">Saved wind farm cases</h4>
        <p className="text-xs text-zinc-400">Reuse turbine curves, layouts and wind conditions independently of installed software. Saving creates an immutable copy. Loading replaces the inputs below.</p>
        <label className="block text-xs text-zinc-400">Saved wind farm case<select aria-label="Saved wind farm case" className={field} value={caseAssetId} onChange={(e) => { setCaseAssetId(e.target.value); setCaseMessage(''); }}><option value="">Select saved inputs…</option>{caseAssets.map((saved) => <option key={saved.id} value={saved.id}>{saved.name}{saved.demonstration ? ' · demonstration' : ''} · {saved.updated_at} · {saved.id.slice(0, 8)}</option>)}</select></label>
        <button className={button} disabled={busy || !caseAssetId} onClick={loadCase}>Load saved case (replace inputs)</button>
        <div className="grid gap-3 sm:grid-cols-2"><Input label="Case name" value={caseName} onChange={(value) => { setCaseName(value); setCaseMessage(''); }} /><Input label="Case notes" value={caseNotes} onChange={(value) => { setCaseNotes(value); setCaseMessage(''); }} /></div>
        <label className="flex items-center gap-2 text-xs text-zinc-400"><input aria-label="Case contains demonstration data" type="checkbox" checked={caseDemonstration} onChange={(e) => setCaseDemonstration(e.target.checked)} />Case contains synthetic or demonstration data</label>
        <button className={button} disabled={busy || !caseName.trim()} onClick={saveCase}>Save case copy</button>
        {caseMessage && <p role="status" className="text-xs text-indigo-300">{caseMessage}</p>}
      </div>
      <p className="text-xs text-zinc-500">Case drafts stay available while switching workspaces in this session. Save a case copy to retain inputs after closing NOVA.</p>
      {caseDemonstration && <p className="rounded border border-amber-900 bg-amber-950/20 p-3 text-xs text-amber-300">Demonstration inputs: this turbine curve is synthetic and has not been validated for a real turbine. Replace the curve and wind probabilities with engineering data before using results for decisions. Wake model: NOJ.</p>}
      <p className="text-xs text-zinc-400">Wake model: NOJ. Local coordinates: x east, y north [m]. Wind directions follow the meteorological convention, clockwise from north.</p>
      <div className="grid gap-3 sm:grid-cols-3"><Input label="Turbine name" value={turbine.name} onChange={(name) => setTurbine({ ...turbine, name })} /><Input label="Rotor diameter [m]" type="number" value={turbine.diameter} onChange={(diameter) => setTurbine({ ...turbine, diameter })} /><Input label="Hub height [m]" type="number" value={turbine.height} onChange={(height) => setTurbine({ ...turbine, height })} /></div>
      <h4 className="text-xs">Turbine layout</h4><div className="space-y-2">{layout.map((row, i) => <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2"><Input label={`Turbine ${i + 1} x [m]`} type="number" value={row.x} onChange={(v) => updateRow(setLayout, i, 'x', v)} /><Input label={`Turbine ${i + 1} y [m]`} type="number" value={row.y} onChange={(v) => updateRow(setLayout, i, 'y', v)} /><button className={button} disabled={layout.length <= 1} onClick={() => setLayout(layout.filter((_, j) => j !== i))}>Remove</button></div>)}</div>
      <button className={button} onClick={() => setLayout([...layout, { x: '', y: '' }])}>Add turbine</button>
      <WindFarmLayout layout={layout} />
      <h4 className="text-xs">Shared turbine power and thrust coefficient curve</h4><div className="space-y-2">{curve.map((row, i) => <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2">{[['speed', 'Wind speed [m/s]'], ['power', 'Power [W]'], ['ct', 'Ct']].map(([key, label]) => <Input key={key} label={`Curve ${i + 1} ${label}`} type="number" value={row[key]} onChange={(v) => updateRow(setCurve, i, key, v)} />)}<button className={button} disabled={curve.length <= 2} onClick={() => setCurve(curve.filter((_, j) => j !== i))}>Remove</button></div>)}</div>
      <button className={button} onClick={() => setCurve([...curve, { speed: '', power: '', ct: '' }])}>Add curve point</button>
      <div className="grid gap-3 sm:grid-cols-2"><Input label="Wind directions [degrees, comma separated]" value={wind.directions} onChange={(directions) => setWind({ ...wind, directions })} /><Input label="Wind speeds [m/s, comma separated]" value={wind.speeds} onChange={(speeds) => setWind({ ...wind, speeds })} /><Input label="Turbulence intensity [fraction]" type="number" value={wind.turbulence} onChange={(turbulence) => setWind({ ...wind, turbulence })} /></div>
      <label className="block text-xs text-zinc-400">Wind probabilities<textarea aria-label="Wind probabilities" className={field} value={wind.probabilities} onChange={(e) => setWind({ ...wind, probabilities: e.target.value })} /></label>
      <p className="text-xs text-zinc-500">JSON matrix: one row per direction and one column per speed, in the entered order. For one direction and two speeds: [[0.5, 0.5]]. All probabilities must be nonnegative and sum to 1.</p>
      <Input label="Execution timeout [seconds]" type="number" value={timeout} onChange={setTimeoutValue} />
      <button className={button} disabled={busy || executing || !configurationId} onClick={runCase}>Run PyWake case</button>
    </div>}
    {selected === 'openfast' && <div className={panel}><h3 className="text-sm">Run an existing OpenFAST case</h3>
      <p className="text-xs text-zinc-400">Supply an existing complete case directory. NOVA copies case files into an isolated working directory; referenced input files must remain inside the case. Result import above works independently of a solver configuration.</p>
      <Input label="Case directory" value={caseDirectory} onChange={setCaseDirectory} /><Input label="Input .fst file (relative to case)" value={inputFile} onChange={setInputFile} /><Input label="Expected .out or .outb file (relative to case)" value={outputFile} onChange={setOutputFile} /><Input label="Execution timeout [seconds]" type="number" value={timeout} onChange={setTimeoutValue} />
      <OpenFASTCaseInspection definition={{ case_directory: caseDirectory, input_file: inputFile, output_file: outputFile, timeout_seconds: Number(timeout) }} disabled={busy || !caseDirectory || !inputFile || !outputFile} />
      <button className={button} disabled={busy || executing || !configurationId || !caseDirectory || !inputFile || !outputFile} onClick={runCase}>Run OpenFAST case</button>
    </div>}
    <div className={panel}><h3 className="text-sm">Saved external runs</h3><label className="block text-xs text-zinc-400">Reopen result<select aria-label="Saved external run" className={field} value={current?.id || ''} onChange={(e) => { if (e.target.value) act(async () => setCurrent(await request(`/v1/runs/${e.target.value}`))); }}><option value="">Select run…</option>{runs.map((r) => <option key={r.id} value={r.id}>{r.result?.adapter_id || r.external_job?.adapter_id || 'External'} · {r.state} · {r.created_at} · {r.id.slice(0, 8)}</option>)}</select></label></div>
    {current && <div className={panel}><h3 className="text-sm">External run · {current.state} · {Math.round((current.progress || 0) * 100)}%</h3>
      {!active(current) && <button className={button} disabled={busy} onClick={() => act(() => download(`/v1/external-runs/${current.id}/archive`, `${current.result?.adapter_id || 'external'}-${current.id.slice(0, 8)}.nova-run`))}>Export external archive</button>}
      {current.imported_from_run && <p className="text-xs text-indigo-300">Portable result imported from run {current.imported_from_run}. Configure locally installed software separately to execute a new case.</p>}
      {current.error && <p role="alert" className="text-xs text-red-400">{current.error}</p>}
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[10px] text-zinc-400">{(current.logs || []).join('\n')}</pre>
      {result && <div className="flex flex-wrap gap-2">{result.data && <button className={button} onClick={() => act(() => download(`/v1/external-runs/${current.id}/csv`, `${result.adapter_id}-results.csv`))}>Export external CSV</button>}{(result.artifacts || []).map((name) => <button key={name} className={button} onClick={() => act(() => download(`/v1/external-runs/${current.id}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}`, name.split('/').at(-1)))}>{name}</button>)}</div>}
      {result?.data && <>
        {result.adapter_id === 'openfast' ? <OpenFastResult key={current.id} data={result.data} /> : result.adapter_id === 'pywake' ? <PyWakeResult data={result.data} /> : <p className="text-xs text-zinc-400">Normalized result available through export.</p>}
      </>}
    </div>}
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
  </section>;
}
