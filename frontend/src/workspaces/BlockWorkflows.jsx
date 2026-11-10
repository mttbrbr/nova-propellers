import { useCallback, useEffect, useMemo, useState } from 'react';
import { Background, Controls, Handle, Position, ReactFlow, addEdge, useEdgesState, useNodesState } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { request } from '../backend.js';
import StageLayout, { StageTitle } from '../shell/StageLayout.jsx';
import LineChart from '../ui/LineChart.jsx';
import { Button, Disclosure, KeyValue, Notice, Section, SelectField, StatusDot } from '../ui/controls.jsx';
import { formatValue, niceTicks } from '../lib/blade.js';

const typeColor = { record: '#4CC9F0', rotor_spec: '#B49CFB', rotor_result: '#46D19A', table: '#F2A93B', report: '#F27C7C' };
const statusTone = { succeeded: 'ok', failed: 'err', blocked: 'muted', violated: 'warn' };
const fmt = (v) => typeof v === 'number' ? formatValue(v, 4) : String(v ?? '—');
const fieldClass = 'h-[30px] w-full min-w-0 rounded-md border border-nv-edge bg-nv-chrome px-2 text-[12.5px] text-nv-ink focus:border-nv-accent focus:outline-none';

// Option hints for the generic configuration editor, keyed by field name.
function optionsFor(key, catalog, rotors) {
  const axial = rotors?.axial_corrections || {}, vertical = rotors?.vertical_corrections || {};
  const map = {
    operator: catalog?.operators, severity: ['hard', 'soft'], on_violation: ['report', 'stop'], sense: ['maximize', 'minimize'],
    method: ['auto', 'bemt', 'cobyla', 'nelder_mead', 'grid', ...(rotors?.vawt_methods || []).map((m) => m.id)],
    variable: ['auto', 'tip_speed_ratio', 'advance_ratio'], preset: (catalog?.constraint_presets || []).map((p) => p.id),
    shape: ['straight', 'troposkien'], name: null, ...Object.fromEntries(Object.entries({ ...axial, ...vertical }).map(([k, v]) => [k, v])),
  };
  if (key === 'preset' && map.preset) return map.preset;
  return map[key] || null;
}
const rowTemplates = {
  checks: { quantity: 'power_w', operator: '<=', value: 1000, severity: 'hard', label: '', unit: '' },
  values: { name: 'p', value: 1, unit: '', min: null, max: null },
  assignments: { name: 'y', expression: 'x * 2', unit: '' },
  variables: { path: 'geometry.radius_m', min: 1, max: 10 },
};

function BlockNode({ data }) {
  const spec = data.spec;
  const rows = Math.max(spec.inputs.length, spec.outputs.length, 1);
  return <div className={`min-w-[190px] rounded-lg border bg-nv-raised text-nv-ink shadow-lg shadow-black/30 ${data.selected ? 'border-nv-accent' : 'border-nv-edge-strong'}`}>
    <div className="flex items-center gap-2 border-b border-nv-line px-3 py-2">
      {data.status && <StatusDot tone={statusTone[data.status] || 'muted'} />}
      <span className="truncate text-[13px] font-medium">{data.id}</span>
      <span className={`ml-auto rounded px-1.5 py-px text-[10.5px] uppercase tracking-wide ${spec.family === 'general' ? 'bg-nv-active text-nv-reference' : 'bg-nv-accent/15 text-nv-accent'}`}>{spec.family === 'general' ? 'gen' : 'spec'}</span>
    </div>
    <div className="px-3 pb-1 pt-1.5 text-[11.5px] text-nv-muted">{spec.label}</div>
    <div className="relative" style={{ height: rows * 22 + 6 }}>
      {spec.inputs.map((port, i) => <div key={port.name} className="absolute left-0 flex items-center text-[11px] text-nv-muted" style={{ top: i * 22 + 2 }}>
        <Handle type="target" position={Position.Left} id={port.name} style={{ top: 9, background: typeColor[port.type], width: 9, height: 9, border: port.optional ? '1px dashed #9AA3AE' : '1px solid #0B0D10' }} />
        <span className="pl-3">{port.name}{port.optional ? '?' : ''}</span></div>)}
      {spec.outputs.map((port, i) => <div key={port.name} className="absolute right-0 flex items-center text-[11px] text-nv-muted" style={{ top: i * 22 + 2 }}>
        <span className="pr-3">{port.name}</span>
        <Handle type="source" position={Position.Right} id={port.name} style={{ top: 9, background: typeColor[port.type], width: 9, height: 9 }} /></div>)}
    </div>
  </div>;
}
const nodeTypes = { block: BlockNode };

