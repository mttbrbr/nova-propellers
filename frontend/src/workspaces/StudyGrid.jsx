import { useState } from 'react';

const field = 'rounded border border-zinc-700 bg-zinc-950 p-2 text-xs';
const metrics = { thrust_n: ['Thrust', 'N'], torque_nm: ['Torque', 'N·m'], power_w: ['Power', 'W'], figure_of_merit: ['Figure of merit', 'dimensionless'] };
const number = (value) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumSignificantDigits: 6 });

export default function StudyGrid({ run, rows, primary, secondary, onInspect }) {
  const nodes = (run.workflow?.nodes || []).filter((n) => n.type === 'analysis');
  const [selection, setSelection] = useState('');
  const [metric, setMetric] = useState('thrust_n');
  const selected = nodes.some((n) => n.id === selection) ? selection : nodes[0]?.id;
  const available = rows.filter((row) => row.node_id === selected && row.state === 'succeeded' && Number.isFinite(row[metric]));
  const values = available.map((row) => row[metric]);
  const low = values.length ? Math.min(...values) : 0, high = values.length ? Math.max(...values) : 0;
  return <section aria-label="Two-axis study grid" className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm">Two-axis results</h3><div className="flex flex-wrap gap-2">
      <label className="text-xs text-zinc-400">Analysis node<select aria-label="Grid analysis node" className={`${field} ml-2`} value={selected || ''} onChange={(e) => setSelection(e.target.value)}>{nodes.map((n) => <option key={n.id} value={n.id}>{n.id} · {n.config.model}</option>)}</select></label>
      <label className="text-xs text-zinc-400">Quantity<select aria-label="Grid result quantity" className={`${field} ml-2`} value={metric} onChange={(e) => setMetric(e.target.value)}>{Object.entries(metrics).map(([id, [label, units]]) => <option key={id} value={id}>{label} [{units}]</option>)}</select></label>
    </div></div>
    <p className="text-xs text-zinc-400">Rows: {primary.parameter} [{primary.units}]. Columns: {secondary.parameter} [{secondary.units}]. {metrics[metric][0]} [{metrics[metric][1]}]{values.length ? `: ${number(low)}–${number(high)}` : ': no completed values'}. Select a completed cell to inspect its exact frozen inputs.</p>
    <div className="overflow-auto"><table aria-label="Two-axis performance grid" className="w-full text-left text-xs"><caption className="sr-only">{primary.parameter} [{primary.units}] by {secondary.parameter} [{secondary.units}]</caption>
      <thead className="text-zinc-400"><tr><th className="p-3 font-normal">{primary.parameter} [{primary.units}] ↓ / {secondary.parameter} [{secondary.units}] →</th>{secondary.values.map((value) => <th key={value} scope="col" className="p-3 font-normal">{number(value)} [{secondary.units}]</th>)}</tr></thead>
      <tbody>{primary.values.map((x) => <tr key={x} className="border-t border-zinc-800"><th scope="row" className="p-3 font-normal text-zinc-400">{number(x)} [{primary.units}]</th>{secondary.values.map((y) => {
        const sample = (run.result?.cases || []).find((c) => c.value === x && c.secondary_value === y);
        const row = sample?.state === 'succeeded' ? available.find((r) => r.value === x && r.secondary_value === y) : null;
        const state = sample?.state || (['queued', 'running', 'cancelling'].includes(run.state) ? 'Pending' : `Not run (${run.state})`);
        const intensity = row ? high === low ? .18 : .08 + .3 * (row[metric] - low) / (high - low) : 0;
        return <td key={y} data-state={sample?.state || 'pending'} className="min-w-32 border-l border-zinc-800 p-3" style={{ backgroundColor: `rgba(99, 102, 241, ${intensity})` }}>
          {row ? <button className="w-full rounded p-2 text-left tabular-nums hover:bg-white/5 focus-visible:outline focus-visible:outline-indigo-400" aria-label={`Inspect grid case ${sample.index + 1}`} onClick={() => onInspect(row)}>{number(row[metric])}<span className="mt-1 block text-[10px] text-zinc-400">{metrics[metric][1]} · {row.model} · {row.fidelity}</span></button> : <div className="p-2 text-zinc-500"><span>—</span><span className="mt-1 block text-[10px]">{state}</span>{sample?.error && <span className="mt-1 block max-w-xs text-[10px] text-red-400">{sample.error}</span>}</div>}
        </td>;
      })}</tr>)}</tbody>
    </table></div>
    <p className="text-[10px] text-zinc-500">Each cell is one evaluated case. Shading shows the selected quantity across completed cells; failed and unexecuted cases have no assigned value. No interpolation is applied between cases.</p>
  </section>;
}
