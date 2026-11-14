import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Keyboard, LayoutTemplate, Maximize, Network, Play, Save, Search, Square, X } from 'lucide-react';
import { Background, Controls, Handle, Position, ReactFlow, ReactFlowProvider, addEdge, useEdgesState, useNodesState, useReactFlow, useViewport } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { request } from '../backend.js';
import LineChart from '../ui/LineChart.jsx';
import { Button, Disclosure, IconButton, KeyValue, MenuItem, Notice, Popover, StatusDot } from '../ui/controls.jsx';
import { formatValue, niceTicks } from '../lib/blade.js';

const IntegrationsContext = createContext({ list: [], openSettings: null });
const typeColor = { record: '#FF8533', rotor_spec: '#B49CFB', rotor_result: '#46D19A', table: '#4CC9F0', report: '#F27C7C', openfast_case: '#E8B34A' };
const statusTone = { succeeded: 'ok', failed: 'err', blocked: 'muted', violated: 'warn' };
const fmt = (v) => typeof v === 'number' ? formatValue(v, 4) : String(v ?? '—');
const fieldClass = 'h-[30px] w-full min-w-0 rounded-md border border-nv-edge bg-nv-chrome px-2 text-[12.5px] text-nv-ink focus:border-nv-accent focus:outline-none';

