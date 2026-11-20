import { useEffect, useMemo, useRef, useState } from 'react';
import { formatValue, niceTicks } from '../lib/blade.js';
import { useElementWidth } from './LineChart.jsx';

// Colours by mode family; whirl and frame by dash pattern. Orange stays the primary (flap) colour.
const familyColor = { flap: '#FF8533', edge: '#4CC9F0', torsion: '#B49CFB', axial: '#9AA4B2', fa: '#7BD88F', ss: '#E8B34A' };
const whirlDash = { collective: undefined, backward: '7 4', forward: '2 3', differential: '10 3 2 3' };
const margin = { left: 44, right: 46, top: 12, bottom: 28 };

export function family(curve) {
  const direction = String(curve.direction || '');
  return direction.replace(/^(blade|tower)_/, '');
}

export function curveStyle(curve) {
  return { color: familyColor[family(curve)] || '#9AA4B2', dash: curve.whirl ? whirlDash[curve.whirl] : curve.frame === 'fixed' && curve.component === 'tower' ? '1 0' : undefined };
}

// Campbell diagram: mode frequencies and nP excitation lines against rotor speed, crossings and the
// operating speed. Hover reads every curve at that speed; clicking a curve selects it.
export function CampbellChart({ campbell, operating, selected, onSelect, height = 300 }) {
  const [box, width] = useElementWidth(520);
  const [hover, setHover] = useState(null);
  const svg = useRef(null);
  const rpm = campbell.rpm;
  const lo = rpm[0], hi = rpm[rpm.length - 1];
  const fMax = Math.max(...campbell.curves.flatMap((c) => c.frequency_hz)) * 1.08;
  const yTicks = niceTicks(0, fMax, 4).filter((t) => t <= fMax + 1e-9);
  const yHi = yTicks[yTicks.length - 1] >= fMax ? yTicks[yTicks.length - 1] : fMax;
  const xTicks = niceTicks(lo, hi, 4).filter((t) => t >= lo - 1e-9 && t <= hi + 1e-9);
  const plotW = width - margin.left - margin.right, plotH = height - margin.top - margin.bottom;
  const sx = (x) => margin.left + (x - lo) / Math.max(hi - lo, 1e-9) * plotW;
  const sy = (y) => margin.top + (1 - y / yHi) * plotH;
  const line = (ys) => ys.map((y, i) => `${sx(rpm[i])},${sy(Math.min(y, yHi))}`).join(' ');
  const at = (values, x) => {
    if (x <= lo) return values[0];
    const i = Math.min(rpm.findIndex((r) => r >= x), rpm.length - 1);
    const t = (x - rpm[i - 1]) / (rpm[i] - rpm[i - 1]);
    return values[i - 1] + t * (values[i] - values[i - 1]);
  };
  const readout = hover == null ? [] : campbell.curves.map((c) => ({ id: c.id, label: c.label, value: at(c.frequency_hz, hover), ...curveStyle(c) }))
    .sort((a, b) => b.value - a.value);
  return <figure className="m-0 min-w-0">
    <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <span className="text-[13px] text-nv-ink">Campbell diagram<span className="ml-1.5 text-nv-muted">Hz vs rpm{campbell.coupling === 'mbc' ? ' · rotor–tower coupled, fixed frame' : ''}</span></span>
      <span className="flex flex-wrap gap-3 text-xs text-nv-muted">
        {Object.entries(familyColor).filter(([f]) => campbell.curves.some((c) => family(c) === f)).map(([f, color]) =>
          <span key={f} className="inline-flex items-center gap-1.5"><svg width="14" height="4" aria-hidden="true"><line x1="0" x2="14" y1="2" y2="2" stroke={color} strokeWidth="2" /></svg>{{ fa: 'tower fore-aft', ss: 'tower side-side' }[f] || f}</span>)}
        {campbell.coupling === 'mbc' && ['collective', 'backward', 'forward'].map((w) => <span key={w} className="inline-flex items-center gap-1.5">
          <svg width="16" height="4" aria-hidden="true"><line x1="0" x2="16" y1="2" y2="2" stroke="#C7CDD6" strokeWidth="1.6" strokeDasharray={whirlDash[w]} /></svg>{w === 'collective' ? 'collective' : w === 'backward' ? 'BW' : 'FW'}</span>)}
      </span>
    </figcaption>
    <div ref={box} className="w-full">
      <svg ref={svg} width={width} height={height} role="img" className="block select-none"
        aria-label={`Campbell diagram with ${campbell.curves.length} modes and ${campbell.harmonics.length} excitation lines from ${lo} to ${hi} rpm`}
        onPointerMove={(e) => { const x = e.clientX - svg.current.getBoundingClientRect().left; setHover(x >= margin.left && x <= width - margin.right ? lo + (x - margin.left) / plotW * (hi - lo) : null); }}
        onPointerLeave={() => setHover(null)}>
        {yTicks.map((t) => <g key={t}><line x1={margin.left} x2={width - margin.right} y1={sy(t)} y2={sy(t)} stroke={t === 0 ? '#2A303A' : '#171B21'} />
          <text x={margin.left - 8} y={sy(t) + 4} textAnchor="end" className="fill-nv-muted font-mono text-[11px]">{formatValue(t, 3)}</text></g>)}
        {xTicks.map((t, i) => <text key={t} x={sx(t)} y={height - 8} textAnchor={i === xTicks.length - 1 ? 'end' : 'middle'} className="fill-nv-muted font-mono text-[11px]">{i === xTicks.length - 1 ? `${formatValue(t, 3)} rpm` : formatValue(t, 3)}</text>)}
        {Object.entries(campbell.excitation).map(([name, ys]) => {
          // label at the right edge, or where the line leaves the top of the plot
          const inside = ys[ys.length - 1] <= yHi;
          const label = inside ? { x: sx(hi) + 4, y: sy(ys[ys.length - 1]) + 4, anchor: 'start' }
            : { x: sx(Math.min(hi, yHi * 60 / Number(name.replace('P', '')))) - 3, y: margin.top + 10, anchor: 'end' };
          return <g key={name} pointerEvents="none">
            <polyline points={line(ys)} fill="none" stroke="#5A6472" strokeWidth="1.1" strokeDasharray="4 4" />
            <text x={label.x} y={label.y} textAnchor={label.anchor} className="fill-nv-muted font-mono text-[11px]">{name}</text>
          </g>;
        })}
        {operating && operating >= lo && operating <= hi && <g pointerEvents="none">
          <rect x={sx(operating * 0.9)} y={margin.top} width={Math.max(0, sx(Math.min(hi, operating * 1.1)) - sx(Math.max(lo, operating * 0.9)))} height={plotH} fill="#FF8533" opacity=".06" />
          <line x1={sx(operating)} x2={sx(operating)} y1={margin.top} y2={margin.top + plotH} stroke="#FF8533" strokeDasharray="2 4" opacity=".8" />
          <text x={sx(operating) + 4} y={margin.top + 11} className="fill-nv-accent font-mono text-[11px]">{formatValue(operating, 3)} rpm</text></g>}
        {campbell.curves.map((c) => {
          const style = curveStyle(c);
          const active = selected === c.id;
          return <g key={c.id} className="cursor-pointer" onClick={() => onSelect?.(c.id)}>
            <polyline points={line(c.frequency_hz)} fill="none" stroke="transparent" strokeWidth="10" />
            <polyline points={line(c.frequency_hz)} fill="none" stroke={style.color} strokeWidth={active ? 3 : 1.9} strokeDasharray={style.dash} opacity={selected && !active ? 0.45 : 1} strokeLinejoin="round">
              <title>{c.label}</title></polyline>
          </g>;
        })}
        {campbell.crossings.map((x, i) => x.frequency_hz <= yHi && <circle key={i} cx={sx(x.rpm)} cy={sy(x.frequency_hz)} r="3.5" fill="#0B0D10" stroke="#F27C7C" strokeWidth="1.6" pointerEvents="none">
          <title>{`${x.mode} × ${x.harmonic} at ${formatValue(x.rpm, 3)} rpm`}</title></circle>)}
        {hover != null && <line x1={sx(hover)} x2={sx(hover)} y1={margin.top} y2={margin.top + plotH} stroke="#3A424E" pointerEvents="none" />}
      </svg>
    </div>
    <div className="mt-1 min-h-[18px] text-xs text-nv-muted" aria-live="polite">
      {hover != null && <span className="flex flex-wrap gap-x-3 gap-y-0.5"><span className="font-mono text-nv-ink">{formatValue(hover, 3)} rpm</span>
        {readout.map((r) => <span key={r.id} className="inline-flex items-center gap-1"><span className="inline-block h-[3px] w-2.5" style={{ background: r.color }} />{r.label} <span className="font-mono text-nv-ink">{formatValue(r.value, 3)}</span></span>)}</span>}
    </div>
  </figure>;
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!query) return undefined;
    const update = () => setReduced(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return reduced;
}

