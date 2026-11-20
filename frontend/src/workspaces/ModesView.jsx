import { useEffect, useMemo, useState } from 'react';
import { Pause, Play, X } from 'lucide-react';
import { formatValue } from '../lib/blade.js';
import { CampbellChart, ModeShape, Participation, curveStyle } from '../ui/ModalCharts.jsx';
import ModeViewport, { views } from '../ui/ModeViewport.jsx';

// Full-screen view of the modes of one block result: mode list (left), Campbell diagram or mode shape
// (centre), square animated 3-D turbine (right). Opened over the Workflow canvas.

export const modalOf = (blockResult) => blockResult?.status === 'succeeded'
  ? Object.values(blockResult.outputs || {}).find((v) => v && v.kind === 'modal') : null;

const real = (values) => values ? [values, null] : null;

function nearest(list, value) {
  return list.reduce((best, item, i) => Math.abs(item - value) < Math.abs(list[best] - value) ? i : best, 0);
}

// Every mode of a modal output as { id, label, frequency(i), damping(i), participation(i), shape(i) } over speed index i.
function entries(modal) {
  const campbell = modal.campbell;
  if (campbell) {
    return campbell.curves.map((c) => ({
      id: c.id, label: c.label, style: curveStyle(c), coupled: c.component === 'coupled',
      frequency: (i) => c.frequency_hz[i], damping: (i) => c.damping_ratio?.[i],
      participation: (i) => c.participation?.[i],
      shape: (i) => {
        if (c.component === 'coupled') {
          const k = nearest(c.shape_index || [0], i);
          const s = c.shapes?.[k];
          return s && { x: modal.shape_x, tower: s.tower, blades: s.blades, rpm: campbell.rpm[c.shape_index[k]] };
        }
        const s = c.shapes?.length > 1 ? c.shapes[i] : c.shapes?.[0];
        if (!s) return null;
        const parts = s.components || {};
        return c.component === 'tower'
          ? { x: modal.x, tower: { fa: real(parts.fa), ss: real(parts.ss) } }
          : { x: modal.x, blades: [{ flap: real(parts.flap), edge: real(parts.edge) }], single: true };
      },
      raw: (i) => {
        const s = c.shapes?.length > 1 ? c.shapes[i] : c.shapes?.[0];
        return s && { ...s, label: c.label, direction: c.direction, frequency_hz: c.frequency_hz[i], damping_ratio: c.damping_ratio?.[i] };
      },
    }));
  }
  return (modal.modes || []).map((m) => ({
    id: m.id, label: m.label, style: curveStyle(m), coupled: false,
    frequency: () => m.frequency_hz, damping: () => m.damping_ratio, participation: () => m.participation,
    shape: () => modal.component === 'tower'
      ? { x: modal.x, tower: { fa: real(m.components?.fa), ss: real(m.components?.ss) } }
      : { x: modal.x, blades: [{ flap: real(m.components?.flap), edge: real(m.components?.edge) }], single: true },
    raw: () => m,
  }));
}