const toFlow = (workflow, specs) => ({
  nodes: workflow.nodes.map((n, i) => ({ id: n.id, type: 'block', position: n.position || { x: (i % 5) * 260, y: Math.floor(i / 5) * 200 },
    data: { id: n.id, type: n.type, config: n.config || {}, spec: specs[n.type] } })),
  edges: workflow.edges.map((e) => ({ id: `${e.source}.${e.source_port}-${e.target}.${e.target_port}`, source: e.source, sourceHandle: e.source_port,
    target: e.target, targetHandle: e.target_port, style: { stroke: typeColor[specs[workflow.nodes.find((n) => n.id === e.source)?.type]?.outputs.find((p) => p.name === e.source_port)?.type] || '#3A424E', strokeWidth: 1.6 } })),
});
const fromFlow = (nodes, edges, name) => ({
  schema_version: 2, kind: 'blocks', name,
  nodes: nodes.map((n) => ({ id: n.id, type: n.data.type, config: n.data.config, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } })),
  edges: edges.map((e) => ({ source: e.source, source_port: e.sourceHandle, target: e.target, target_port: e.targetHandle })),
});

export default function BlockWorkflows() {
  const [catalog, setCatalog] = useState(null);
  const [rotorCatalog, setRotorCatalog] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [saved, setSaved] = useState([]);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [name, setName] = useState('Untitled block workflow');
  const [record, setRecord] = useState(null);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const specs = useMemo(() => Object.fromEntries((catalog?.blocks || []).map((b) => [b.type, b])), [catalog]);

  const load = useCallback((workflow, savedRecord = null) => {
    const flow = toFlow(workflow, specs);
    setNodes(flow.nodes); setEdges(flow.edges); setName(savedRecord?.name || workflow.name || 'Block workflow');
    setRecord(savedRecord); setResult(null); setSelected(null);
  }, [specs, setNodes, setEdges]);
  useEffect(() => {
    Promise.all([request('/v1/blocks/catalog'), request('/v1/rotors/catalog'), request('/v1/blocks/templates'), request('/v1/blocks/workflows')])
      .then(([c, r, t, s]) => { setCatalog(c); setRotorCatalog(r); setTemplates(t); setSaved(s); }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (catalog && !nodes.length && templates.length) request(`/v1/blocks/templates/${templates[0].id}`).then((w) => load(w)).catch((e) => setError(e.message));
  }, [catalog, templates]); // eslint-disable-line react-hooks/exhaustive-deps

  const workflow = () => fromFlow(nodes, edges, name);
  const act = async (task) => { setBusy(true); setError(''); try { await task(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  const addBlock = (type) => {
    let index = 1;
    while (nodes.some((n) => n.id === `${type}_${index}`)) index += 1;
    const id = `${type}_${index}`;
    setNodes((list) => [...list, { id, type: 'block', position: { x: 80 + (list.length % 4) * 60, y: 60 + (list.length % 6) * 50 },
      data: { id, type, config: structuredClone(specs[type].defaults), spec: specs[type] } }]);
    setSelected(id); setResult(null);
  };
  const portType = (nodeId, handle, direction) => {
    const node = nodes.find((n) => n.id === nodeId);
    return node?.data.spec[direction].find((p) => p.name === handle)?.type;
  };
  const isValidConnection = (c) => c.source !== c.target && portType(c.source, c.sourceHandle, 'outputs') === portType(c.target, c.targetHandle, 'inputs')
    && !edges.some((e) => e.target === c.target && e.targetHandle === c.targetHandle);
  const onConnect = (c) => { setEdges((list) => addEdge({ ...c, id: `${c.source}.${c.sourceHandle}-${c.target}.${c.targetHandle}`, style: { stroke: typeColor[portType(c.source, c.sourceHandle, 'outputs')], strokeWidth: 1.6 } }, list)); setResult(null); };
  const setConfig = (id, config) => { setNodes((list) => list.map((n) => n.id === id ? { ...n, data: { ...n.data, config } } : n)); setResult(null); };
  const removeBlock = (id) => { setNodes((list) => list.filter((n) => n.id !== id)); setEdges((list) => list.filter((e) => e.source !== id && e.target !== id)); setSelected(null); setResult(null); };
  const run = () => act(async () => { setResult(await request('/v1/blocks/run', { workflow: workflow() })); });
  const save = () => act(async () => {
    const stored = await request('/v1/blocks/workflows', { name, workflow: workflow(), id: record?.id, expected_revision: record?.revision });
    setRecord(stored); setSaved(await request('/v1/blocks/workflows')); setMessage(`Saved revision ${stored.revision}`);
  });

  const display = nodes.map((n) => ({ ...n, data: { ...n.data, status: result?.blocks?.[n.id]?.status, selected: n.id === selected } }));
  const chosen = nodes.find((n) => n.id === selected);
  const groups = useMemo(() => {
    const out = { general: {}, specific: {} };
    (catalog?.blocks || []).forEach((b) => { (out[b.family][b.category] ||= []).push(b); });
    return out;
  }, [catalog]);

  const inputs = <>
    <StageTitle title="Block workflows" detail="Compose general and rotor-specific blocks, bind parameters and enforce real limits." />
    <Section title="Workflow">
      <input aria-label="Workflow name" className={fieldClass} value={name} onChange={(e) => setName(e.target.value)} />
      <SelectField label="Template" ariaLabel="Load template" value="" options={[['', 'Load a template…'], ...templates.map((t) => [t.id, t.name])]}
        onChange={(id) => id && act(async () => load(await request(`/v1/blocks/templates/${id}`)))} />
      {saved.length > 0 && <SelectField label="Saved" ariaLabel="Open saved workflow" value={record?.id || ''} options={[['', 'Open saved…'], ...saved.map((s) => [s.id, `${s.name} · r${s.revision}`])]}
        onChange={(id) => { const item = saved.find((s) => s.id === id); if (item) load(item.workflow, item); }} />}
      <div className="grid grid-cols-2 gap-2">
        <Button variant="primary" disabled={busy || !nodes.length} onClick={run}>{busy ? 'Running…' : 'Run workflow'}</Button>
        <Button disabled={busy || !nodes.length} onClick={save}>Save workflow</Button>
        <Button disabled={busy} onClick={() => { setNodes([]); setEdges([]); setRecord(null); setResult(null); setName('Untitled block workflow'); }}>New</Button>
      <Button disabled={busy || !nodes.length} onClick={() => act(async () => { const v = await request('/v1/blocks/validate', { workflow: workflow() }); setMessage(`Valid · execution order ${v.order.join(' → ')}`); })}>Validate</Button>
      </div>
    </Section>
    {['general', 'specific'].map((family) => <Section key={family} title={family === 'general' ? 'General blocks' : 'Specific blocks'}
      aside={<span className="text-xs text-nv-muted">{family === 'general' ? 'any domain' : 'rotor engineering'}</span>}>
      {Object.entries(groups[family]).map(([category, blocks]) => <div key={category} className="flex flex-col gap-1">
        <span className="text-[11.5px] uppercase tracking-wide text-nv-muted">{category}</span>
        <div className="flex flex-wrap gap-1.5">{blocks.map((b) => <button key={b.type} type="button" title={b.description} onClick={() => addBlock(b.type)}
          className="rounded-md border border-nv-edge px-2 py-1 text-[12px] text-nv-ink hover:border-nv-accent hover:bg-nv-hover">+ {b.label}</button>)}</div>
      </div>)}
    </Section>)}
    <Section title="Port types">
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-nv-muted">{Object.entries(typeColor).map(([type, color]) =>
        <span key={type} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: color }} />{type.replace('_', ' ')}</span>)}</div>
      <p className="m-0 text-xs text-nv-muted">Only matching types connect. Dashed ports are optional.</p>
    </Section>
  </>;

  const content = <div className="flex h-full min-h-[600px] min-w-0 flex-col">
    <div className="flex flex-wrap items-center gap-3 border-b border-nv-line px-6 py-3">
      <h2 className="m-0 text-[15px] font-semibold">{name}</h2>
      {result && <span className="flex items-center gap-2 text-[13px]"><StatusDot tone={result.status === 'succeeded' ? 'ok' : result.status === 'failed' ? 'err' : 'warn'} />
        {result.status}{result.feasible != null && <> · {result.feasible ? 'all hard constraints satisfied' : 'constraint violation'}</>}</span>}
      {message && <span role="status" className="text-xs text-nv-ok-ink">{message}</span>}
    </div>
    {error && <div className="px-6 pt-3"><Notice tone="err" role="alert" action={<button type="button" className="text-nv-muted" onClick={() => setError('')}>×</button>}>{error}</Notice></div>}
    <div aria-label="Block canvas" className="min-h-[480px] flex-1 bg-nv-canvas">
      <ReactFlow nodes={display} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type === 'remove')) setResult(null); }}
        onConnect={onConnect} isValidConnection={isValidConnection} onNodeClick={(_, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)}
        onNodesDelete={(deleted) => { if (deleted.some((n) => n.id === selected)) setSelected(null); setResult(null); }}
        fitView colorMode="dark" minZoom={0.15} maxZoom={2} deleteKeyCode={['Delete', 'Backspace']}>
        <Background color="#1C2027" /><Controls />
      </ReactFlow>
    </div>
  </div>;

  const side = chosen
    ? <BlockInspector key={chosen.id} node={chosen} result={result?.blocks?.[chosen.id]} catalog={catalog} rotors={rotorCatalog}
        onChange={(config) => setConfig(chosen.id, config)} onRemove={() => removeBlock(chosen.id)} />
    : <RunSummary result={result} />;
  return <StageLayout inputsLabel="Block palette" contentLabel="Block workflow canvas" sideLabel="Block inspector" flush inputs={inputs} content={content} side={side} />;
}

