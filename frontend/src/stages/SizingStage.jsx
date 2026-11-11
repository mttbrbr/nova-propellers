import { ArrowRight } from 'lucide-react';
import { formatValue, niceTicks } from '../lib/blade.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import { Button, Field, LabeledSegmented, Metric, Section } from '../ui/controls.jsx';
import { FamilySelector } from './RotorStages.jsx';
import LineChart from '../ui/LineChart.jsx';

const AIR_DENSITY = 1.225;

// Ideal actuator-disk relations; the backend applies the same theory when the
// estimate is applied, so the chart is a faithful preview of that call.
export function idealDisk(thrust, loading, density = AIR_DENSITY) {
  const area = thrust / loading;
  const diameter = Math.sqrt(4 * area / Math.PI);
  const induced = Math.sqrt(thrust / (2 * density * area));
  return { area, diameter, induced, power: thrust * induced };
}

function DiskPreview({ diameter, induced }) {
  return <div className="relative aspect-square w-full overflow-hidden rounded-xl border border-nv-line bg-[#0A0C0F]">
    <svg viewBox="0 0 600 600" className="absolute inset-0 h-full w-full" role="img" aria-label={`Ideal actuator disk of ${formatValue(diameter)} metres with its contracting slipstream`}>
      <defs><linearGradient id="disk-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FF8533" stopOpacity=".35" /><stop offset="1" stopColor="#FF8533" stopOpacity=".08" /></linearGradient></defs>
      <g fill="none" stroke="#2A303A" strokeWidth="1.2"><path d="M 140 200 C 150 320, 200 420, 214 560" /><path d="M 460 200 C 450 320, 400 420, 386 560" /></g>
      <g fill="none" stroke="#3A424E" strokeDasharray="4 6"><path d="M 220 210 C 228 320, 250 420, 258 560" /><path d="M 300 210 L 300 560" /><path d="M 380 210 C 372 320, 350 420, 342 560" /></g>
      <ellipse cx="300" cy="200" rx="160" ry="44" fill="url(#disk-fill)" stroke="#FF8533" strokeWidth="2" />
      <g stroke="#C4CAD2" strokeWidth="1.2"><line x1="140" y1="120" x2="460" y2="120" /><line x1="140" y1="112" x2="140" y2="128" /><line x1="460" y1="112" x2="460" y2="128" /></g>
      <text x="300" y="106" textAnchor="middle" className="fill-nv-ink-strong font-mono text-[14px]">Ø {formatValue(diameter)} m</text>
      <g stroke="#FF8533" strokeWidth="2" fill="none"><line x1="300" y1="300" x2="300" y2="400" /><path d="M 292 390 L 300 404 L 308 390" /></g>
      <text x="314" y="360" className="fill-nv-accent font-mono text-[13px]">vᵢ {formatValue(induced)} m/s</text>
      <text x="300" y="588" textAnchor="middle" className="fill-nv-muted text-[12px]">Ideal slipstream contracts to half the disk area</text>
    </svg>
  </div>;
}