// Option hints for the generic configuration editor, keyed by field name.
function optionsFor(key, catalog, rotors) {
  const axial = rotors?.axial_corrections || {}, vertical = rotors?.vertical_corrections || {};
  const map = {
    operator: catalog?.operators, severity: ['hard', 'soft'], stat: ['mean', 'min', 'max', 'std', 'final'], on_violation: ['report', 'stop'], sense: ['maximize', 'minimize'],
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

export default function BlockWorkflows(props) {
  return <ReactFlowProvider><BlockEditor {...props} /></ReactFlowProvider>;
}

const typing = (el) => el?.matches?.('input, select, textarea, [contenteditable="true"]');
const OVERLAY = 'absolute z-10 rounded-xl border border-nv-edge bg-nv-panel/95 backdrop-blur';
const shortcuts = [['Add a block here', 'Double-click'], ['Search blocks', 'Ctrl K'], ['Run workflow', 'Ctrl Enter'], ['Save', 'Ctrl S'], ['Duplicate block', 'Ctrl D'],
  ['Remove block', 'Del'], ['Auto-layout', 'L'], ['Fit view', 'F'], ['Pan', 'Drag'], ['Close any card', 'Esc'], ['Show shortcuts', '?']];
const Kbd = ({ children }) => <kbd className="rounded border border-b-2 border-nv-edge bg-nv-chrome px-1.5 font-mono text-[11px] text-nv-muted">{children}</kbd>;

// Layered auto-layout: column = longest path from a source, rows stacked per column.
function layered(nodes, edges) {
  const depth = Object.fromEntries(nodes.map((n) => [n.id, 0]));
  for (let pass = 0; pass < nodes.length; pass += 1) edges.forEach((e) => { if (depth[e.source] + 1 > depth[e.target]) depth[e.target] = Math.min(depth[e.source] + 1, nodes.length); });
  const rows = {};
  return nodes.map((n) => { const col = depth[n.id], row = rows[col] = (rows[col] ?? -1) + 1; return { ...n, position: { x: col * 260, y: row * 200 } }; });
}

// Settings card next to the selected block. Its real size is measured, then the first side where it fits
// entirely inside the canvas wins (right, left, below, above); otherwise it is clamped on screen.
const CARD_WIDTH = 340, GAP = 16, MARGIN = 12;
const clamp = (value, low, high) => Math.max(low, Math.min(value, Math.max(low, high)));

function placeCard(box, rect, height) {
  const top = (wanted) => clamp(wanted, MARGIN, box.height - height - MARGIN);
  const left = (wanted) => clamp(wanted, MARGIN, box.width - CARD_WIDTH - MARGIN);
  const options = [
    { side: 'right', fits: rect.x + rect.w + GAP + CARD_WIDTH <= box.width - MARGIN, left: rect.x + rect.w + GAP, top: top(rect.y - 8) },
    { side: 'left', fits: rect.x - GAP - CARD_WIDTH >= MARGIN, left: rect.x - GAP - CARD_WIDTH, top: top(rect.y - 8) },
    { side: 'below', fits: rect.y + rect.h + GAP + height <= box.height - MARGIN, left: left(rect.x + rect.w / 2 - CARD_WIDTH / 2), top: rect.y + rect.h + GAP },
    { side: 'above', fits: rect.y - GAP - height >= MARGIN, left: left(rect.x + rect.w / 2 - CARD_WIDTH / 2), top: rect.y - GAP - height },
  ];
  const chosen = options.find((o) => o.fits);
  if (chosen) return chosen;
  // Nothing fits (small canvas or huge block): overlap the block on the roomier horizontal side, kept on screen.
  const rightRoom = box.width - (rect.x + rect.w), leftRoom = rect.x;
  return { side: 'overlap', left: left(rightRoom >= leftRoom ? rect.x + rect.w + GAP : rect.x - GAP - CARD_WIDTH), top: top(rect.y - 8) };
}

function SettingsCard({ canvas, node, viewport, children }) {
  const card = useRef(null);
  const [placement, setPlacement] = useState(null);
  const measure = useCallback(() => {
    if (!canvas.current || !card.current) return;
    const box = { width: canvas.current.clientWidth, height: canvas.current.clientHeight };
    const rect = { x: node.position.x * viewport.zoom + viewport.x, y: node.position.y * viewport.zoom + viewport.y,
      w: (node.measured?.width || 190) * viewport.zoom, h: (node.measured?.height || 120) * viewport.zoom };
    const height = Math.min(card.current.offsetHeight, box.height - 2 * MARGIN);
    const next = placeCard(box, rect, height);
    const caret = next.side === 'right' || next.side === 'left' ? clamp(rect.y + rect.h / 2 - next.top - 6, 20, height - 28)
      : next.side === 'below' || next.side === 'above' ? clamp(rect.x + rect.w / 2 - next.left - 6, 20, CARD_WIDTH - 28) : null;
    setPlacement((previous) => previous && previous.left === next.left && previous.top === next.top && previous.side === next.side && previous.caret === caret ? previous : { ...next, caret });
  }, [canvas, node.position.x, node.position.y, node.measured?.width, node.measured?.height, viewport.x, viewport.y, viewport.zoom]);
  useLayoutEffect(measure, [measure]);
  useEffect(() => { // content grows and shrinks (disclosures, results), and the window resizes
    const watcher = new ResizeObserver(measure);
    if (card.current) watcher.observe(card.current);
    if (canvas.current) watcher.observe(canvas.current);
    return () => watcher.disconnect();
  }, [measure, canvas]);
  const side = placement?.side;
  const caretStyle = side === 'right' ? { top: placement.caret, left: -7, borderWidth: '0 0 1px 1px' } : side === 'left' ? { top: placement.caret, right: -7, borderWidth: '1px 1px 0 0' }
    : side === 'below' ? { left: placement.caret, top: -7, borderWidth: '1px 0 0 1px' } : side === 'above' ? { left: placement.caret, bottom: -7, borderWidth: '0 1px 1px 0' } : null;
  return <div ref={card} role="region" aria-label="Block settings" data-side={side}
    className="absolute z-20 flex flex-col rounded-2xl border border-nv-edge bg-nv-panel/[0.97] shadow-2xl shadow-black/60"
    style={{ width: CARD_WIDTH, maxHeight: canvas.current ? canvas.current.clientHeight - 2 * MARGIN : undefined, left: placement?.left ?? 0, top: placement?.top ?? 0, visibility: placement ? 'visible' : 'hidden' }}>
    {caretStyle && <span aria-hidden="true" className="absolute h-3 w-3 rotate-45 border border-nv-edge bg-nv-panel" style={caretStyle} />}
    <div className="overflow-y-auto p-4">{children}</div>
  </div>;
}

function BlockEditor({ seed = null, onOpenSettings = null }) {
  const flow = useReactFlow();
  const viewport = useViewport();
  const canvas = useRef(null);
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
  const [panel, setPanel] = useState(null); // 'results' | 'keys' | null
  const [palette, setPalette] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(null); // {id, progress, message} while a run is in the background
  const [integrations, setIntegrations] = useState([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const specs = useMemo(() => Object.fromEntries((catalog?.blocks || []).map((b) => [b.type, b])), [catalog]);

  const load = useCallback((workflow, savedRecord = null) => {
    const loaded = toFlow(workflow, specs);
    setNodes(loaded.nodes); setEdges(loaded.edges); setName(savedRecord?.name || workflow.name || 'Block workflow');
    setRecord(savedRecord); setResult(null); setSelected(null); setPanel(null); setPalette(null);
    setTimeout(() => flow.fitView({ padding: 0.2, duration: 200 }), 30);
  }, [specs, setNodes, setEdges, flow]);
  useEffect(() => {
    Promise.all([request('/v1/blocks/catalog'), request('/v1/rotors/catalog'), request('/v1/blocks/templates'), request('/v1/blocks/workflows'), request('/v1/integrations')])
      .then(([c, r, t, s, i]) => { setCatalog(c); setRotorCatalog(r); setTemplates(t); setSaved(s); setIntegrations(i); }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!catalog || !templates.length) return;
    // A workflow handed over from the design sheet (e.g. "Open as workflow") wins over the default template.
    if (seed?.workflow) { load(seed.workflow); return; }
    if (!nodes.length) request(`/v1/blocks/templates/${templates[0].id}`).then((w) => load(w)).catch((e) => setError(e.message));
  }, [catalog, templates, seed?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!message) return undefined; const t = setTimeout(() => setMessage(''), 3500); return () => clearTimeout(t); }, [message]);

  const workflow = () => fromFlow(nodes, edges, name);
  const act = async (task) => { setBusy(true); setError(''); try { await task(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  const addBlock = (type, position) => {
    let index = 1;
    while (nodes.some((n) => n.id === `${type}_${index}`)) index += 1;
    const id = `${type}_${index}`;
    const at = position || flow.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
    setNodes((list) => [...list, { id, type: 'block', position: { x: Math.round(at.x), y: Math.round(at.y) },
      data: { id, type, config: structuredClone(specs[type].defaults), spec: specs[type] } }]);
    setSelected(id); setResult(null); setPalette(null);
  };
  const duplicate = (id) => {
    const source = nodes.find((n) => n.id === id);
    if (!source) return;
    let index = 1;
    while (nodes.some((n) => n.id === `${source.data.type}_${index}`)) index += 1;
    const copy = `${source.data.type}_${index}`;
    setNodes((list) => [...list, { ...source, id: copy, selected: false, position: { x: source.position.x + 40, y: source.position.y + 60 }, data: { ...source.data, id: copy, config: structuredClone(source.data.config) } }]);
    setSelected(copy); setResult(null);
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
  const cancelled = useRef(false);
  const run = () => act(async () => {
    cancelled.current = false;
    let current = await request('/v1/blocks/runs', { workflow: workflow() });
    setProgress(current); setSelected(null); setPanel(null); setResult(null);
    try {
      while (current.state === 'running') {
        await new Promise((resolve) => setTimeout(resolve, 600));
        current = await request(`/v1/blocks/runs/${current.id}`);
        setProgress(current);
      }
    } finally { setProgress(null); }
    if (current.state === 'succeeded') { setResult(current.result); setPanel('results'); }
    else if (current.state === 'cancelled') setMessage('Run cancelled');
    else throw new Error(current.error || 'The run failed');
  });
  const cancelRun = () => progress && request(`/v1/blocks/runs/${progress.id}/cancel`, {}).then(setProgress).catch((e) => setError(e.message));
  const validate = () => act(async () => { const v = await request('/v1/blocks/validate', { workflow: workflow() }); setMessage(`Valid · execution order ${v.order.join(' → ')}`); });
  const save = (copy = false) => act(async () => {
    const stored = await request('/v1/blocks/workflows', { name, workflow: workflow(), id: copy ? undefined : record?.id, expected_revision: copy ? undefined : record?.revision });
    setRecord(stored); setSaved(await request('/v1/blocks/workflows')); setMessage(copy ? `Saved “${stored.name}” as a template` : `Saved revision ${stored.revision}`);
  });
  const fresh = () => { setNodes([]); setEdges([]); setRecord(null); setResult(null); setSelected(null); setPanel(null); setName('Untitled block workflow'); };
  const layout = () => { setNodes((list) => layered(list, edges)); setTimeout(() => flow.fitView({ padding: 0.2, duration: 250 }), 30); };
  const openPalette = (screen) => {
    const box = canvas.current.getBoundingClientRect();
    const at = screen || { x: box.left + box.width / 2 - 190, y: box.top + box.height / 3 };
    setSelected(null); setPanel(null);
    setPalette({ x: at.x - box.left, y: at.y - box.top, flow: flow.screenToFlowPosition(at), q: '', f: 'all', on: 0 });
  };

  const keys = useRef();
  keys.current = { run, cancelRun, running: Boolean(progress), save, duplicate, layout, openPalette, selected, palette, nodes, busy };
  useEffect(() => {
    const onKey = (e) => {
      const k = keys.current, mod = e.ctrlKey || e.metaKey;
      if (e.key === 'Escape') { setPalette(null); setSelected(null); setPanel(null); return; }
      if (mod && e.key === 'Enter') { e.preventDefault(); if (k.running) k.cancelRun(); else if (!k.busy && k.nodes.length) k.run(); return; }
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); if (!k.busy && k.nodes.length) k.save(); return; }
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); k.openPalette(); return; }
      if (typing(e.target) || mod && e.key.toLowerCase() !== 'd') return;
      if (mod && e.key.toLowerCase() === 'd') { e.preventDefault(); if (k.selected) k.duplicate(k.selected); return; }
      if (e.key === '/') { e.preventDefault(); k.openPalette(); }
      else if (e.key === '?') setPanel((p) => p === 'keys' ? null : 'keys');
      else if (e.key.toLowerCase() === 'l') k.layout();
      else if (e.key.toLowerCase() === 'f') flow.fitView({ padding: 0.2, duration: 250 });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [flow]);

  const display = nodes.map((n) => ({ ...n, data: { ...n.data, status: result?.blocks?.[n.id]?.status, selected: n.id === selected } }));
  const chosen = nodes.find((n) => n.id === selected);
  const tone = !result ? null : result.status === 'succeeded' ? (result.feasible === false ? 'warn' : 'ok') : result.status === 'failed' ? 'err' : 'warn';

  return <IntegrationsContext.Provider value={{ list: integrations.filter((i) => i.adapter_id === 'openfast'), openSettings: onOpenSettings }}><div ref={canvas} aria-label="Block workflow canvas" className="relative min-h-[560px] min-w-0 flex-1 bg-nv-canvas xl:h-full xl:min-h-0"
    onDoubleClick={(e) => { if (e.target.classList?.contains('react-flow__pane')) openPalette({ x: e.clientX, y: e.clientY }); }}>
    <ReactFlow nodes={display} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type === 'remove')) setResult(null); }}
      onConnect={onConnect} isValidConnection={isValidConnection} onNodeClick={(_, n) => { setSelected(n.id); setPalette(null); setPanel(null); }}
      onPaneClick={() => { setSelected(null); setPalette(null); setPanel((p) => p === 'keys' ? null : p); }}
      onNodeDragStart={() => setSelected(null)} onMoveStart={(event) => { if (event) { setSelected(null); setPalette(null); } }}
      onNodesDelete={(deleted) => { if (deleted.some((n) => n.id === selected)) setSelected(null); setResult(null); }}
      zoomOnDoubleClick={false} fitView fitViewOptions={{ padding: 0.2 }} colorMode="dark" minZoom={0.15} maxZoom={2} deleteKeyCode={['Delete', 'Backspace']} proOptions={{ hideAttribution: true }}>
      <Background color="#1C2027" /><Controls position="bottom-left" showInteractive={false} />
    </ReactFlow>

    <div className={`${OVERLAY} left-3.5 top-3.5 flex h-10 items-center gap-2 px-2`}>
      <input aria-label="Workflow name" className="h-8 w-[220px] rounded-md bg-transparent px-2 text-[13px] font-medium hover:bg-nv-hover focus:bg-nv-chrome focus:outline-none" value={name} onChange={(e) => setName(e.target.value)} />
      <span className="pr-1 text-xs text-nv-muted">{record ? `r${record.revision}` : 'Not saved'}</span>
    </div>

    <div role="toolbar" aria-label="Workflow tools" aria-orientation="vertical" className={`${OVERLAY} right-3.5 top-3.5 flex flex-col gap-0.5 p-1`}>
      <IconButton label={progress ? 'Cancel run' : 'Run workflow'} shortcut="Ctrl Enter" tooltipSide="left" icon={progress ? Square : Play} disabled={progress ? progress.state !== 'running' : busy || !nodes.length} onClick={progress ? cancelRun : run} className="!bg-nv-accent !text-[#1A0F06] hover:!bg-[#FF9A57] disabled:!bg-transparent disabled:!text-nv-muted" />
      <IconButton label="Validate" tooltipSide="left" icon={CheckCircle2} disabled={busy || !nodes.length} onClick={validate} />
      <IconButton label="Save workflow" shortcut="Ctrl S" tooltipSide="left" icon={Save} disabled={busy || !nodes.length} onClick={() => save()} />
      <div className="mx-1 my-0.5 h-px bg-nv-line" />
      <Popover label="Templates" align="right" width="w-72" trigger={({ ref, open, toggle }) => <IconButton ref={ref} label="Templates" tooltipSide="left" icon={LayoutTemplate} active={open} aria-expanded={open} onClick={toggle} />}>
        {(close) => <div className="flex flex-col gap-0.5 p-1.5">
          <span className="px-2.5 pb-0.5 pt-1.5 text-[11.5px] uppercase tracking-wide text-nv-muted">Built-in templates</span>
          {templates.map((t) => <MenuItem key={t.id} onClick={() => { close(); act(async () => load(await request(`/v1/blocks/templates/${t.id}`))); }}>{t.name}</MenuItem>)}
          {saved.length > 0 && <span className="px-2.5 pb-0.5 pt-2 text-[11.5px] uppercase tracking-wide text-nv-muted">My templates</span>}
          {saved.map((s) => <MenuItem key={s.id} hint={`r${s.revision}`} onClick={() => { close(); load(s.workflow, s); }}>{s.name}</MenuItem>)}
          <div className="my-1 h-px bg-nv-line" />
          <MenuItem disabled={busy || !nodes.length} onClick={() => { close(); save(true); }}>Save as new template</MenuItem>
          <MenuItem onClick={() => { close(); fresh(); }}>Blank workflow</MenuItem>
        </div>}
      </Popover>
      <IconButton label="Auto-layout" shortcut="L" tooltipSide="left" icon={Network} disabled={!nodes.length} onClick={layout} />
      <IconButton label="Fit view" shortcut="F" tooltipSide="left" icon={Maximize} onClick={() => flow.fitView({ padding: 0.2, duration: 250 })} />
      <IconButton label="Search blocks" shortcut="Ctrl K" tooltipSide="left" icon={Search} disabled={!catalog} onClick={() => openPalette()} />
      <IconButton label="Shortcuts" shortcut="?" tooltipSide="left" icon={Keyboard} active={panel === 'keys'} onClick={() => setPanel(panel === 'keys' ? null : 'keys')} />
    </div>

    {!selected && !palette && !panel && catalog && <div className={`${OVERLAY} pointer-events-none bottom-3.5 left-1/2 flex h-8 -translate-x-1/2 items-center gap-2 rounded-full px-3.5 text-[12.5px] text-nv-muted`}>
      Double-click to add a block <Kbd>Ctrl K</Kbd> to search</div>}
    {(error || message) && <div className="absolute left-1/2 top-3.5 z-20 w-[min(560px,60%)] -translate-x-1/2">
      {error ? <Notice tone="err" role="alert" action={<button type="button" aria-label="Dismiss" className="text-nv-muted" onClick={() => setError('')}>×</button>}>{error}</Notice>
        : <Notice tone="ok"><span role="status">{message}</span></Notice>}</div>}
    {progress && <div role="status" aria-label="Run progress" className={`${OVERLAY} bottom-3.5 right-3.5 flex h-9 max-w-[420px] items-center gap-2.5 px-3 text-[12.5px]`}>
      <span className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-nv-line"><span className="block h-full bg-nv-accent transition-all" style={{ width: `${Math.round((progress.progress || 0) * 100)}%` }} /></span>
      <span className="truncate text-nv-reference">{progress.message}</span></div>}
    {result && !progress && <button type="button" onClick={() => setPanel(panel === 'results' ? null : 'results')} className={`${OVERLAY} bottom-3.5 right-3.5 flex h-9 items-center gap-2 px-3 text-[12.5px] hover:bg-nv-hover`}>
      <StatusDot tone={tone} />{result.status}{result.feasible != null && <> · {result.feasible ? 'hard constraints met' : 'constraint violation'}</>}<Kbd>Details</Kbd></button>}

    {chosen && !palette && <SettingsCard canvas={canvas} node={chosen} viewport={viewport}>
      <BlockInspector key={chosen.id} node={chosen} result={result?.blocks?.[chosen.id]} catalog={catalog} rotors={rotorCatalog}
        onChange={(config) => setConfig(chosen.id, config)} onRemove={() => removeBlock(chosen.id)} onDuplicate={() => duplicate(chosen.id)} onClose={() => setSelected(null)} />
    </SettingsCard>}

    {palette && catalog && <BlockSearch palette={palette} blocks={catalog.blocks} onChange={setPalette} onPick={(type) => addBlock(type, palette.flow)} onClose={() => setPalette(null)} bounds={canvas.current?.getBoundingClientRect()} />}

    {panel === 'results' && result && <div role="region" aria-label="Run summary" className="absolute bottom-16 right-3.5 z-20 max-h-[70%] w-[380px] overflow-y-auto rounded-2xl border border-nv-edge bg-nv-panel/[0.97] p-4 shadow-2xl shadow-black/60"><RunSummary result={result} /></div>}
    {panel === 'keys' && <div role="dialog" aria-label="Keyboard shortcuts" className="absolute left-1/2 top-1/2 z-30 w-[min(560px,90%)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-nv-edge bg-nv-panel/[0.97] p-5 shadow-2xl shadow-black/60">
      <div className="mb-3 flex items-center"><h2 className="m-0 text-[15px] font-semibold">Shortcuts</h2><button type="button" aria-label="Close" className="ml-auto text-nv-muted hover:text-nv-ink" onClick={() => setPanel(null)}><X size={16} /></button></div>
      <div className="grid grid-cols-1 gap-x-9 sm:grid-cols-2">{shortcuts.map(([label, combo]) => <div key={label} className="flex items-center justify-between border-b border-nv-line py-1.5 text-[12.5px] text-nv-reference">
        <span>{label}</span><span className="flex gap-1">{combo.split(' ').map((c) => <Kbd key={c}>{c}</Kbd>)}</span></div>)}</div></div>}
  </div></IntegrationsContext.Provider>;
}

function BlockSearch({ palette, blocks, onChange, onPick, onClose, bounds }) {
  const input = useRef(null);
  useEffect(() => { input.current?.focus(); }, []);
  const q = palette.q.trim().toLowerCase();
  const list = blocks.filter((b) => (palette.f === 'all' || (palette.f === 'general') === (b.family === 'general')) && (!q || `${b.label} ${b.type} ${b.description} ${b.category}`.toLowerCase().includes(q)));
  const on = Math.min(palette.on, Math.max(list.length - 1, 0));
  const left = Math.min(Math.max(palette.x - 24, 12), Math.max((bounds?.width || 1000) - 392, 12)), top = Math.min(Math.max(palette.y - 20, 12), Math.max((bounds?.height || 700) - 440, 12));
  const key = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); onChange({ ...palette, on: (on + (e.key === 'ArrowDown' ? 1 : -1) + list.length) % Math.max(list.length, 1) }); }
    else if (e.key === 'Enter' && list[on]) { e.preventDefault(); onPick(list[on].type); }
    else if (e.key === 'Escape') { e.stopPropagation(); onClose(); }
  };
  return <div role="dialog" aria-label="Add a block" className="absolute z-30 w-[380px] rounded-2xl border border-nv-edge bg-nv-panel/[0.97] shadow-2xl shadow-black/60" style={{ left, top }}>
    <div className="flex items-center gap-2.5 border-b border-nv-line px-3.5 py-2.5"><Search size={16} className="text-nv-muted" aria-hidden="true" />
      <input ref={input} aria-label="Search blocks" placeholder="Add a block…" autoComplete="off" className="min-w-0 flex-1 bg-transparent text-sm focus:outline-none" value={palette.q}
        onChange={(e) => onChange({ ...palette, q: e.target.value, on: 0 })} onKeyDown={key} /><Kbd>Esc</Kbd></div>
    <div className="flex gap-1 px-3 pb-1 pt-2">{[['all', 'All'], ['general', 'General'], ['specific', 'Rotor']].map(([id, label]) => <button key={id} type="button" aria-pressed={palette.f === id}
      className={`h-6 rounded-md px-2.5 text-xs ${palette.f === id ? 'bg-nv-active text-nv-ink' : 'text-nv-muted hover:text-nv-ink'}`} onClick={() => { onChange({ ...palette, f: id, on: 0 }); input.current?.focus(); }}>{label}</button>)}</div>
    <ul role="listbox" aria-label="Blocks" className="m-0 max-h-[290px] list-none overflow-y-auto p-1.5">
      {list.map((b, i) => <li key={b.type} role="option" aria-selected={i === on} onMouseEnter={() => onChange({ ...palette, on: i })} onClick={() => onPick(b.type)}
        className={`flex cursor-pointer flex-col rounded-lg px-2.5 py-1.5 ${i === on ? 'bg-nv-active' : ''}`}>
        <span className="flex items-center gap-2 text-[13px]"><span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ background: typeColor[b.outputs[0]?.type] || '#8A93A0' }} />{b.label}
          <span className={`ml-auto rounded px-1.5 text-[10.5px] uppercase tracking-wide ${b.family === 'general' ? 'bg-nv-active text-nv-reference' : 'bg-nv-accent/15 text-nv-accent'}`}>{b.family === 'general' ? 'general' : 'rotor'}</span></span>
        <span className="text-[11.5px] text-nv-muted">{b.inputs.length ? b.inputs.map((p) => p.name).join(', ') : 'no input'} → {b.outputs.map((p) => p.name).join(', ')} · {b.description}</span></li>)}
      {!list.length && <li className="px-2.5 py-2 text-[13px] text-nv-muted">No block matches.</li>}
    </ul>
    <div className="flex items-center gap-3 border-t border-nv-line px-3.5 py-2 text-[11.5px] text-nv-muted"><span><Kbd>↑↓</Kbd> move</span><span><Kbd>Enter</Kbd> add here</span>
      <span className="ml-auto flex gap-2">{Object.entries(typeColor).map(([type, color]) => <span key={type} title={type} className="inline-flex items-center gap-1"><i className="h-[7px] w-[7px] rounded-full" style={{ background: color }} />{type.replace('rotor_', '').replace('_', ' ')}</span>)}</span></div>
  </div>;
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