function RunSummary({ result }) {
  if (!result) return <div className="flex flex-col gap-3 text-[13px] text-nv-muted">
    <h2 className="m-0 text-[15px] font-semibold text-nv-ink">Run summary</h2>
    <p className="m-0">Select a block to edit it. Run the workflow to see every constraint with its margin.</p>
    <p className="m-0">General blocks (parameters, expressions, constraints, sweeps, optimizer) work on named quantities; specific blocks define rotors, conditions, corrections and solvers.</p>
  </div>;
  return <div className="flex flex-col gap-4">
    <h2 className="m-0 text-[15px] font-semibold">Run summary</h2>
    <div className="flex flex-col gap-1">{result.order.map((id) => <div key={id} className="flex items-center gap-2 text-[13px]">
      <StatusDot tone={statusTone[result.blocks[id].status]} /><span className="w-40 truncate">{id}</span><span className="text-nv-muted">{result.blocks[id].status}</span>
      {result.blocks[id].seconds != null && <span className="ml-auto font-mono text-xs text-nv-muted">{result.blocks[id].seconds.toFixed(2)} s</span>}</div>)}</div>
    {result.reports.map((report) => <ConstraintTable key={report.block} report={report} title={`Constraints · ${report.block}`} />)}
  </div>;
}

function ConstraintTable({ report, title }) {
  return <section aria-label={title} className="flex flex-col gap-2">
    <h3 className="m-0 flex items-center gap-2 text-[13px] font-semibold"><StatusDot tone={report.feasible ? 'ok' : 'err'} />{title}</h3>
    <table className="w-full text-left text-xs tabular-nums"><thead className="text-nv-muted"><tr>{['Check', 'Value', 'Limit', 'Margin', ''].map((h) => <th key={h} className="p-1.5 font-normal">{h}</th>)}</tr></thead>
      <tbody>{report.checks.map((c, i) => <tr key={i} className="border-t border-nv-line">
        <td className="p-1.5">{c.label}{c.severity === 'soft' && <span className="ml-1 text-nv-muted">(soft)</span>}</td>
        <td className="p-1.5 font-mono">{c.error ? c.error : fmt(c.value_observed)}</td>
        <td className="p-1.5 font-mono">{c.operator} {fmt(c.value)}{c.operator === 'between' ? `–${fmt(c.upper)}` : ''} {c.unit}</td>
        <td className="p-1.5 font-mono">{c.margin == null ? '—' : `${(c.margin * 100).toFixed(1)} %`}</td>
        <td className="p-1.5"><StatusDot tone={c.satisfied ? 'ok' : c.severity === 'soft' ? 'warn' : 'err'} /></td></tr>)}</tbody></table>
  </section>;
}

