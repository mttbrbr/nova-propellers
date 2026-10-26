import { useState } from 'react';

const leaf = 'block w-full rounded px-2 py-2 text-left text-xs hover:bg-nv-hover disabled:opacity-40';
const models = (workflow) => [...new Set((workflow?.nodes || []).filter((n) => n.type === 'analysis').map((n) => (n.config?.model || 'bemt').toUpperCase()))].join(' + ');

export default function ProjectExplorer({ project, simulations, geometries, assets, runs, simulationId, geometryId, selectedPolar, locked, onSimulation, onGeometry, onRun, onUsePolar, onStudies }) {
  const [query, setQuery] = useState('');
  const [asset, setAsset] = useState(null);
  const [allRuns, setAllRuns] = useState(false);
  const matches = (text) => text.toLowerCase().includes(query.toLowerCase().trim());
  const families = [...new Set(geometries.map((g) => g.geometry_id))];
  const filteredRuns = runs.filter((r) => matches(`${r.name} ${r.simulation_name || ''} ${r.state} ${r.id} ${models(r.workflow)}`));
  const downloadSource = () => {
    const url = URL.createObjectURL(new Blob([asset.source], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = (asset.filename || `${asset.airfoil || 'asset'}.txt`).split(/[\\/]/).at(-1); link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <details open className="border-t border-nv-line pt-5" aria-label="Project explorer">
    <summary className="cursor-pointer pb-3 text-[15px] font-semibold">Project explorer</summary>
    {!project ? <p className="pb-3 text-[13px] text-nv-muted">Save the draft to create a project. Its geometry, data, simulations and executions will appear here.</p> : <div className="space-y-1 pb-3">
      <p className="truncate px-1 pb-2 text-xs text-nv-reference" title={project.name}>{project.name}</p>
      <input aria-label="Search project explorer" placeholder="Find simulation, geometry, data or run…" className="mb-2 w-full rounded border border-nv-edge bg-nv-chrome p-2 text-xs" value={query} onChange={(e) => setQuery(e.target.value)} />
      <details open><summary className="cursor-pointer p-2 text-xs text-nv-muted">Simulations · {simulations.length}</summary>
        {simulations.filter((s) => matches(`${s.name} ${s.kind || 'propeller'} ${models(s.workflow)}`)).map((s) => <button key={s.id} type="button" disabled={locked} aria-label={`Open simulation ${s.name}`} aria-current={s.id === simulationId ? 'true' : undefined} className={`${leaf} ${s.id === simulationId ? 'bg-nv-active text-nv-ink-strong' : 'text-nv-muted'}`} onClick={() => onSimulation(s)}>
          <span className="block">{s.name} · r{s.revision}</span><span className="text-[11px] text-nv-muted">{s.kind && s.kind !== 'propeller' ? s.kind.toUpperCase() : `${models(s.workflow) || 'Geometry only'} · ${s.inputs?.rpm || '—'} rpm · geometry r${s.geometry_revision || '—'}`}</span>
        </button>)}
        {!simulations.length && <p className="p-2 text-xs text-nv-muted">No saved simulations yet.</p>}
        {simulations.filter((s) => !s.kind || s.kind === 'propeller').length > 1 && <button type="button" className={`${leaf} text-nv-accent`} onClick={onStudies}>Compare simulation solvers →</button>}
      </details>
      <details><summary className="cursor-pointer p-2 text-xs text-nv-muted">Geometry · {families.length} definitions / {geometries.length} revisions</summary>
        {geometries.filter((g) => matches(`${g.name} r${g.geometry_revision}`)).map((g) => <button type="button" key={g.id} className={`${leaf} ${g.id === geometryId ? 'bg-nv-active text-nv-ink-strong' : 'text-nv-muted'}`} disabled={locked} aria-label={`Use geometry ${g.name} revision ${g.geometry_revision}`} aria-current={g.id === geometryId ? 'true' : undefined} onClick={() => onGeometry(g.id)}>{g.name} · r{g.geometry_revision}<span className="block text-[11px] text-nv-muted">{g.definition.blades} blades · {g.definition.diameter} m</span></button>)}
      </details>
      <details><summary className="cursor-pointer p-2 text-xs text-nv-muted">Referenced data · {assets.length}</summary>
        {assets.filter((a) => matches(`${a.name || a.filename || a.airfoil || ''} ${a.kind}`)).map((a) => <button type="button" className={`${leaf} text-nv-muted`} key={a.id} onClick={() => setAsset(a)} aria-label={`Inspect data ${a.name || a.filename || a.airfoil}`}>{a.name || a.filename || a.airfoil}<span className="block text-[11px] text-nv-muted">{a.type === 'simulation_case' ? `${a.kind.toUpperCase()} case` : a.kind === 'polar_family' ? 'Airfoil polars' : 'Airfoil geometry'}{a.id === selectedPolar ? ' · selected polars' : ''}{a.demonstration ? ' · synthetic demonstration' : ''}</span></button>)}
        {!assets.length && <p className="p-2 text-xs text-nv-muted">No referenced data. Import polars in Force analysis.</p>}
      </details>
      <details open><summary className="cursor-pointer p-2 text-xs text-nv-muted">Executions in this project · {runs.length}</summary>
        {(allRuns || query ? filteredRuns : filteredRuns.slice(0, 10)).map((r) => <button key={r.id} type="button" aria-label={`View execution ${r.id}`} className={`${leaf} text-nv-muted`} onClick={() => onRun(r)}>
          <span className="block">{r.comparison ? r.name : r.simulation_name || 'Unassigned analysis'}{r.simulation_revision ? ` · r${r.simulation_revision}` : ''}</span>
          <span className="block text-[11px] text-nv-muted">{r.comparison ? 'Solver comparison' : r.study ? `Sweep ${r.study.parameter}${r.study.secondary ? ` × ${r.study.secondary.parameter}` : ''}` : r.optimization ? 'Optimization' : r.external_job?.adapter_id?.toUpperCase() || models(r.workflow)} · {r.state}</span>
          <span className="block text-[11px] text-nv-muted">{r.created_at} · {r.id.slice(0, 8)}</span>
        </button>)}
        {!runs.length && <p className="p-2 text-xs text-nv-muted">No executions yet.</p>}
        {filteredRuns.length > 10 && !query && <button className={`${leaf} text-nv-accent`} onClick={() => setAllRuns(!allRuns)}>{allRuns ? 'Show latest 10' : `Show all ${filteredRuns.length} executions`}</button>}
      </details>
      {asset && <div className="space-y-2 rounded border border-nv-edge p-3 text-xs" aria-label="Data asset inspector">
        <div className="flex justify-between gap-2"><span className="break-all">{asset.name || asset.filename || asset.airfoil}</span><button aria-label="Close data inspector" onClick={() => setAsset(null)}>×</button></div>
        <p className="text-nv-muted">{asset.type === 'simulation_case' ? `${asset.kind.toUpperCase()} · ${asset.files?.length || 0} input files` : asset.airfoil} · {asset.type === 'simulation_case' ? asset.notes : asset.kind === 'polar_family' ? `${asset.points?.length || 0} polar samples · Mach ${asset.mach} · Ncrit ${asset.ncrit}` : `${asset.coordinates?.length || 0} coordinate points`}</p>
        {asset.demonstration && <p className="text-nv-warn-ink">Synthetic demonstration data; not measurements.</p>}
        <p className="break-all text-[11px] text-nv-muted">SHA256 {asset.source_sha256 || asset.content_hash}</p>
        {typeof asset.source === 'string' && <button className={`${leaf} text-nv-accent`} onClick={downloadSource}>Download original source</button>}
        {asset.kind === 'polar_family' && <button className={`${leaf} text-nv-accent`} disabled={locked} onClick={() => onUsePolar(asset)}>Use these polars in current simulation</button>}
      </div>}
    </div>}
  </details>;
}
