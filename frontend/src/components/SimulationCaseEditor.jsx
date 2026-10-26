import { useState } from 'react';

const field = 'mt-1 w-full rounded border border-zinc-700 bg-zinc-950 p-2 text-xs';
export default function SimulationCaseEditor({ kind, text, onChange, disabled }) {
  const [advanced, setAdvanced] = useState(false);
  let configuration;
  try { configuration = JSON.parse(text); } catch { configuration = null; }
  const change = (edit) => { const next = structuredClone(configuration); edit(next); onChange(JSON.stringify(next, null, 2)); };
  const input = (label, value, apply, type = 'number') => <label key={label} className="block text-xs text-zinc-400">{label}<input aria-label={label} className={field} type={type} step="any" disabled={disabled} value={value ?? ''} onChange={(e) => change((next) => apply(next, type === 'number' ? Number(e.target.value) : e.target.value))} /></label>;
  const data = configuration?.case;
  return <div className="space-y-5">
    {data && kind === 'openfast' && <div className="grid gap-3 md:grid-cols-2">
      {input('Source case directory', data.case_directory, (next, value) => { next.case.case_directory = value; if (value) delete next.asset_id; }, 'text')}
      {input('Main input file', data.input_file, (next, value) => { next.case.input_file = value; }, 'text')}
      {input('Output file', data.output_file, (next, value) => { next.case.output_file = value; }, 'text')}
      {input('Timeout [s]', data.timeout_seconds, (next, value) => { next.case.timeout_seconds = value; })}
      {configuration.asset_id && <p className="text-xs text-emerald-300">Saved source files are frozen in this project. Enter a source directory to acquire updated files.</p>}
    </div>}
    {data?.turbine && data?.layout && data?.wind && kind === 'pywake' && <>
      <div className="grid gap-3 md:grid-cols-3">
        {input('Turbine name', data.turbine.name, (next, value) => { next.case.turbine.name = value; }, 'text')}
        {input('Rotor diameter [m]', data.turbine.diameter_m, (next, value) => { next.case.turbine.diameter_m = value; })}
        {input('Hub height [m]', data.turbine.hub_height_m, (next, value) => { next.case.turbine.hub_height_m = value; })}
      </div>
      <div><h3 className="mb-3 text-sm">Wind farm layout</h3><div className="space-y-2">{data.layout.x_m.map((x, i) => <div className="grid grid-cols-[1fr_1fr_auto] items-end gap-3" key={i}>
        {input(`Turbine ${i + 1} x [m]`, x, (next, value) => { next.case.layout.x_m[i] = value; })}
        {input(`Turbine ${i + 1} y [m]`, data.layout.y_m[i], (next, value) => { next.case.layout.y_m[i] = value; })}
        <button disabled={disabled || data.layout.x_m.length < 2} className="p-2 text-xs disabled:opacity-30" onClick={() => change((next) => { next.case.layout.x_m.splice(i, 1); next.case.layout.y_m.splice(i, 1); })}>Remove</button>
      </div>)}</div><button disabled={disabled} className="mt-3 rounded border border-zinc-700 p-2 text-xs" onClick={() => change((next) => { next.case.layout.x_m.push(0); next.case.layout.y_m.push(0); })}>Add turbine</button></div>
      <div><h3 className="mb-3 text-sm">Power and thrust coefficient curves</h3>{data.turbine.wind_speed_m_s.map((speed, i) => <div className="mb-2 grid grid-cols-3 gap-3" key={i}>
        {input(`Curve ${i + 1} wind speed [m/s]`, speed, (next, value) => { next.case.turbine.wind_speed_m_s[i] = value; })}
        {input(`Curve ${i + 1} power [W]`, data.turbine.power_w[i], (next, value) => { next.case.turbine.power_w[i] = value; })}
        {input(`Curve ${i + 1} Ct`, data.turbine.ct[i], (next, value) => { next.case.turbine.ct[i] = value; })}
      </div>)}</div>
      <div><h3 className="mb-3 text-sm">Wind conditions</h3><p className="mb-3 text-xs text-zinc-500">Edit direction and speed bins below; use the full configuration to add bins and adjust their probability matrix.</p>
        <div className="grid gap-3 md:grid-cols-3">{data.wind.directions_deg.map((value, i) => input(`Direction ${i + 1} [deg]`, value, (next, v) => { next.case.wind.directions_deg[i] = v; }))}
        {data.wind.speeds_m_s.map((value, i) => input(`Wind speed ${i + 1} [m/s]`, value, (next, v) => { next.case.wind.speeds_m_s[i] = v; }))}
        {input('Turbulence intensity', data.wind.turbulence_intensity, (next, value) => { next.case.wind.turbulence_intensity = value; })}</div>
      </div>
      <label className="flex gap-2 text-xs text-amber-300"><input type="checkbox" disabled={disabled} checked={Boolean(configuration.demonstration)} onChange={(e) => change((next) => { next.demonstration = e.target.checked; })} />Synthetic demonstration data</label>
    </>}
    <button className="text-xs text-indigo-300" onClick={() => setAdvanced(!advanced)}>{advanced ? 'Hide' : 'Edit'} full case configuration</button>
    {(advanced || !configuration) && <label className="block text-xs">Case configuration JSON<textarea aria-label="Simulation case configuration" spellCheck={false} disabled={disabled} className={`${field} min-h-[420px] font-mono`} value={text} onChange={(e) => onChange(e.target.value)} /></label>}
  </div>;
}