function BlockInspector({ node, result, catalog, rotors, onChange, onRemove }) {
  const spec = node.data.spec;
  const [raw, setRaw] = useState(false);
  const [text, setText] = useState(JSON.stringify(node.data.config, null, 2));
  const [textError, setTextError] = useState('');
  useEffect(() => { if (!raw) setText(JSON.stringify(node.data.config, null, 2)); }, [node.data.config, raw]);
  return <div className="flex flex-col gap-4">
    <div className="flex items-start justify-between gap-3"><div><h2 className="m-0 text-[15px] font-semibold">{node.id}</h2>
      <p className="m-0 mt-1 text-xs text-nv-muted">{spec.label} · {spec.family === 'general' ? 'general' : 'specific'} block</p></div>
      <Button variant="danger" onClick={onRemove}>Remove</Button></div>
    <p className="m-0 text-[13px] text-nv-reference">{spec.description}</p>
    <div className="flex gap-2 text-xs">{spec.inputs.map((p) => <span key={p.name} className="rounded border border-nv-edge px-1.5 py-0.5 text-nv-muted">in {p.name}: {p.type}</span>)}
      {spec.outputs.map((p) => <span key={p.name} className="rounded border border-nv-edge px-1.5 py-0.5 text-nv-muted">out {p.name}: {p.type}</span>)}</div>
    <div className="flex items-center justify-between"><h3 className="m-0 text-[13px] font-semibold">Settings</h3>
      <button type="button" className="text-xs text-nv-reference hover:text-nv-ink" onClick={() => setRaw(!raw)}>{raw ? 'Form view' : 'JSON view'}</button></div>
    {raw ? <><textarea aria-label="Block configuration JSON" className="min-h-[260px] rounded-md border border-nv-edge bg-nv-chrome p-2 font-mono text-[12px]" value={text}
      onChange={(e) => { setText(e.target.value); try { onChange(JSON.parse(e.target.value)); setTextError(''); } catch { setTextError('Invalid JSON'); } }} />
      {textError && <p className="m-0 text-xs text-nv-err-ink">{textError}</p>}</>
      : <ConfigEditor value={node.data.config} onChange={onChange} catalog={catalog} rotors={rotors} path={[]} />}
    {result && <BlockResult result={result} />}
  </div>;
}