export default function ModesView({ result, blockId, onBlock, onClose }) {
  const blocks = useMemo(() => (result?.order || []).filter((id) => modalOf(result.blocks[id])), [result]);
  const modal = modalOf(result?.blocks?.[blockId]);
  const list = useMemo(() => modal ? entries(modal) : [], [modal]);
  const campbell = modal?.campbell;
  const [selected, setSelected] = useState(null);
  const [speed, setSpeed] = useState(() => campbell ? nearest(campbell.rpm, modal.operating_rpm ?? campbell.rpm.at(-1)) : 0);
  const [playing, setPlaying] = useState(true);
  const [amplitude, setAmplitude] = useState(0.5);
  const [view, setView] = useState('iso');
  useEffect(() => {
    setSelected(null);
    setSpeed(campbell ? nearest(campbell.rpm, modal.operating_rpm ?? campbell.rpm.at(-1)) : 0);
  }, [blockId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [onClose]);
  if (!modal) return null;
  const current = list.find((m) => m.id === selected) || list[0];
  const rpm = campbell ? campbell.rpm[speed] : null;
  const shape = current?.shape(speed);
  const layout = modal.layout || { blade_length_m: modal.length_m, tower_height_m: modal.component === 'tower' ? modal.length_m : undefined, blades: 3 };
  const damping = current?.damping(speed);
  return <section role="dialog" aria-label="Mode view" className="absolute inset-0 z-40 flex flex-col bg-nv-canvas">
    <header className="flex flex-wrap items-center gap-3 border-b border-nv-line px-4 py-2.5">
      <h2 className="m-0 text-[15px] font-semibold text-nv-ink">Mode view</h2>
      <div role="group" aria-label="Block" className="flex flex-wrap gap-1.5">
        {blocks.map((id) => <button key={id} type="button" aria-pressed={id === blockId} onClick={() => onBlock(id)}
          className={`h-8 rounded-md border px-3 text-[12.5px] ${id === blockId ? 'border-nv-accent bg-nv-accent/15 text-nv-ink' : 'border-nv-edge bg-nv-chrome text-nv-reference hover:bg-nv-hover'}`}>{id}</button>)}
      </div>
      <button type="button" onClick={onClose} className="ml-auto flex h-8 items-center gap-1.5 rounded-md border border-nv-edge bg-nv-chrome px-3 text-[12.5px] text-nv-ink hover:bg-nv-hover">
        <X size={14} aria-hidden="true" />Back to canvas</button>
    </header>
    <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)_auto]">
      <aside aria-label="Modes" className="flex min-h-0 flex-col gap-3 overflow-y-auto border-r border-nv-line p-4">
        <span className="text-[11.5px] uppercase tracking-wider text-nv-muted">Modes{rpm != null ? ` · ${formatValue(rpm, 3)} rpm` : ''}</span>
        <div className="flex flex-col gap-1">{list.map((m) => {
          const active = m.id === current?.id;
          return <button key={m.id} type="button" aria-pressed={active} onClick={() => setSelected(m.id)}
            className={`grid grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-2 rounded-md border px-2.5 py-2 text-left text-[12.5px] ${active ? 'border-nv-accent/50 bg-nv-raised text-nv-ink' : 'border-transparent text-nv-reference hover:bg-nv-hover'}`}>
            <svg width="16" height="4" aria-hidden="true"><line x1="0" x2="16" y1="2" y2="2" stroke={m.style.color} strokeWidth="2.4" strokeDasharray={m.style.dash} /></svg>
            <span className="truncate">{m.label}</span><span className="font-mono text-[12px]">{formatValue(m.frequency(speed), 4)} Hz</span></button>;
        })}</div>
        {current?.participation(speed) && <div className="flex flex-col gap-2 border-t border-nv-line pt-3">
          <span className="text-[11.5px] uppercase tracking-wider text-nv-muted">Participation</span>
          <Participation shares={current.participation(speed)} /></div>}
      </aside>
      <main className="flex min-w-0 flex-col gap-3 overflow-y-auto p-5">
        {campbell ? <CampbellChart campbell={campbell} operating={modal.operating_rpm} selected={current?.id} onSelect={setSelected} height={560} />
          : current && <>
            <ModeShape mode={current.raw(0)} x={modal.x} length={modal.length_m} component={modal.component === 'tower' ? 'tower' : 'blade'} height={320} />
            <table aria-label="All modes" className="mt-2 w-full text-left text-[12.5px] tabular-nums">
              <thead className="text-nv-muted"><tr><th className="p-2 font-normal">Mode</th><th className="p-2 text-right font-normal">Frequency</th>
                <th className="p-2 text-right font-normal">Damping</th><th className="p-2 text-right font-normal">Nodes</th><th className="p-2 font-normal">Main participation</th></tr></thead>
              <tbody>{list.map((m) => {
                const raw = m.raw(0);
                const shares = Object.entries(raw.participation || {}).sort((a, b) => b[1] - a[1]);
                return <tr key={m.id} className={`border-t border-nv-line ${m.id === current.id ? 'text-nv-ink' : 'text-nv-reference'}`}>
                  <td className="p-2">{m.label}</td><td className="p-2 text-right font-mono">{formatValue(raw.frequency_hz, 4)} Hz</td>
                  <td className="p-2 text-right font-mono">{raw.damping_ratio ? `${formatValue(raw.damping_ratio * 100, 3)} %` : '—'}</td>
                  <td className="p-2 text-right font-mono">{raw.nodes ?? '—'}</td>
                  <td className="p-2">{shares.slice(0, 2).map(([k, v]) => `${k} ${Math.round(v * 100)} %`).join(' · ')}</td></tr>;
              })}</tbody></table></>}
        <p className="m-0 text-xs text-nv-muted">Select a mode in the list or on the chart; the 3-D view on the right animates it.</p>
      </main>
      <section aria-label="3-D mode shape" className="flex min-h-0 flex-col gap-3 border-l border-nv-line p-4" style={{ width: 'min(44vw, calc(100vh - 150px))' }}>
        <div className="flex items-baseline justify-between gap-3">
          <span className="truncate text-[14px] text-nv-ink">{current?.label}</span>
          <span className="font-mono text-[12.5px] text-nv-muted">{current ? `${formatValue(current.frequency(speed), 4)} Hz` : ''}{damping ? ` · ζ ${formatValue(damping * 100, 3)} %` : ''}</span>
        </div>
        <div className="relative aspect-square w-full overflow-hidden rounded-xl border border-nv-line">
          <ModeViewport layout={layout} mode={shape} amplitude={amplitude} playing={playing} view={view} label={`${current?.label || 'Mode'} animated in 3-D`} />
          <div role="group" aria-label="View" className="absolute right-2.5 top-2.5 flex flex-col gap-1.5">
            {Object.entries(views).map(([id, v]) => <button key={id} type="button" aria-pressed={view === id} onClick={() => setView(id)}
              className={`h-8 min-w-[44px] rounded-md border px-2 text-[11.5px] ${view === id ? 'border-nv-accent bg-nv-accent/15 text-nv-ink' : 'border-nv-edge bg-nv-chrome/90 text-nv-reference hover:bg-nv-hover'}`}>{v.label}</button>)}
          </div>
        </div>
        <div className="grid grid-cols-[44px_minmax(0,1fr)] items-center gap-3">
          <button type="button" aria-label={playing ? 'Pause animation' : 'Play animation'} onClick={() => setPlaying(!playing)}
            className="grid h-11 w-11 place-items-center rounded-lg bg-nv-accent text-nv-accent-ink hover:bg-nv-accent-soft">{playing ? <Pause size={18} /> : <Play size={18} />}</button>
          <div className="flex flex-col gap-1.5">
            <label className="grid grid-cols-[86px_minmax(0,1fr)_64px] items-center gap-2 text-xs text-nv-muted">amplitude
              <input type="range" min="0.05" max="1" step="0.05" value={amplitude} onChange={(e) => setAmplitude(Number(e.target.value))} className="accent-[#FF8533]" />
              <span className="font-mono text-nv-ink">×{Math.round(amplitude * 100)}</span></label>
            {campbell && <label className="grid grid-cols-[86px_minmax(0,1fr)_64px] items-center gap-2 text-xs text-nv-muted">rotor speed
              <input type="range" min="0" max={campbell.rpm.length - 1} step="1" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="accent-[#FF8533]" />
              <span className="font-mono text-nv-ink">{formatValue(rpm, 3)} rpm</span></label>}
          </div>
        </div>
        <p className="m-0 text-xs leading-relaxed text-nv-muted">
          {shape?.single ? 'Single-blade mode drawn on every blade. ' : ''}
          {current?.coupled ? `Shape at ${formatValue(shape?.rpm, 3)} rpm, rotor frozen with blade 1 up; whirl modes show the phase lag between blades. ` : ''}
          Colour and amplitude are a visual scale; the grey line is the undeformed structure.</p>
      </section>
    </div>
  </section>;
}