export default function SizingStage({ inputs, set, sizing, onEstimate, onContinue, busy, family = 'propeller', onFamily }) {
  const fromLoading = inputs.diameter_mode === 'actuator_disk';
  const thrust = Math.max(Number(inputs.thrust_target) || 0, 1e-6);
  const loading = fromLoading ? Math.max(Number(inputs.disk_loading) || 0, 1e-6) : thrust / (Math.PI * (Number(inputs.diameter) || 1e-6) ** 2 / 4);
  const current = idealDisk(thrust, loading);
  const ticks = niceTicks(Math.max(10, loading * 0.4), loading * 2.2, 3).filter((tick) => tick > 0);
  const low = ticks[0], high = ticks[ticks.length - 1];
  const span = Array.from({ length: 48 }, (_, index) => low + (high - low) * index / 47);
  const choose = (value) => { set('diameter_mode', 'actuator_disk'); set('disk_loading', Math.round(value)); };
  return <StageLayout inputsLabel="Stage inputs" contentLabel="Sizing trade-off" sideLabel="Actuator disk preview"
    inputs={<>
      <StageTitle title="Sizing" detail="Set the target and get a first diameter." />
      <Section title="Project">
        <Field label="Name" ariaLabel="Project name" text value={inputs.project_name} onChange={(v) => set('project_name', v)} />
        {onFamily && <FamilySelector value={family} onChange={onFamily} />}
        <LabeledSegmented label="Blade layout" value={inputs.propeller_type} onChange={(v) => set('propeller_type', v)}
          options={[['traditional', 'Traditional'], ['toroidal', 'Toroidal', true, 'Toroidal propellers are not supported in this alpha']]} />
      </Section>
      <Section title="Target">
        <Field label="Thrust" ariaLabel="Target thrust" unit="N" value={inputs.thrust_target} onChange={(v) => set('thrust_target', v)} />
      </Section>
      <Section title="Diameter">
        <LabeledSegmented label="Mode" value={inputs.diameter_mode} onChange={(v) => set('diameter_mode', v)} options={[['manual', 'Manual'], ['actuator_disk', 'From loading']]} />
        {fromLoading
          ? <><Field label="Disk loading" unit="N/m²" value={inputs.disk_loading} onChange={(v) => set('disk_loading', v)} />
            <Button disabled={busy} onClick={onEstimate}>Use Ø {formatValue(current.diameter)} m</Button></>
          : <Field label="Diameter" unit="m" value={inputs.diameter} onChange={(v) => set('diameter', v)} />}
        {sizing && <p className="m-0 font-mono text-xs text-nv-muted">Applied: Ø {sizing.diameter_m} m · vᵢ {sizing.induced_velocity_m_s} m/s · P {sizing.ideal_power_w} W</p>}
        <p className="m-0 text-xs leading-relaxed text-nv-muted">Ideal actuator disk: a reference, not a prediction. Real propellers need more power.</p>
      </Section>
      <div className="flex-1" />
      <Button onClick={onContinue}>Continue to Geometry<ArrowRight size={16} aria-hidden="true" /></Button>
    </>}
    content={<>
      <section aria-labelledby="sizing-trade">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="sizing-trade" className="m-0 text-[15px] font-semibold">Trade-off for {formatValue(thrust)} N <span className="font-normal text-nv-muted">· sea-level air, {AIR_DENSITY} kg/m³</span></h2>
          <span className="text-[12.5px] text-nv-muted">Click a chart to choose a disk loading</span>
        </div>
        <div className="grid gap-8 lg:grid-cols-2">
          <LineChart title="Diameter" unit="m" xDomain={[low, high]} xTicks={ticks} xLabel="N/m²" selection={loading} onSelect={choose}
            series={[{ id: 'diameter', color: '#FF8533', points: span.map((x) => ({ x, y: idealDisk(thrust, x).diameter })) }]} />
          <LineChart title="Ideal power" unit="W" xDomain={[low, high]} xTicks={ticks} xLabel="N/m²" selection={loading} onSelect={choose}
            series={[{ id: 'power', color: '#4CC9F0', points: span.map((x) => ({ x, y: idealDisk(thrust, x).power })) }]} />
        </div>
      </section>
      <section aria-labelledby="sizing-method" className="grid gap-x-10 gap-y-4 sm:grid-cols-3">
        <h2 id="sizing-method" className="m-0 text-[15px] font-semibold sm:col-span-3">How the estimate is made</h2>
        {[['A = T / DL', 'Disk area from thrust and disk loading.'], ['vᵢ = √(T / 2ρA)', 'Induced velocity through the disk.'], ['P = T · vᵢ', 'Ideal power, a lower bound for the real one.']].map(([formula, text]) =>
          <div key={formula} className="flex flex-col gap-1.5"><span className="font-mono text-[15px]">{formula}</span><span className="text-[13px] leading-relaxed text-nv-muted">{text}</span></div>)}
      </section>
      <section aria-labelledby="sizing-presets">
        <h2 id="sizing-presets" className="m-0 mb-3.5 text-[15px] font-semibold">Starting points</h2>
        <div className="grid gap-3 sm:grid-cols-3">{[['Low loading', 150], ['Moderate', 220], ['Compact', 300]].map(([name, value]) => {
          const option = idealDisk(thrust, value);
          const active = fromLoading && Math.round(loading) === value;
          return <button key={name} type="button" onClick={() => choose(value)} aria-pressed={active}
            className={`rounded-lg border px-4 py-3.5 text-left transition hover:bg-nv-hover ${active ? 'border-nv-accent' : 'border-nv-edge'}`}>
            <span className="block text-[13px]">{name}</span><span className="mt-1 block font-mono text-[12.5px] text-nv-muted">{value} N/m² · Ø {formatValue(option.diameter)} m</span>
          </button>;
        })}</div>
      </section>
    </>}
    side={<>
      <DiskPreview diameter={current.diameter} induced={current.induced} />
      <dl className="m-0 grid grid-cols-3 gap-x-6 gap-y-5">
        <Metric size="md" label="Diameter" value={formatValue(current.diameter)} unit="m" />
        <Metric size="md" label="Induced velocity" value={formatValue(current.induced)} unit="m/s" />
        <Metric size="md" label="Ideal power" value={formatValue(current.power)} unit="W" />
        <Metric size="md" label="Disk area" value={formatValue(current.area)} unit="m²" />
        <Metric size="md" label="Disk loading" value={formatValue(loading)} unit="N/m²" />
        <Metric size="md" label="Thrust" value={formatValue(thrust)} unit="N" />
      </dl>
    </>} />;
}