// Side view of a mode shape: the deformed axis oscillates at a fixed visual rate (not the physical
// frequency), with the undeformed axis as reference. Every component of the shape is drawn.
export function ModeShape({ mode, x, length, component, height = 170 }) {
  const [box, width] = useElementWidth(420);
  const reduced = useReducedMotion();
  const [phase, setPhase] = useState(Math.PI / 2);
  const [playing, setPlaying] = useState(!reduced);
  useEffect(() => {
    if (!playing || reduced) return undefined;
    let frame, start;
    const tick = (time) => { start ??= time; setPhase(((time - start) / 1000) * 2 * Math.PI * 0.8); frame = requestAnimationFrame(tick); };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, reduced]);
  const components = mode.components || { [mode.direction]: mode.shape };
  const names = Object.keys(components).filter((k) => components[k].some((v) => Math.abs(v) > 0.02));
  const pad = { left: 14, right: 14, top: 10, bottom: 22 };
  const plotW = width - pad.left - pad.right, plotH = height - pad.top - pad.bottom;
  const sx = (s) => pad.left + s * plotW;
  const sy = (v) => pad.top + plotH / 2 - v * plotH * 0.42;
  const scale = Math.sin(phase);
  const labelFor = (n) => ({ fa: 'fore-aft', ss: 'side-side' }[n] || n);
  return <figure className="m-0 min-w-0">
    <figcaption className="mb-1 flex items-baseline justify-between gap-3">
      <span className="text-[13px] text-nv-ink">{mode.label}<span className="ml-1.5 font-mono text-nv-muted">{formatValue(mode.frequency_hz, 4)} Hz</span>
        {mode.damping_ratio ? <span className="ml-1.5 text-nv-muted">ζ {formatValue(mode.damping_ratio * 100, 3)} %</span> : null}</span>
      {!reduced && <button type="button" className="text-xs text-nv-reference hover:text-nv-ink" onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Animate'}</button>}
    </figcaption>
    <div ref={box} className="w-full">
      <svg width={width} height={height} role="img" className="block" aria-label={`${mode.label} shape along the ${component}: ${names.map(labelFor).join(', ')}`}>
        <line x1={sx(0)} x2={sx(1)} y1={sy(0)} y2={sy(0)} stroke="#2A303A" strokeWidth="1.5" />
        <rect x={pad.left - 6} y={sy(0) - 14} width="6" height="28" fill="#2A303A" />
        {names.map((n) => <polyline key={n} points={x.map((s, i) => `${sx(s)},${sy(components[n][i] * scale)}`).join(' ')} fill="none"
          stroke={familyColor[n] || '#9AA4B2'} strokeWidth={n === mode.direction ? 2.4 : 1.5} strokeDasharray={n === mode.direction ? undefined : '5 4'} />)}
        <text x={sx(1)} y={height - 6} textAnchor="end" className="fill-nv-muted font-mono text-[11px]">{length ? `${formatValue(length, 3)} m` : 'tip'}</text>
        <text x={sx(0)} y={height - 6} className="fill-nv-muted font-mono text-[11px]">{component === 'tower' ? 'base' : 'root'}</text>
      </svg>
    </div>
    <div className="flex flex-wrap gap-3 text-xs text-nv-muted">{names.map((n) => <span key={n} className="inline-flex items-center gap-1.5">
      <svg width="14" height="4" aria-hidden="true"><line x1="0" x2="14" y1="2" y2="2" stroke={familyColor[n] || '#9AA4B2'} strokeWidth="2" strokeDasharray={n === mode.direction ? undefined : '4 3'} /></svg>{labelFor(n)}</span>)}</div>
  </figure>;
}

export function Participation({ shares }) {
  const entries = Object.entries(shares || {}).filter(([, v]) => v > 0.005).sort((a, b) => b[1] - a[1]);
  return <div className="flex flex-col gap-1">{entries.map(([k, v]) => <div key={k} className="grid grid-cols-[120px_minmax(0,1fr)_48px] items-center gap-2 text-xs">
    <span className="text-nv-muted">{k.replace('_', ' ')}</span>
    <span className="h-1.5 rounded bg-nv-chrome"><span className="block h-1.5 rounded" style={{ width: `${v * 100}%`, background: familyColor[k.replace(/^(blade|tower)_/, '')] || '#9AA4B2' }} /></span>
    <span className="text-right font-mono text-nv-ink">{formatValue(v * 100, 3)} %</span></div>)}</div>;
}

// Everything a modal output carries: Campbell chart with a selectable curve, or the list of modes,
// and the selected mode's shape (or participation for coupled modes, which have no single shape).
export function ModalView({ modal }) {
  const campbell = modal.campbell;
  const modes = useMemo(() => campbell ? campbell.curves : modal.modes || [], [campbell, modal.modes]);
  const [selected, setSelected] = useState(modes[0]?.id);
  const [speed, setSpeed] = useState(() => campbell && modal.operating_rpm ? modal.operating_rpm : null);
  const current = modes.find((m) => m.id === selected) || modes[0];
  if (!current) return null;
  let shape = null, participation = null;
  if (campbell) {
    const index = speed == null ? campbell.rpm.length - 1 : campbell.rpm.reduce((best, r, i) => Math.abs(r - speed) < Math.abs(campbell.rpm[best] - speed) ? i : best, 0);
    const shapes = current.shapes || [];
    const pick = shapes.length > 1 ? shapes[index] : shapes[0];
    if (pick) shape = { ...pick, label: current.label, direction: current.direction, frequency_hz: current.frequency_hz[index], damping_ratio: current.damping_ratio?.[index] };
    else participation = { label: current.label, shares: current.participation?.[index], frequency: current.frequency_hz[index], rpm: campbell.rpm[index] };
  } else {
    shape = current;
  }
  const component = current.component === 'tower' ? 'tower' : 'blade';
  const length = component === 'tower' ? modal.tower_height_m ?? modal.length_m : modal.blade_length_m ?? modal.length_m;
  return <div className="flex flex-col gap-3">
    {campbell && <CampbellChart campbell={campbell} operating={modal.operating_rpm} selected={current.id} onSelect={setSelected} />}
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2 text-xs text-nv-muted">Mode
        <select aria-label="Mode" className="h-[28px] rounded-md border border-nv-edge bg-nv-chrome px-2 text-[12.5px] text-nv-ink" value={current.id} onChange={(e) => setSelected(e.target.value)}>
          {modes.map((m) => <option key={m.id} value={m.id}>{m.label}{campbell ? '' : ` · ${formatValue(m.frequency_hz, 4)} Hz`}</option>)}</select></label>
      {campbell && <label className="flex items-center gap-2 text-xs text-nv-muted">at
        <input aria-label="Rotor speed for the mode shape" type="range" min={campbell.rpm[0]} max={campbell.rpm.at(-1)} step={(campbell.rpm.at(-1) - campbell.rpm[0]) / Math.max(campbell.rpm.length - 1, 1)}
          value={speed ?? campbell.rpm.at(-1)} onChange={(e) => setSpeed(Number(e.target.value))} className="accent-[#FF8533]" />
        <span className="font-mono text-nv-ink">{formatValue(speed ?? campbell.rpm.at(-1), 3)} rpm</span></label>}
    </div>
    {shape && <ModeShape mode={shape} x={modal.x} length={length} component={component} />}
    {participation && <div className="flex flex-col gap-2"><span className="text-[13px] text-nv-ink">{participation.label}
      <span className="ml-1.5 font-mono text-nv-muted">{formatValue(participation.frequency, 4)} Hz at {formatValue(participation.rpm, 3)} rpm</span></span>
      <span className="text-xs text-nv-muted">Coupled mode: share of each component in the mode (multi-blade coordinates)</span>
      <Participation shares={participation.shares} /></div>}
  </div>;
}

// OpenFAST linearisation compared with Nova's coupled Campbell diagram, mode by mode.
export function LinearizationComparison({ table }) {
  if (!table.comparison?.length) return null;
  return <div className="flex flex-col gap-1.5">
    <span className="text-xs text-nv-muted">OpenFAST vs Nova at {formatValue(table.rpm, 3)} rpm</span>
    <table className="w-full text-left text-xs tabular-nums"><thead className="text-nv-muted"><tr>
      <th className="p-1 font-normal">OpenFAST mode</th><th className="p-1 font-normal">Nova mode</th><th className="p-1 text-right font-normal">OpenFAST Hz</th>
      <th className="p-1 text-right font-normal">Nova Hz</th><th className="p-1 text-right font-normal">Δ %</th></tr></thead>
      <tbody>{table.comparison.map((p) => <tr key={p.openfast_mode} className="border-t border-nv-line">
        <td className="p-1">{p.openfast_mode}</td><td className="p-1">{p.nova_mode}</td>
        <td className="p-1 text-right font-mono">{formatValue(p.openfast_hz, 4)}</td><td className="p-1 text-right font-mono">{formatValue(p.nova_hz, 4)}</td>
        <td className={`p-1 text-right font-mono ${Math.abs(p.difference_pct) > 5 ? 'text-nv-warn-ink' : 'text-nv-ink'}`}>{formatValue(p.difference_pct, 3)}</td></tr>)}</tbody></table>
  </div>;
}