function ConfigEditor({ value, onChange, catalog, rotors, path }) {
  const entries = Object.entries(value || {});
  if (!entries.length) return <p className="m-0 text-xs text-nv-muted">No settings.</p>;
  return <div className="flex flex-col gap-2">{entries.map(([key, item]) => <ConfigField key={key} name={key} value={item} catalog={catalog} rotors={rotors} path={[...path, key]}
    onChange={(next) => onChange({ ...value, [key]: next })} />)}</div>;
}

function ScalarInput({ name, value, onChange, catalog, rotors }) {
  const options = optionsFor(name, catalog, rotors);
  if (typeof value === 'boolean') return <input type="checkbox" aria-label={name} className="accent-nv-accent" checked={value} onChange={(e) => onChange(e.target.checked)} />;
  if (options && (typeof value === 'string' || typeof value === 'boolean')) return <select aria-label={name} className={fieldClass} value={String(value)} onChange={(e) => onChange(e.target.value)}>
    {(options.includes(value) ? options : [value, ...options]).map((o) => <option key={String(o)} value={String(o)} className="bg-nv-panel">{String(o).replaceAll('_', ' ')}</option>)}</select>;
  if (name === 'section_name' || (name === 'name' && rotors?.sections?.includes(value))) return <select aria-label={name} className={fieldClass} value={value} onChange={(e) => onChange(e.target.value)}>
    {rotors.sections.map((s) => <option key={s} className="bg-nv-panel">{s}</option>)}</select>;
  if (typeof value === 'number' || value === null) {
    return <input aria-label={name} className={`${fieldClass} font-mono`} inputMode="decimal" value={value ?? ''} placeholder={value === null ? 'none' : undefined}
      onChange={(e) => { const t = e.target.value.trim(); onChange(t === '' ? null : Number.isFinite(Number(t)) ? Number(t) : value); }} />;
  }
  return <input aria-label={name} className={`${fieldClass} ${name === 'expression' || name === 'quantity' ? 'font-mono' : ''}`} value={value ?? ''} onChange={(e) => onChange(e.target.value)} />;
}

