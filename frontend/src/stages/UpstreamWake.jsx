import { Disclosure, Field, SelectField } from '../ui/controls.jsx';

const DEFAULT_DECAY = { rotor: 0.04, body: 0.06 };

// Wake of a rotor or body upstream (tandem rotors, fuselage, nacelle, tower). The parent decides
// whether the deficit is averaged over the disk or resolved around the azimuth; see `note`.
export default function UpstreamWake({ wake: current, onChange, radius, note }) {
  const wake = current || { kind: 'none' };
  const defaults = {
    rotor: { diameter_m: 2 * radius, coefficient: 0.75, distance_m: 6 * radius, offset_m: 0, offset_z_m: 0, decay: DEFAULT_DECAY.rotor },
    body: { diameter_m: radius, coefficient: 1, distance_m: 4 * radius, offset_m: 0, offset_z_m: 0, decay: DEFAULT_DECAY.body },
  };
  const set = (patch) => onChange({ ...wake, ...patch });
  const choose = (kind) => onChange(kind === 'none' ? { kind } : { model: 'gaussian', ...defaults[kind], ...(wake.kind === kind ? wake : {}), kind });
  const summary = wake.kind === 'none' ? 'None' : `${wake.kind} · ${wake.model} · ${wake.distance_m} m ahead`;
  return <Disclosure title="Upstream wake" summary={summary}>
    <SelectField label="Source" ariaLabel="Upstream wake source" value={wake.kind} onChange={choose}
      options={[['none', 'None'], ['rotor', 'Rotor ahead (tandem)'], ['body', 'Body ahead (fuselage, nacelle, tower)']]} />
    {wake.kind !== 'none' && <>
      <SelectField label="Wake model" ariaLabel="Upstream wake model" value={wake.model} onChange={(v) => set({ model: v })}
        options={[['jensen', 'Jensen (top-hat)'], ['gaussian', 'Gaussian']]} />
      <Field label={wake.kind === 'rotor' ? 'Rotor diameter' : 'Body diameter'} unit="m" value={wake.diameter_m ?? ''} onChange={(v) => set({ diameter_m: v })} />
      <Field label={wake.kind === 'rotor' ? 'Thrust coefficient Ct' : 'Drag coefficient Cd'} value={wake.coefficient ?? ''} onChange={(v) => set({ coefficient: v })} />
      <Field label="Distance upstream" unit="m" value={wake.distance_m ?? ''} onChange={(v) => set({ distance_m: v })} />
      <Field label="Lateral offset" unit="m" value={wake.offset_m ?? 0} onChange={(v) => set({ offset_m: v })} />
      <Field label="Vertical offset" unit="m" value={wake.offset_z_m ?? 0} onChange={(v) => set({ offset_z_m: v })} />
      <Field label="Wake growth k" value={wake.decay ?? ''} onChange={(v) => set({ decay: v })} />
      {note && <p className="m-0 text-xs leading-relaxed text-nv-muted">{note}</p>}
    </>}
  </Disclosure>;
}