function BlockInspector({ node, result, catalog, rotors, onChange, onRemove, onDuplicate, onClose }) {
  const spec = node.data.spec;
  const [raw, setRaw] = useState(false);
  const [text, setText] = useState(JSON.stringify(node.data.config, null, 2));
  const [textError, setTextError] = useState('');
  useEffect(() => { if (!raw) setText(JSON.stringify(node.data.config, null, 2)); }, [node.data.config, raw]);
  return <div className="flex flex-col gap-4">
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="m-0 truncate text-[15px] font-semibold">{node.id}</h2>
      <p className="m-0 mt-0.5 text-xs text-nv-muted">{spec.label} · {spec.family === 'general' ? 'general' : 'rotor'} block</p></div>
      <button type="button" aria-label="Close settings" className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-nv-muted hover:bg-nv-hover hover:text-nv-ink" onClick={onClose}><X size={15} aria-hidden="true" /></button></div>
    <div className="flex gap-2"><Button onClick={onDuplicate}>Duplicate</Button><Button variant="danger" onClick={onRemove}>Remove</Button></div>
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

function IntegrationField({ value, onChange }) {
  const { list, openSettings } = useContext(IntegrationsContext);
  if (!list.length) return <div className="flex flex-col gap-1.5 rounded-md border border-nv-warn/30 bg-nv-warn/10 p-2.5 text-[12.5px] text-nv-reference">
    OpenFAST is not set up on this computer.
    {openSettings && <div><Button onClick={openSettings}>Set up OpenFAST</Button></div>}</div>;
  return <label className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-2 text-[12.5px] text-nv-muted">executable
    <select aria-label="OpenFAST executable" className={fieldClass} value={value || ''} onChange={(e) => onChange(e.target.value)}>
      <option value="" className="bg-nv-panel">First configured</option>
      {list.map((i) => <option key={i.id} value={i.id} className="bg-nv-panel">{i.probe?.version ? `OpenFAST ${i.probe.version}` : 'OpenFAST'} · {String(i.executable).split('/').slice(-4).join('/')}</option>)}</select></label>;
}

function ConfigField({ name, value, onChange, catalog, rotors, path }) {
  const label = name.replaceAll('_', ' ');
  if (name === 'integration_id') return <IntegrationField value={value} onChange={onChange} />;
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
    {points.length > 1 && hi > lo && <LineChart title={`${y} vs ${x === 'tip_speed_ratio' ? 'λ' : x === 'advance_ratio' ? 'J' : x}`} series={[{ id: 'y', color: '#FF8533', points }]} height={170}
      xDomain={[lo, hi]} xTicks={ticks.length > 1 ? ticks : [lo, hi]} xLabel={x === 'tip_speed_ratio' ? 'λ' : x === 'advance_ratio' ? 'J' : ''} />}
    <details className="text-xs"><summary className="cursor-pointer text-nv-reference">Rows</summary><div className="mt-1 max-h-64 overflow-auto">
      <table className="w-full text-left tabular-nums"><thead className="text-nv-muted"><tr>{columns.map((c) => <th key={c} className="p-1 font-normal">{c}</th>)}</tr></thead>
        <tbody>{table.rows.map((r, i) => <tr key={i} className="border-t border-nv-line">{columns.map((c) => <td key={c} className="p-1 font-mono">{fmt(r[c])}</td>)}</tr>)}</tbody></table></div></details>
  </div>;
}