function ConfigField({ name, value, onChange, catalog, rotors, path }) {
  const label = name.replaceAll('_', ' ');
  if (name === 'bindings') return <BindingsEditor value={value || {}} onChange={onChange} />;
  if (Array.isArray(value) && value.every((v) => typeof v === 'number')) {
    return <label className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-2 text-[12.5px] text-nv-muted">{label}
      <input aria-label={name} className={`${fieldClass} font-mono`} value={value.join(', ')} onChange={(e) => onChange(e.target.value.split(',').map((t) => Number(t.trim())).filter((v) => Number.isFinite(v)))} /></label>;
  }
  if (Array.isArray(value)) {
    // Preset checks show their default limit and severity so they can be edited in place.
    const presets = Object.fromEntries((catalog?.constraint_presets || []).map((p) => [p.id, p]));
    if (name === 'checks') value = value.map((row) => row.preset ? { value: presets[row.preset]?.value ?? 0, severity: 'hard', ...row } : row);
    return <Disclosure title={label} summary={`${value.length} item${value.length === 1 ? '' : 's'}`} defaultOpen={path.length === 1}>
      {value.map((row, index) => <div key={index} className="flex flex-col gap-1.5 rounded-md border border-nv-line p-2">
        <ConfigEditor value={row} catalog={catalog} rotors={rotors} path={[...path, index]} onChange={(next) => onChange(value.map((r, i) => i === index ? next : r))} />
        <button type="button" className="self-end text-xs text-nv-err-ink" onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove</button></div>)}
      <div className="flex gap-2">
        <button type="button" className="text-xs text-nv-reference hover:text-nv-ink" onClick={() => onChange([...value, structuredClone(rowTemplates[name] || value.at(-1) || {})])}>+ Add</button>
        {name === 'checks' && <select aria-label="Add preset check" className={fieldClass} value="" onChange={(e) => e.target.value && onChange([...value, { preset: e.target.value, value: presets[e.target.value].value, severity: 'hard' }])}>
          <option value="">+ Add preset…</option>{(catalog?.constraint_presets || []).map((p) => <option key={p.id} value={p.id} title={p.rationale}>{p.label} ({p.quantity} {p.operator} {formatValue(p.value, 3)} {p.unit})</option>)}</select>}
      </div>
    </Disclosure>;
  }
  if (value && typeof value === 'object') {
    return <Disclosure title={label} summary={`${Object.keys(value).length} fields`} defaultOpen={path.length === 1 && Object.keys(value).length <= 8}>
      <ConfigEditor value={value} onChange={onChange} catalog={catalog} rotors={rotors} path={path} /></Disclosure>;
  }
  return <label className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-2 text-[12.5px] text-nv-muted">{label}
    <ScalarInput name={name} value={value} onChange={onChange} catalog={catalog} rotors={rotors} /></label>;
}

function BindingsEditor({ value, onChange }) {
  const rows = Object.entries(value);
  const rename = (from, to) => onChange(Object.fromEntries(rows.map(([k, v]) => [k === from ? to : k, v])));
  return <Disclosure title="Bindings" summary={rows.length ? `${rows.length} driven field${rows.length === 1 ? '' : 's'}` : 'none'} defaultOpen={rows.length > 0}>
    <p className="m-0 text-xs text-nv-muted">Drive specification fields from the connected parameters, e.g. geometry.radius_m = D / 2.</p>
    {rows.map(([path, expression]) => <div key={path} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-1.5">
      <input aria-label="Binding path" className={`${fieldClass} font-mono`} defaultValue={path} onBlur={(e) => e.target.value !== path && rename(path, e.target.value)} />
      <input aria-label={`Binding ${path}`} className={`${fieldClass} font-mono`} value={expression} onChange={(e) => onChange({ ...value, [path]: e.target.value })} />
      <button type="button" aria-label={`Remove binding ${path}`} className="px-1 text-nv-err-ink" onClick={() => onChange(Object.fromEntries(rows.filter(([k]) => k !== path)))}>×</button></div>)}
    <button type="button" className="self-start text-xs text-nv-reference hover:text-nv-ink" onClick={() => { let i = 1; while (value[`geometry.field_${i}`]) i += 1; onChange({ ...value, [`geometry.field_${i}`]: 'x' }); }}>+ Add binding</button>
  </Disclosure>;
}

function BlockResult({ result }) {
  return <section aria-label="Block result" className="flex flex-col gap-3 border-t border-nv-line pt-4">
    <h3 className="m-0 flex items-center gap-2 text-[13px] font-semibold"><StatusDot tone={statusTone[result.status]} />Result · {result.status}</h3>
    {result.error && <Notice tone={result.status === 'blocked' ? 'info' : 'err'}>{result.error}</Notice>}
    {result.outputs && Object.entries(result.outputs).map(([port, value]) => <PortValue key={port} port={port} value={value} />)}
  </section>;
}

function PortValue({ port, value }) {
  if (value && Array.isArray(value.checks) && 'feasible' in value) return <ConstraintTable report={value} title={`Constraints (${port})`} />;
  if (value && value.rows) return <TableValue port={port} table={value} />;
  if (value && value.kind && value.performance) {
    return <div className="flex flex-col gap-1"><span className="text-xs text-nv-muted">{port}: {value.method_label}</span>
      {value.warnings?.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}</div>;
  }
  if (value && value.kind && value.geometry) return <p className="m-0 text-xs text-nv-muted">{port}: {value.kind} specification ({Object.keys(value.geometry).length} geometry fields)</p>;
  if (value && value.title) return <div className="flex flex-col gap-2"><span className="text-xs text-nv-muted">{port}: {value.title}</span>
    {value.values && <Record values={value.values} />}{value.table && <TableValue port="table" table={value.table} />}
    {value.checks?.map((r) => <ConstraintTable key={r.block} report={r} title={`Constraints · ${r.block}`} />)}</div>;
  if (value && typeof value === 'object') return <div className="flex flex-col gap-1"><span className="text-xs text-nv-muted">{port}</span><Record values={value} /></div>;
  return null;
}

function Record({ values }) {
  const entries = Object.entries(values).filter(([, v]) => typeof v === 'number');
  return <details open={entries.length <= 14} className="text-[12.5px]"><summary className="cursor-pointer text-xs text-nv-reference">{entries.length} values</summary>
    <div className="mt-1 flex flex-col gap-0.5">{entries.map(([k, v]) => <KeyValue key={k} label={k}><span className="font-mono">{fmt(v)}</span></KeyValue>)}</div></details>;
}

function TableValue({ port, table }) {
  const rows = table.rows.filter((r) => r.state !== 'failed');
  const x = table.kind === 'performance_curve' ? table.variable : table.kind === 'sweep' ? 'value' : 'evaluation';
  const y = table.kind === 'optimization' ? 'objective' : table.rotor_kind && !['hawt', 'vawt'].includes(table.rotor_kind) ? (table.rotor_kind === 'marine' ? 'open_water_efficiency' : 'efficiency') : 'CP';
  const points = rows.filter((r) => typeof r[x] === 'number' && typeof r[y] === 'number').map((r) => ({ x: r[x], y: r[y] })).sort((a, b) => a.x - b.x);
  const lo = points[0]?.x ?? 0, hi = points.at(-1)?.x ?? 1;
  const ticks = niceTicks(lo, hi, 3).filter((t) => t >= lo - 1e-9 && t <= hi + 1e-9);
  const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => !['state', 'error'].includes(k)).slice(0, 8);
  return <div className="flex flex-col gap-2">
    <span className="text-xs text-nv-muted">{port}: {table.kind} · {table.rows.length} rows{table.filtered_from != null ? ` (of ${table.filtered_from})` : ''}</span>
    {points.length > 1 && hi > lo && <LineChart title={`${y} vs ${x === 'tip_speed_ratio' ? 'λ' : x === 'advance_ratio' ? 'J' : x}`} series={[{ id: 'y', color: '#4CC9F0', points }]} height={170}
      xDomain={[lo, hi]} xTicks={ticks.length > 1 ? ticks : [lo, hi]} xLabel={x === 'tip_speed_ratio' ? 'λ' : x === 'advance_ratio' ? 'J' : ''} />}
    <details className="text-xs"><summary className="cursor-pointer text-nv-reference">Rows</summary><div className="mt-1 max-h-64 overflow-auto">
      <table className="w-full text-left tabular-nums"><thead className="text-nv-muted"><tr>{columns.map((c) => <th key={c} className="p-1 font-normal">{c}</th>)}</tr></thead>
        <tbody>{table.rows.map((r, i) => <tr key={i} className="border-t border-nv-line">{columns.map((c) => <td key={c} className="p-1 font-mono">{fmt(r[c])}</td>)}</tr>)}</tbody></table></div></details>
  </div>;
}
