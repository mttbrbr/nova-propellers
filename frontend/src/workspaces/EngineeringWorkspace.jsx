import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Background, Controls, Handle, Position, ReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { download, fileBase64, request as backendRequest, waitForExecution } from '../backend.js';
import SimulationCaseEditor from '../components/SimulationCaseEditor.jsx';
import { OpenFastResult, PyWakeResult } from './IntegrationsWorkspace.jsx';
import ProjectExplorer from '../components/ProjectExplorer.jsx';
import ProjectPicker from '../components/ProjectPicker.jsx';
import { rememberProject } from '../lib/preferences.js';

// Preserve the native editor shape while using multidisciplinary persistence.
const request = async (path, payload) => {
  let target = path;
  if (/^\/v1\/projects(?:$|\/import$|\/[^/]+\/(?:simulations|archive)$)/.test(path) || /^\/v1\/simulations(?:$|\/[^/]+\/(?:run|clone)$)/.test(path)) target = path.replace('/v1/', '/v2/');
  if (path === '/v1/projects' && payload) payload = { name: payload.name, id: payload.id, expected_revision: payload.expected_revision };
  if (path === '/v1/simulations' && payload && !payload.kind) {
    const { name, id, expected_revision, project_id, ...configuration } = payload;
    payload = { name, id, expected_revision, project_id, kind: 'propeller', configuration };
  }
  const result = await backendRequest(target, payload);
  const unpack = (item) => item?.kind === 'propeller' && item.configuration ? { ...item, ...item.configuration } : item;
  return Array.isArray(result) ? result.map(unpack) : unpack(result);
};
const externalDefaults = (kind) => kind === 'pywake' ? { demonstration: true, notes: 'Synthetic demonstration turbine', case: {
  turbine: { name: 'Demonstration turbine', diameter_m: 100, hub_height_m: 100, wind_speed_m_s: [3,8,12,25], power_w: [0,1000000,3000000,3000000], ct: [.8,.8,.7,.1] },
  layout: { x_m: [0,500], y_m: [0,0] }, wind: { directions_deg: [270], speeds_m_s: [8,12], probabilities: [[.5,.5]], turbulence_intensity: .1 }, wake_model: 'noj', timeout_seconds: 300,
} } : { case: { case_directory: '', input_file: '', output_file: '', timeout_seconds: 300 } };

const button = 'inline-flex min-h-[34px] items-center justify-center rounded-[7px] border border-nv-edge px-3 text-[13px] text-nv-ink hover:bg-nv-hover disabled:cursor-not-allowed disabled:opacity-40';
const field = 'h-[34px] w-full min-w-0 rounded-md border border-nv-edge bg-nv-chrome px-2.5 text-[13px] text-nv-ink focus:border-nv-accent focus:outline-none disabled:opacity-50';
const menuItem = 'flex h-[34px] w-full items-center rounded-md px-2.5 text-left text-[13px] text-nv-ink hover:bg-nv-active disabled:cursor-not-allowed disabled:opacity-40';
const running = (run) => ['queued', 'running', 'cancelling'].includes(run?.state);
const ordered = (value) => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, ordered(value[key])])) : value;
const stable = (value) => JSON.stringify(ordered(value));
const modelNames = (graph) => [...new Set((graph?.nodes || []).filter((n) => n.type === 'analysis').map((n) => n.config?.model || 'bemt'))];
const inputLabels = [['diameter', 'diameter'], ['blades', 'blade count'], ['rpm', 'rotation speed'], ['airfoil', 'airfoil'], ['propeller_type', 'propeller type'],
  ['geometry_method', 'geometry method'], ['geometry_parameters', 'blade shape'], ['airfoil_assignments', 'airfoil loft']];
// Human-readable reasons why a stored run no longer matches the editable configuration.
const changedFields = (run, current) => {
  const changed = inputLabels.filter(([key]) => stable(run.inputs?.[key] ?? null) !== stable(current.inputs?.[key] ?? null)).map(([, label]) => label);
  if (stable(modelNames(run.workflow)) !== stable(modelNames(current.workflow))) changed.push('solver');
  if (stable(run.conditions) !== stable(current.conditions)) changed.push('air properties');
  if ((run.polar_asset_id || '') !== (current.polar_asset_id || '')) changed.push('airfoil data');
  return changed.length ? changed : ['workflow'];
};
// Results are stale only when physics inputs change; renaming the project does not invalidate them.
const runSignature = (draftInputs, graph, settings, polarId) => stable({ inputs: Object.fromEntries(Object.entries(draftInputs || {}).filter(([key]) => key !== 'project_name')),
  workflow: graph, conditions: settings, assetId: polarId || '' });
const newestFirst = (a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''));

function Operation({ data }) {
  const input = ['sizing', 'geometry'].includes(data.type) ? 'design'
    : data.type === 'analysis' ? 'geometry' : 'result';
  const output = ['parameters', 'sizing'].includes(data.type) ? 'design'
    : data.type === 'geometry' ? 'geometry' : 'result';
  return <div className="rounded-lg border border-nv-edge-strong bg-nv-raised px-4 py-3 text-nv-ink">
    {data.type !== 'parameters' && <Handle type="target" position={Position.Left} id={input} />}
    <div className="text-[13px]">{data.id}</div><div className="mt-1 text-xs text-nv-muted">{data.type}{data.model ? ` · ${data.model}` : ''}</div>
    <Handle type="source" position={Position.Right} id={output} />
  </div>;
}
const nodeTypes = { operation: Operation };

// The controller stays mounted for the whole session; its controls are rendered
// into the slots of whichever workspace is visible (header, Geometry, Analysis,
// Workflow), so switching workspaces never resets project or run state.
const EngineeringWorkspace = forwardRef(function EngineeringWorkspace({ inputs, model, onOpen, onResult, onAdvanced, onConfigChange, onCompatibility, onProjectChange, onContextChange, onLoadedModel, onShowResults, onShowStudies, onNewDraft, onBrowseProjects, uiBusy = false, slots = {}, rotorFamily = 'propeller', rotorSpec = null, onRotorOpen, onRotorResult }, ref) {
  const activation = useRef(0);
  const [workflow, setWorkflow] = useState(null);
  const [project, setProject] = useState(null);
  const [projects, setProjects] = useState([]);
  const [assets, setAssets] = useState([]);
  const [assetId, setAssetId] = useState('');
  const [conditions, setConditions] = useState({ air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 });
  const [activeRun, setActiveRun] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [preview, setPreview] = useState(null);
  const [reynolds, setReynolds] = useState(100000);
  const [selected, setSelected] = useState('analysis');
  const [validation, setValidation] = useState(null);
  const [busy, setBusy] = useState(false);
  const [simulations, setSimulations] = useState([]);
  const [simulation, setSimulation] = useState(null);
  const [simulationName, setSimulationName] = useState('Simulation 1');
  const savedDraft = useRef(null);
  const baselinePending = useRef(false);
  const [baselineVersion, setBaselineVersion] = useState(0);
  const [savingConfiguration, setSavingConfiguration] = useState(false);
  const [guard, setGuard] = useState(null);
  const [guardSaving, setGuardSaving] = useState(false);
  const draftBaseline = useRef(null);
  const [geometries, setGeometries] = useState([]);
  const [geometry, setGeometry] = useState(null);
  const [geometryName, setGeometryName] = useState('Propeller geometry');
  const [adoption, setAdoption] = useState([]);
  const [kind, setKind] = useState('propeller');
  const [externalText, setExternalText] = useState('{}');
  const [integrationId, setIntegrationId] = useState('');
  const [integrations, setIntegrations] = useState([]);
  // Rotor-family simulations (HAWT, VAWT, marine) are typed project simulations whose
  // specification is edited in the Design stages; external kinds use case editors.
  const rotor = kind === 'rotor';
  const external = kind !== 'propeller' && !rotor;
  const familyRef = useRef(rotorFamily);
  familyRef.current = rotorFamily;
  const rotorStamp = rotor ? stable(rotorSpec) : '';
  useEffect(() => { backendRequest('/v1/integrations').then(setIntegrations).catch(() => {}); }, []);
  // Choosing another rotor family starts a new simulation draft in the same project;
  // a saved simulation never changes family.
  useEffect(() => {
    const wanted = rotorFamily === 'propeller' ? 'propeller' : 'rotor';
    const savedFamily = simulation ? (simulation.kind === 'rotor' ? simulation.configuration?.spec?.kind : simulation.kind || 'propeller') : null;
    if (kind === wanted && (!simulation || savedFamily === rotorFamily || (wanted === 'propeller' && kind !== 'rotor'))) return;
    if (kind !== 'propeller' && kind !== 'rotor' && rotorFamily === 'propeller') return;
    if (simulation) {
      setSimulation(null); setSimulationName(`Simulation ${simulations.length + 1}`); setActiveRun(null);
      setMessage('Rotor type changed: started a new simulation draft; saved simulations are unchanged');
    }
    savedDraft.current = null; baselinePending.current = true; setKind(wanted);
    // Only the family drives this transition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rotorFamily]);

  const refresh = async () => {
    const epoch = activation.current;
    const [p, a, r] = await Promise.all([request('/v1/projects'), request('/v1/assets'), request('/v1/runs')]);
    setProjects(p); setAssets(a); setHistory(r);
    if (project?.id) {
      const [list, geometryList] = await Promise.all([request(`/v1/projects/${project.id}/simulations`), request(`/v1/projects/${project.id}/geometries`)]);
      if (epoch === activation.current) { setSimulations(list); setGeometries(geometryList); }
    }
  };
  useEffect(() => {
    request('/v1/workflow-template').then(setWorkflow).catch((e) => setError(e.message));
    Promise.all([request('/v1/projects'), request('/v1/assets'), request('/v1/runs')])
      .then(([p, a, r]) => { setProjects(p); setAssets(a); setHistory(r); }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => { onProjectChange?.(project?.id || null); }, [project, onProjectChange]);
  // Confirmations fade on their own; errors stay until dismissed.
  useEffect(() => {
    if (!message) return undefined;
    const timer = window.setTimeout(() => setMessage(''), 8000);
    return () => window.clearTimeout(timer);
  }, [message]);
  const configuredWorkflow = () => {
    if (!workflow) throw new Error('Workflow is still loading');
    return workflow.template ? { ...workflow, nodes: workflow.nodes.map((n) => n.id === 'analysis'
      ? { ...n, config: { ...n.config, model } } : n) } : workflow;
  };
  const signature = (draftInputs, graph, settings, polarId) => stable({ inputs: draftInputs, workflow: graph, conditions: settings, assetId: polarId || '' });
  const currentGraph = workflow ? configuredWorkflow() : null;
  const configurationStamp = signature(inputs, currentGraph, conditions, assetId);
  const runStamp = runSignature(inputs, currentGraph, conditions, assetId);
  const geometryReference = (value) => ({ id: value?.geometry_id || null, revision: value?.geometry_revision || null });
  const draftStamp = stable({ configuration: rotor ? rotorStamp : external ? externalText : configurationStamp, kind, name: simulationName.trim(), geometry: geometryReference(geometry) });
  const draftDirty = !simulation && !baselinePending.current && draftBaseline.current !== null && draftBaseline.current !== draftStamp;
  const simulationDirty = Boolean(simulation) && !baselinePending.current && savedDraft.current !== draftStamp;
  useEffect(() => {
    if (draftBaseline.current === null && workflow) draftBaseline.current = draftStamp;
    if (baselinePending.current && workflow) {
      draftBaseline.current = draftStamp;
      savedDraft.current = draftStamp; baselinePending.current = false;
      setBaselineVersion((v) => v + 1);
    }
  }, [draftStamp, simulation, workflow]);
  const projectRunsForContext = history.filter((r) => r.project_id === project?.id);
  const simulationRuns = simulation ? projectRunsForContext.filter((r) => r.simulation_id === simulation.id && !r.study && !r.comparison && !r.optimization && !r.external_job).sort(newestFirst) : [];
  const lastRun = simulationRuns.find((r) => r.state === 'succeeded' && r.result) || null;
  const lastRunStale = Boolean(lastRun && workflow && runSignature(lastRun.inputs, lastRun.workflow, lastRun.conditions, lastRun.polar_asset_id) !== runStamp);
  const changedSinceRun = lastRunStale ? changedFields(lastRun, { inputs, workflow: currentGraph, conditions, polar_asset_id: assetId }) : [];
  useEffect(() => {
    onContextChange?.({ kind, project, projectNameModified: Boolean(project && inputs.project_name !== project.name), simulation, simulationName, simulationStatus: simulation ? (simulationDirty ? 'modified' : 'saved') : 'unsaved',
      models: rotor ? [{ single_streamtube: 'sst', double_streamtube: 'ds', multiple_streamtube: 'mst', double_multiple_streamtube: 'dmst' }[rotorSpec?.method] || rotorSpec?.method || 'bemt'] : external ? [kind] : modelNames(currentGraph), activeRun, dirty: simulationDirty || draftDirty, ready: Boolean(workflow), busy: busy || uiBusy || savingConfiguration || running(activeRun), error,
      geometry, selectedAsset: assets.find((a) => a.id === assetId) || null, conditions, projectRuns: projectRunsForContext, simulationRuns, lastRun, lastRunStale, changedSinceRun });
    // Derived strings track configuration values, not parent object identities.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, simulation, simulationName, kind, externalText, rotorStamp, configurationStamp, simulationDirty, draftDirty, baselineVersion, busy, uiBusy, savingConfiguration, activeRun, error, onContextChange, geometry, assets, assetId, history]);
  useEffect(() => {
    if (workflow) onConfigChange?.(runSignature(inputs, workflow.template ? { ...workflow, nodes: workflow.nodes.map((n) => n.id === 'analysis' ? { ...n, config: { ...n.config, model } } : n) } : workflow, conditions, assetId));
  }, [inputs, workflow, conditions, assetId, model, onConfigChange]);
  useEffect(() => {
    if (!workflow) return undefined;
    let valid = true; setValidation(null);
    const timer = window.setTimeout(() => {
      request('/v1/workflows/validate', currentGraph).then((value) => { if (valid) { setValidation(value); onCompatibility?.(value.guided_compatible); } }).catch((e) => { if (valid) { setValidation({ valid: false, error: e.message }); onCompatibility?.(false); } });
    }, 150);
    return () => { valid = false; window.clearTimeout(timer); };
      // Scientific graph values are tracked by the stable configuration signature.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configurationStamp, onCompatibility]);
  const body = () => ({ name: inputs.project_name || 'Untitled project', inputs,
    workflow: configuredWorkflow(), polar_asset_id: assetId || null, conditions,
    geometry_id: geometry?.geometry_id || null, geometry_revision: geometry?.geometry_revision || null,
    id: project?.id || null, expected_revision: project?.revision || null });
  const saveProject = async () => {
    const epoch = activation.current;
    const projectBody = project ? { id: project.id, expected_revision: project.revision, name: inputs.project_name || 'Untitled project', inputs: project.inputs, workflow: project.workflow, conditions: project.conditions, polar_asset_id: project.polar_asset_id, geometry_id: project.geometry_id, geometry_revision: project.geometry_revision } : body();
    const saved = await request('/v1/projects', projectBody);
    if (epoch !== activation.current) throw new Error('Project changed while saving; the saved project remains in the library');
    setProject(saved); rememberProject(saved.id); await refresh(); setMessage(`Saved revision ${saved.revision}`);
    return saved;
  };
  const saveSimulation = async (projectOverride = null) => {
    if (simulation && !simulationDirty) return simulation;
    const epoch = activation.current;
    setSavingConfiguration(true);
    try {
    const snapshot = body();
    const name = simulationName.trim();
    if (!name) throw new Error('Give this simulation a name');
    const savedProject = projectOverride || project || await saveProject();
    if (rotor) {
      if (!rotorSpec) throw new Error('Rotor specification is still loading');
      const saved = await request('/v1/simulations', { project_id: savedProject.id, name, kind: 'rotor', configuration: { spec: rotorSpec },
        id: simulation?.id || null, expected_revision: simulation?.revision || null });
      if (epoch !== activation.current) throw new Error('Project changed while saving; the configuration remains in the library');
      baselinePending.current = true; setSimulation(saved);
      setSimulations(await request(`/v1/projects/${savedProject.id}/simulations`));
      setMessage(`Saved ${rotorSpec.kind.toUpperCase()} simulation · revision ${saved.revision}`); return saved;
    }
    if (external) {
      const configuration = JSON.parse(externalText);
      const saved = await request('/v1/simulations', { project_id: savedProject.id, name, kind, configuration, id: simulation?.id || null, expected_revision: simulation?.revision || null });
      if (epoch !== activation.current) throw new Error('Project changed while saving; the configuration remains in the library');
      setExternalText(JSON.stringify(saved.configuration, null, 2)); baselinePending.current = true; setSimulation(saved);
      setSimulations(await request(`/v1/projects/${savedProject.id}/simulations`));
      setMessage(`Saved ${kind} simulation · revision ${saved.revision}`); return saved;
    }
    const published = await publishSnapshotGeometry(savedProject, snapshot);
    const saved = await request('/v1/simulations', { ...snapshot, name, project_id: savedProject.id,
      id: simulation?.id || null, expected_revision: simulation?.revision || null });
    if (epoch !== activation.current) throw new Error('Project or simulation changed while saving; the saved configuration remains in the library');
    savedDraft.current = stable({ configuration: signature(snapshot.inputs, snapshot.workflow, snapshot.conditions, snapshot.polar_asset_id), kind: 'propeller', name, geometry: geometryReference(saved) });
    baselinePending.current = false;
    setSimulation(saved);
    const geometryList = await request(`/v1/projects/${savedProject.id}/geometries`);
    if (epoch !== activation.current) throw new Error('Project changed while loading saved geometry');
    setGeometries(geometryList); setGeometry(geometryList.find((g) => g.geometry_id === saved.geometry_id && g.geometry_revision === saved.geometry_revision) || null);
    const list = await request(`/v1/projects/${savedProject.id}/simulations`);
    if (epoch === activation.current) setSimulations(list);
    setMessage(`Saved simulation ${name} · revision ${saved.revision}${published ? ` · published geometry r${published.geometry_revision} for this simulation only` : ''}`);
    return saved;
    } finally { setSavingConfiguration(false); }
  };
  const saveAll = async () => {
    if (!simulationName.trim()) throw new Error('Give this simulation a name');
    const savedProject = !project || project.name !== inputs.project_name ? await saveProject() : project;
    await saveSimulation(savedProject);
    setMessage((previous) => previous || 'Project and current simulation saved');
  };
  // One saved simulation evaluated with several solvers; no extra simulations are created.
  const submitSolverComparison = async (models, simulationId = null) => {
    const target = simulationId && simulationId !== simulation?.id ? simulations.find((item) => item.id === simulationId) : await saveSimulation();
    if (!target) throw new Error('Select a saved simulation');
    return request(`/v1/simulations/${target.id}/solver-comparison`, { expected_revision: target.revision, models });
  };
  const openProjectById = async (id, simulationId = null) => {
    const saved = projects.find((item) => item.id === id) || await backendRequest(`/v2/projects/${id}`);
    await openProject(saved, false, simulationId);
  };
  const submitStudy = async (definition) => {
    const saved = await saveSimulation();
    return request(`/v1/simulations/${saved.id}/study`, { expected_revision: saved.revision, study: definition });
  };
  const monitoringError = (message) => (error) => setError((previous) => error ? message : previous === message ? '' : previous);
  const executeOptimization = async (solver, maxIterations) => {
    const saved = await saveSimulation();
    let run = await request(`/v1/simulations/${saved.id}/optimize`, { expected_revision: saved.revision, solver, max_iterations: maxIterations });
    setActiveRun(run);
    run = await waitForExecution(run, setActiveRun, monitoringError('Connection interrupted while monitoring optimization. Retrying; the submitted job is unchanged.'));
    await refresh();
    if (run.state !== 'succeeded') throw new Error(run.error || `Optimization ${run.state}`);
    return run.result.candidate;
  };
  const execute = async () => {
    setError('');
    const epoch = activation.current;
    const snapshot = body();
    if (rotor) {
      const saved = await saveSimulation();
      const run = await request(`/v1/simulations/${saved.id}/run`, { expected_revision: saved.revision });
      await refresh();
      if (run.state !== 'succeeded') throw new Error(run.error || `Run ${run.state}`);
      if (epoch === activation.current) { setActiveRun(run); onRotorResult?.(run); }
      return run.result;
    }
    if (!external && snapshot.workflow.nodes.some((n) => n.type === 'analysis' && n.config.model === 'bemt') && !assetId) {
      throw new Error('Select imported polars or explicitly select demonstration data first');
    }
    const saved = await saveSimulation();
    let run = await request(`/v1/simulations/${saved.id}/run`, { expected_revision: saved.revision, ...(external && integrationId ? { integration_id: integrationId } : {}) });
    if (epoch === activation.current) setActiveRun(run);
    run = await waitForExecution(run, (next) => { if (epoch === activation.current) setActiveRun(next); }, monitoringError('Connection interrupted while monitoring the run. Retrying; the submitted job is unchanged.'));
    await refresh();
    if (run.state !== 'succeeded') throw new Error(run.error || `Run ${run.state}`);
    if (epoch !== activation.current || external) return run.result;
    await onResult?.(run.result, snapshot.inputs, run.id, runSignature(snapshot.inputs, snapshot.workflow, snapshot.conditions, snapshot.polar_asset_id), undefined, run);
    return run.result;
  };
  useImperativeHandle(ref, () => ({ execute, openRun: (r) => act(() => openExecution(r)), openProjectById: (id, simulationId) => act(() => openProjectById(id, simulationId)),
    solverComparison: submitSolverComparison, projectId: () => project?.id || null,
    importArchive: (file) => act(() => importArchive(file)), optimize: executeOptimization, study: submitStudy, snapshot: body, refresh, save: () => act(saveAll), guard: protectDraft, cancel: () => request(`/v1/runs/${activeRun.id}/cancel`, {}),
    setModel: (value) => setWorkflow((w) => w && !w.template ? { ...w, nodes: w.nodes.map((n) => n.type === 'analysis' ? { ...n, config: { ...n.config, model: value } } : n) } : w),
    reset: () => {
    const epoch = ++activation.current;
    setKind(familyRef.current !== 'propeller' ? 'rotor' : 'propeller'); setWorkflow(null); setProject(null); setActiveRun(null); setAssetId(''); setPreview(null); setValidation(null);
    setSimulation(null); setSimulations([]); setSimulationName('Simulation 1'); savedDraft.current = null; draftBaseline.current = null; baselinePending.current = true;
    setGeometry(null); setGeometries([]); setAdoption([]);
    setConditions({ air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 });
    request('/v1/workflow-template').then((value) => { if (epoch === activation.current) setWorkflow(value); }).catch((e) => { if (epoch === activation.current) setError(e.message); });
  } }));
  const act = async (action) => {
    setBusy(true); setError(''); setMessage('');
    try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const protectDraft = () => simulationDirty || draftDirty
    ? new Promise((resolve) => setGuard({ resolve })) : Promise.resolve(true);
  const decide = async (choice) => {
    if (guardSaving) return;
    if (choice === 'save') { setGuardSaving(true); try { await saveAll(); } catch (e) { setError(e.message); return; } finally { setGuardSaving(false); } }
    const decision = guard; setGuard(null); decision.resolve(choice !== 'cancel');
  };
  const importArchive = async (file) => {
    if (!await protectDraft()) return;
    const imported = await request('/v1/projects/import', { content_base64: await fileBase64(file) });
    await refresh(); await openProject(imported, true);
  };
  const geometryFields = ['propeller_type', 'diameter', 'blades', 'airfoil', 'geometry_method', 'geometry_parameters', 'airfoil_assignments'];
  const publishSnapshotGeometry = async (savedProject, snapshot) => {
    if (!geometry || stable(geometry.definition) === stable(Object.fromEntries(geometryFields.map((key) => [key, snapshot.inputs[key]])))) return null;
    const revisions = await request(`/v1/projects/${savedProject.id}/geometries`);
    const family = revisions.filter((g) => g.geometry_id === geometry.geometry_id);
    const published = await request(`/v1/projects/${savedProject.id}/geometries`, { name: geometryName || geometry.name, inputs: snapshot.inputs,
      geometry_id: geometry.geometry_id, expected_geometry_revision: Math.max(...family.map((g) => g.geometry_revision)) });
    snapshot.geometry_id = published.geometry_id; snapshot.geometry_revision = published.geometry_revision;
    return published;
  };
  const matchingGeometry = (list, source) => list.find((g) => g.geometry_id === source.geometry_id && g.geometry_revision === source.geometry_revision) || null;
  const chooseGeometry = async (id) => {
    const chosenGeometry = geometries.find((g) => g.id === id);
    if (!chosenGeometry) return;
    const editedGeometry = geometry && stable(geometry.definition) !== stable(Object.fromEntries(geometryFields.map((key) => [key, inputs[key]])));
    if (editedGeometry && !await protectDraft()) return;
    setGeometry(chosenGeometry); setGeometryName(chosenGeometry.name); onOpen({ ...inputs, ...chosenGeometry.definition });
  };
  const publishGeometry = async () => {
    const savedProject = project || await saveProject();
    const family = geometries.filter((g) => g.geometry_id === geometry?.geometry_id);
    const published = await request(`/v1/projects/${savedProject.id}/geometries`, { name: geometryName || 'Propeller geometry', inputs,
      ...(geometry ? { geometry_id: geometry.geometry_id, expected_geometry_revision: Math.max(...family.map((g) => g.geometry_revision)) } : {}) });
    setGeometries(await request(`/v1/projects/${savedProject.id}/geometries`)); setGeometry(published); setAdoption([]);
    setMessage(`Published geometry r${published.geometry_revision}. Choose which saved simulations should adopt it.`);
  };
  const adoptGeometry = async () => {
    const before = body();
    const adopted = await request(`/v1/projects/${project.id}/geometries/${geometry.geometry_id}/adopt`, { geometry_revision: geometry.geometry_revision,
      simulations: simulations.filter((item) => adoption.includes(item.id)).map((item) => ({ id: item.id, expected_revision: item.revision })) });
    const list = await request(`/v1/projects/${project.id}/simulations`); setSimulations(list); setAdoption([]);
    const active = adopted.simulations.find((item) => item.id === simulation?.id);
    if (active) {
      savedDraft.current = stable({ configuration: signature(active.inputs, active.workflow, active.conditions, active.polar_asset_id), kind: 'propeller', name: active.name, geometry: geometryReference(active) });
      baselinePending.current = false; setSimulation(active); setGeometry(adopted.geometry);
      onOpen({ ...before.inputs, ...adopted.geometry.definition });
    }
    setMessage('Selected simulations adopted this geometry revision. Historical executions remain unchanged.');
  };
  const openProject = async (saved, approved = false, preferredSimulationId = null) => {
    if (!approved && !await protectDraft()) return;
    const epoch = ++activation.current;
    const configurations = await request(`/v1/projects/${saved.id}/simulations`);
    rememberProject(saved.id);
    const preferred = configurations.find((item) => item.id === preferredSimulationId) || configurations[0];
    const selectedConfiguration = preferred || (saved.inputs ? saved : { inputs, workflow: await request('/v1/workflow-template'), conditions: { air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 } });
    if (epoch !== activation.current) return;
    if (selectedConfiguration.kind === 'rotor') {
      const geometryList = await request(`/v1/projects/${saved.id}/geometries`);
      if (epoch !== activation.current) return;
      setProject(saved); setSimulations(configurations); setGeometries(geometryList);
      setKind('rotor'); setSimulation(selectedConfiguration); setSimulationName(selectedConfiguration.name); setActiveRun(null);
      baselinePending.current = true; onOpen({ ...inputs, project_name: saved.name }); onRotorOpen?.(selectedConfiguration.configuration.spec); return;
    }
    if (selectedConfiguration.kind && selectedConfiguration.kind !== 'propeller') {
      const geometryList = await request(`/v1/projects/${saved.id}/geometries`);
      if (epoch !== activation.current) return;
      setProject(saved); setSimulations(configurations); setGeometries(geometryList);
      setKind(selectedConfiguration.kind); setExternalText(JSON.stringify(selectedConfiguration.configuration, null, 2));
      setSimulation(selectedConfiguration); setSimulationName(selectedConfiguration.name); setActiveRun(null);
      baselinePending.current = true; onOpen({ ...inputs, project_name: saved.name }); onAdvanced(); return;
    }
    setKind('propeller'); onRotorOpen?.(null);
    const checked = await request('/v1/workflows/validate', selectedConfiguration.workflow);
    if (epoch !== activation.current) return;
    const geometryList = await request(`/v1/projects/${saved.id}/geometries`);
    if (epoch !== activation.current) return;
    setGeometries(geometryList); setGeometry(matchingGeometry(geometryList, selectedConfiguration)); setAdoption([]);
    setProject(saved); setWorkflow(selectedConfiguration.workflow); setConditions(selectedConfiguration.conditions);
    setAssetId(selectedConfiguration.polar_asset_id || ''); setActiveRun(null); setPreview(null); setValidation(null);
    setSimulation(preferred || null); setSimulationName(preferred?.name || 'Simulation 1'); savedDraft.current = null;
    draftBaseline.current = null; baselinePending.current = true;
    setSimulations(configurations);
    onLoadedModel?.(modelNames(selectedConfiguration.workflow)[0] || 'bemt');
    onOpen({ ...selectedConfiguration.inputs, project_name: saved.name });
    if (!checked.guided_compatible) onAdvanced();
  };
  const openSimulation = async (saved) => {
    if (!await protectDraft()) return;
    if (!project || saved.project_id !== project.id) throw new Error('Simulation does not belong to the open project');
    const epoch = ++activation.current;
    if (saved.kind === 'rotor') {
      setKind('rotor'); setSimulation(saved); setSimulationName(saved.name); setActiveRun(null);
      baselinePending.current = true; onRotorOpen?.(saved.configuration.spec); return;
    }
    if (saved.kind && saved.kind !== 'propeller') {
      setKind(saved.kind); setExternalText(JSON.stringify(saved.configuration, null, 2));
      setSimulation(saved); setSimulationName(saved.name); setActiveRun(null); baselinePending.current = true; onAdvanced(); return;
    }
    setKind('propeller'); onRotorOpen?.(null);
    const checked = await request('/v1/workflows/validate', saved.workflow);
    if (epoch !== activation.current) return;
    baselinePending.current = true;
    setGeometry(matchingGeometry(geometries, saved)); setAdoption([]);
    setSimulation(saved); setSimulationName(saved.name); setWorkflow(saved.workflow); setConditions(saved.conditions);
    setAssetId(saved.polar_asset_id || ''); setActiveRun(null); setPreview(null); setValidation(null);
    onLoadedModel?.(modelNames(saved.workflow)[0] || 'bemt');
    onOpen({ ...saved.inputs, project_name: project.name });
    if (!checked.guided_compatible) onAdvanced();
  };
  const newSimulation = async (nextKind = 'propeller') => {
    if (!await protectDraft()) return;
    const epoch = ++activation.current;
    if (nextKind === 'propeller' && familyRef.current !== 'propeller') nextKind = 'rotor';
    setKind(nextKind); if (nextKind !== 'propeller' && nextKind !== 'rotor') { setExternalText(JSON.stringify(externalDefaults(nextKind), null, 2)); onAdvanced(); }
    const defaults = await request('/v1/workflow-template');
    if (epoch !== activation.current) return;
    setSimulation(null); setActiveRun(null); setValidation(null);
    setSimulationName(`Simulation ${simulations.length + 1}`); savedDraft.current = null; baselinePending.current = true;
    setWorkflow(defaults); setConditions({ air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 });
    setAssetId(''); setPreview(null); onLoadedModel?.('bemt'); onNewDraft?.(geometry?.definition);
  };
  const cloneSimulation = async () => {
    if (rotor) {
      const savedProject = project || await saveProject();
      const copy = await request('/v1/simulations', { project_id: savedProject.id, kind: 'rotor',
        name: (simulationName.trim() || 'Simulation').slice(0, 115) + ' copy', configuration: { spec: rotorSpec } });
      setSimulation(copy); setSimulationName(copy.name); baselinePending.current = true;
      setSimulations(await request(`/v1/projects/${savedProject.id}/simulations`));
      setMessage('Independent simulation copy created; the original configuration is unchanged'); return;
    }
    if (external) {
      const epoch = activation.current;
      const savedProject = project || await saveProject();
      const copy = await request('/v1/simulations', { project_id: savedProject.id, kind,
        name: (simulationName.trim() || 'Simulation').slice(0, 115) + ' copy', configuration: JSON.parse(externalText) });
      const list = await request(`/v1/projects/${savedProject.id}/simulations`);
      if (epoch !== activation.current) throw new Error('Project changed while copying; the copy remains in the library');
      setSimulation(copy); setSimulationName(copy.name); setExternalText(JSON.stringify(copy.configuration, null, 2));
      baselinePending.current = true; setSimulations(list);
      setMessage('Independent simulation copy created; the original configuration is unchanged'); return;
    }
    const epoch = activation.current;
    const savedProject = project || await saveProject();
    const snapshot = body();
    await publishSnapshotGeometry(savedProject, snapshot);
    const copied = await request('/v1/simulations', { ...snapshot, name: (simulationName.trim() || 'Simulation').slice(0, 115) + ' copy',
      project_id: savedProject.id, id: null, expected_revision: null });
    if (epoch !== activation.current) throw new Error('Project changed while copying; the copied configuration remains in the library');
    const [list, geometryList] = await Promise.all([request(`/v1/projects/${savedProject.id}/simulations`), request(`/v1/projects/${savedProject.id}/geometries`)]);
    if (epoch !== activation.current) throw new Error('Project changed while loading the copied configuration');
    baselinePending.current = true; setSimulation(copied); setSimulationName(copied.name);
    setSimulations(list); setGeometries(geometryList); setGeometry(matchingGeometry(geometryList, copied));
    setMessage('Independent simulation copy created');
  };
  const importFile = async (file) => {
    const content = await file.text();
    const document = { content, filename: file.name, airfoil: inputs.airfoil,
      format: file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'xfoil', reynolds: Number(reynolds) };
    const parsed = await request('/v1/assets/import-polar', document);
    setPreview({ document, parsed });
  };
  const editable = workflow && !workflow.template;
  const nodes = (workflow?.nodes || []).map((n, i) => ({ id: n.id, type: 'operation',
    position: n.position || { x: i * 190, y: 80 }, data: { id: n.id, type: n.type, model: workflow.template && n.id === 'analysis' ? model : n.config.model } }));
  const edges = (workflow?.edges || []).map((e, i) => ({ id: String(i), source: e.source, target: e.target,
    sourceHandle: e.source_port, targetHandle: e.target_port }));
  const chosen = workflow?.nodes.find((n) => n.id === selected);
  const updateConfig = (config) => setWorkflow((w) => ({ ...w, nodes: w.nodes.map((n) => n.id === selected ? { ...n, config } : n) }));
  const locked = busy || uiBusy || savingConfiguration || running(activeRun);
  const projectRuns = history.filter((r) => r.project_id === project?.id);
  const referencedAssets = new Set();
  const findReferences = (value) => {
    if (!value || typeof value !== 'object') return;
    for (const [key, item] of Object.entries(value)) {
      if (['asset_id', 'polar_asset_id'].includes(key) && typeof item === 'string') referencedAssets.add(item);
      else if (key === 'asset_ids' && Array.isArray(item)) item.forEach((id) => referencedAssets.add(id));
      else if (!['result', 'polar_asset', 'canonical_geometry'].includes(key)) findReferences(item);
    }
  };
  [project, ...simulations, ...geometries, ...projectRuns].forEach(findReferences);
  if (assetId) referencedAssets.add(assetId);
  const openExecution = async (r) => {
    if (r.simulation_kind === 'rotor') { if (r.state === 'succeeded') { onRotorResult?.(r); onShowResults?.(); } else setMessage(`${r.simulation_name} · ${r.state}${r.error ? ` · ${r.error}` : ''}`); return; }
    if (r.external_job) { setActiveRun(r); onAdvanced(); return; }
    if (r.study || r.comparison) { onShowStudies?.(r); return; }
    if (r.optimization) { setMessage('Optimization candidate and diagnostics are available in Studies / Inverse design.'); onShowStudies?.(); return; }
    if (!running(activeRun)) setActiveRun(r);
    if (r.result) { await onResult(r.result, r.inputs, r.id, runSignature(r.inputs, r.workflow, r.conditions, r.polar_asset_id), undefined, r); onShowResults?.(); }
    else setMessage(`${r.simulation_name || r.name} · ${r.state}${r.error ? ` · ${r.error}` : ''}`);
  };
  const portal = (name, content) => slots[name] ? createPortal(content, slots[name]) : null;
  const headerSelect = 'h-8 w-full min-w-0 max-w-[220px] cursor-pointer appearance-none truncate rounded-md bg-transparent px-2 text-[13px] hover:bg-nv-hover disabled:cursor-not-allowed disabled:opacity-50';
  const projectPicker = <ProjectPicker project={project} locked={locked} onOpen={(id, simulationId) => act(() => openProjectById(id, simulationId))} onBrowse={() => onBrowseProjects?.()} />;
  const simulationPicker = <select aria-label="Open saved simulation" className={`${headerSelect} text-nv-ink`} disabled={locked || !project} value={simulation?.id || ''} onChange={(e) => {
    const saved = simulations.find((s) => s.id === e.target.value); if (saved) act(() => openSimulation(saved));
  }}><option value="" disabled={Boolean(simulation)} className="bg-nv-panel">Draft: {simulationName}</option>{simulations.map((s) => <option key={s.id} value={s.id} className="bg-nv-panel">{s.name} · r{s.revision}</option>)}</select>;
  const geometryEdited = geometry && stable(geometry.definition) !== stable(Object.fromEntries(geometryFields.map((key) => [key, inputs[key]])));
  const selectedAsset = assets.find((a) => a.id === assetId);

  return <>
    {portal('projectSelector', projectPicker)}
    {portal('simulationSelector', simulationPicker)}
    {portal('manage', <>
      <label className="flex flex-col gap-1.5 text-[13px] text-nv-muted">Simulation name
        <input aria-label="Simulation name" maxLength={120} className={field} value={simulationName} disabled={locked} onChange={(e) => setSimulationName(e.target.value)} /></label>
      <p className="m-0 text-xs text-nv-muted">{simulation ? `Revision ${simulation.revision} · ${simulationDirty ? 'unsaved changes' : 'saved configuration'}` : 'New configuration · saved separately within the project'} · {(external ? [kind] : modelNames(currentGraph)).map((m) => m.toUpperCase()).join(' + ') || 'geometry only'}</p>
      <div className="grid grid-cols-2 gap-2">
        <button className={button} disabled={locked} onClick={() => act(() => newSimulation())}>New simulation</button>
        <button className={button} disabled={locked} onClick={() => act(cloneSimulation)}>Duplicate simulation</button>
        <button className={button} disabled={locked} onClick={() => act(() => newSimulation('pywake'))}>New PyWake simulation</button>
        <button className={button} disabled={locked} onClick={() => act(() => newSimulation('openfast'))}>New OpenFAST simulation</button>
      </div>
      <p className="m-0 text-xs leading-relaxed text-nv-muted">New keeps the selected geometry and resets analysis settings to defaults. Duplicate copies the current configuration, including unsaved edits.</p>
    </>)}
    {portal('menu', <>
      <span aria-hidden="true" className="mx-1.5 my-1 h-px bg-nv-edge" />
      <button className={menuItem} disabled={!project || locked} onClick={() => act(() => download(`/v2/projects/${project.id}/archive`, `${project.name}.nova`))}>Export saved project .nova</button>
      <label className={`${menuItem} cursor-pointer`}>Open .nova<input aria-label="Open .nova" type="file" accept=".nova" disabled={locked} className="hidden" onChange={(e) => { const file = e.target.files[0]; if (file) act(() => importArchive(file)); e.target.value = ''; }} /></label>
    </>)}
    {portal('explorer', <ProjectExplorer key={project?.id || 'draft'} project={project} simulations={simulations} geometries={geometries} assets={assets.filter((a) => referencedAssets.has(a.id))} runs={projectRuns}
      simulationId={simulation?.id} geometryId={geometry?.id} selectedPolar={assetId} locked={locked} onSimulation={(s) => act(() => openSimulation(s))} onGeometry={(id) => act(() => chooseGeometry(id))} onRun={(r) => act(() => openExecution(r))} onStudies={() => onShowStudies?.()}
      onUsePolar={(a) => { if (a.airfoil !== inputs.airfoil) setError('These polars belong to a different airfoil; select matching geometry first.'); else { setAssetId(a.id); setMessage(`Selected polars: ${a.filename}`); } }} />)}
    {guard && createPortal(<div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6"><div role="dialog" aria-modal="true" aria-labelledby="unsaved-title" className="max-w-md space-y-4 rounded-xl border border-nv-edge bg-nv-panel p-6">
      <h2 id="unsaved-title" className="m-0 text-lg">Unsaved simulation changes</h2><p className="text-[13px] text-nv-muted">Save the current draft, discard its changes, or keep editing.</p>
      <div className="flex flex-wrap gap-2"><button className={button} disabled={guardSaving} onClick={() => decide('save')}>Save changes</button><button className={button} disabled={guardSaving} onClick={() => decide('discard')}>Discard changes</button><button className={button} disabled={guardSaving} onClick={() => decide('cancel')}>Keep editing</button></div>
      {error && <p role="alert" className="text-xs text-nv-err-ink">{error}</p>}
    </div></div>, document.body)}
    {!external && !rotor && portal('revision', <>
      <label className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3 text-[13px] text-nv-muted">Revision
        <select aria-label="Geometry revision" className={field} value={geometry?.id || ''} disabled={locked || !project} onChange={(e) => act(() => chooseGeometry(e.target.value))}><option value="">Unpublished draft</option>{geometries.map((g) => <option key={g.id} value={g.id}>{g.name} · r{g.geometry_revision}</option>)}</select></label>
      {geometryEdited && <p className="m-0 text-xs leading-relaxed text-nv-warn-ink">Edits are not published yet. Save or Run publishes a revision for this simulation only; other simulations keep their geometry.</p>}
      <label className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3 text-[13px] text-nv-muted">Name<input aria-label="Geometry name" className={field} value={geometryName} onChange={(e) => setGeometryName(e.target.value)} /></label>
      <button className={button} disabled={locked} onClick={() => act(publishGeometry)}>Publish geometry revision</button>
      {geometry && simulations.length > 0 && <details className="text-[13px]"><summary className="cursor-pointer py-1 text-nv-reference">Apply revision to saved simulations</summary><div className="mt-2 flex flex-col gap-2">{simulations.filter((item) => !item.kind || item.kind === 'propeller').map((item) => <label key={item.id} className="flex items-center gap-2 text-[13px]"><input aria-label={`Adopt geometry for ${item.name}`} type="checkbox" className="accent-nv-accent" checked={adoption.includes(item.id)} onChange={(e) => { const checked = e.target.checked; setAdoption((ids) => checked ? [...new Set([...ids, item.id])] : ids.filter((id) => id !== item.id)); }} />{item.name} <span className="text-nv-muted">· now r{item.geometry_revision || '—'}</span></label>)}<button className={button} disabled={locked || !adoption.length} onClick={() => act(adoptGeometry)}>Apply to selected simulations</button></div></details>}
      <p className="m-0 text-xs leading-relaxed text-nv-muted">Publishing creates an immutable revision. Applying it changes only the selected simulations; earlier results keep their original geometry.</p>
    </>)}
    {!external && !rotor && portal('data', <>
      <label className="flex flex-col gap-1.5 text-[13px] text-nv-muted">Aerodynamic data<select className={field} value={assetId} onChange={(e) => setAssetId(e.target.value)}>
        <option value="">Select polar asset…</option>{assets.filter((a) => a.airfoil === inputs.airfoil).map((a) => <option key={a.id} value={a.id}>{a.filename}{a.demonstration ? ' — demonstration only' : ''}</option>)}</select></label>
      {selectedAsset?.demonstration && <p className="m-0 text-xs leading-relaxed text-nv-warn-ink">Demonstration data. Results are not physically meaningful.</p>}
      {!assetId && <p className="m-0 text-xs leading-relaxed text-nv-warn-ink">BEMT needs polars: import data or explicitly choose the demonstration set.</p>}
      <div className="grid grid-cols-1 gap-2">
        <label className={`${button} cursor-pointer text-center`}>Import polars<input type="file" accept=".csv,.txt,.pol,.dat" className="hidden" onChange={(e) => { const file = e.target.files[0]; if (file) act(() => importFile(file)); e.target.value = ''; }} /></label>
        <button className={button} onClick={() => act(async () => { const asset = await request('/v1/assets/demonstration-polar', { airfoil: inputs.airfoil });
          setAssetId(asset.id); await refresh(); })}>Use synthetic demonstration</button>
      </div>
      <label className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3 text-[13px] text-nv-muted">Default Re<input aria-label="Reynolds number if absent from file" className={`${field} font-mono`} type="number" value={reynolds} onChange={(e) => setReynolds(e.target.value)} /></label>
      <p className="m-0 text-xs leading-relaxed text-nv-muted">Used when the file has no Reynolds column. CSV headers: reynolds, alpha_deg, cl, cd; optional mach, ncrit, cm. XFOIL headers are read automatically. DAT coordinates are imported in Library.</p>
      {preview && <div className="rounded-lg border border-nv-edge p-3 text-[13px]"><div>{preview.parsed.points.length} points · Mach {preview.parsed.mach} · Ncrit {preview.parsed.ncrit}</div>
        <button className={`${button} mt-2`} onClick={() => act(async () => { const asset = await request('/v1/assets/import-polar', { ...preview.document, commit: true }); setAssetId(asset.id); setPreview(null); await refresh(); })}>Confirm import</button></div>}
      {[['air_density_kg_m3', 'Air density', 'kg/m³', 'Density [kg/m³]'], ['air_viscosity_pa_s', 'Viscosity', 'Pa·s', 'Viscosity [Pa·s]']].map(([key, label, unit, ariaLabel]) =>
        <label key={key} className="grid grid-cols-[104px_minmax(0,1fr)] items-center gap-3 text-[13px] text-nv-muted">{label}
          <span className="flex h-[34px] items-center gap-1.5 rounded-md border border-nv-edge bg-nv-chrome px-2.5 focus-within:border-nv-accent"><input aria-label={ariaLabel} type="number" step="any" className="h-8 min-w-0 flex-1 bg-transparent font-mono text-[13px] text-nv-ink outline-none" value={conditions[key]} onChange={(e) => setConditions((c) => ({ ...c, [key]: Number(e.target.value) }))} /><span className="text-xs">{unit}</span></span></label>)}
      <p className="m-0 text-xs leading-relaxed text-nv-muted">Static (hover) axial analysis. Coordinate lofting does not assign spanwise polars. Imported polars use disclosed endpoint clipping.</p>
    </>)}
    {portal('graphSide', <>
      {rotor && <p className="m-0 text-[13px] text-nv-muted">This {String(rotorSpec?.kind || '').toUpperCase()} simulation runs on the rotor engine. Build constrained chains of rotor blocks in Block workflows.</p>}
      {!external && !rotor && <>
        <h2 className="m-0 text-[13px] font-semibold">Selected block</h2>
        {chosen ? <p className="m-0 text-[13px] text-nv-muted">{chosen.id} · {chosen.type}</p> : <p className="m-0 text-[13px] text-nv-muted">Select a block to inspect its settings.</p>}
        {chosen?.type === 'analysis' && editable && <label className="flex flex-col gap-1.5 text-[13px] text-nv-muted">Solver<select className={field} aria-label="Node solver" value={chosen.config.model} onChange={(e) => updateConfig({ ...chosen.config, model: e.target.value })}>
          {['bemt', 'llt', 'vlm', 'bem'].map((id) => <option key={id}>{id}</option>)}</select></label>}
      </>}
      {external && <>
        <h2 className="m-0 text-[13px] font-semibold">{kind === 'pywake' ? 'Wind farm · PyWake' : 'Aeroelastic turbine · OpenFAST'}</h2>
        <label className="flex flex-col gap-1.5 text-[13px] text-nv-muted">Execution environment<select aria-label="Simulation execution environment" className={field} value={integrationId} onFocus={() => backendRequest('/v1/integrations').then(setIntegrations).catch((e) => setError(e.message))} onChange={(e) => setIntegrationId(e.target.value)}><option value="">Select configured environment…</option>{integrations.filter((i) => (i.adapter_id || i.adapter) === kind).map((i) => <option key={i.id} value={i.id}>{i.name || i.id}</option>)}</select></label>
        <p className="m-0 text-xs leading-relaxed text-nv-muted">Configure execution environments in Integrations. Save preserves this case in the project; Run saves changes before execution.</p>
      </>}
    </>)}
    {!external && !rotor && portal('graph', <div className="flex h-full min-h-[600px] min-w-0 flex-col lg:min-h-0">
      <div className="shrink-0 space-y-3 border-b border-nv-line px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="m-0 text-[15px] font-semibold">Execution graph</h2>
          <p className="m-0 mt-1 text-[13px] text-nv-muted">{editable ? 'Customized workflow · connect and configure blocks' : 'Default workflow · customize to edit'}</p></div>
        <div className="flex flex-wrap gap-2"><button className={button} disabled={locked || !workflow || editable} onClick={() => act(async () => { setWorkflow(await request('/v1/workflows/clone', configuredWorkflow())); setMessage('Independent workflow copy created'); })}>Customize workflow</button>
        <button className={button} onClick={() => act(async () => { const result = await request('/v1/workflows/validate', configuredWorkflow()); setValidation(result); })}>Validate</button>
        </div></div>
        {editable && <details className="relative"><summary className={`${button} inline-flex cursor-pointer`}>Add block</summary><div className="mt-2 flex flex-wrap gap-2">{['analysis', 'collect', 'export'].map((type) => <button key={type} className={button} disabled={locked} onClick={(e) => { setWorkflow((w) => ({ ...w, nodes: [...w.nodes, { id: `${type}-${crypto.randomUUID().slice(0, 8)}`, type, config: type === 'analysis' ? { model: 'bemt' } : {}, position: { x: 300, y: 250 } }] })); e.currentTarget.closest('details').open = false; }}>Add {type}</button>)}</div></details>}
        {!validation && <p className="m-0 text-[13px] text-nv-muted">Checking workflow…</p>}
        {validation && <details><summary className={`cursor-pointer text-[13px] ${validation.valid ? 'text-nv-ok-ink' : 'text-nv-warn-ink'}`}>{validation.valid ? `Valid · ${validation.guided_compatible ? 'Guided compatible' : 'Advanced workflow'}` : 'Workflow needs attention'}</summary><p className="mt-2 text-[13px] text-nv-muted">{validation.error || `Execution order: ${validation.order.join(' → ')}`}</p></details>}
      </div>
      <div aria-label="Workflow canvas" className="min-h-[440px] min-w-0 flex-1 bg-nv-canvas lg:min-h-0"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView colorMode="dark" minZoom={.15} maxZoom={2}
        deleteKeyCode={editable ? ['Backspace', 'Delete'] : null} nodesDraggable={Boolean(editable)} nodesConnectable={Boolean(editable)} edgesReconnectable={false}
        onNodeClick={(_, n) => setSelected(n.id)}
        onNodeDragStop={(_, node) => setWorkflow((w) => ({ ...w, nodes: w.nodes.map((n) => n.id === node.id ? { ...n, position: node.position } : n) }))}
        onConnect={(c) => setWorkflow((w) => ({ ...w, edges: [...w.edges, { source: c.source, source_port: c.sourceHandle, target: c.target, target_port: c.targetHandle }] }))}
        onEdgesDelete={(deleted) => editable && setWorkflow((w) => ({ ...w, edges: w.edges.filter((_, i) => !deleted.some((e) => e.id === String(i))) }))}
        onNodesDelete={(deleted) => editable && setWorkflow((w) => ({ ...w, nodes: w.nodes.filter((n) => !deleted.some((d) => d.id === n.id)), edges: w.edges.filter((e) => !deleted.some((d) => [e.source, e.target].includes(d.id))) }))}>
        <Background color="#1C2027" /><Controls /></ReactFlow></div>
    </div>)}
    {external && portal('graph', <section className="h-full space-y-4 overflow-auto p-6">
      <h2 className="m-0 text-lg">{simulationName} · {kind === 'pywake' ? 'PyWake wind farm' : 'OpenFAST turbine'}</h2>
      <p className="text-[13px] text-nv-muted">Edit the case configuration below. Distances use metres, wind speeds m/s, power W and angles degrees. OpenFAST source files are frozen when saved.</p>
      <SimulationCaseEditor kind={kind} text={externalText} onChange={setExternalText} disabled={locked} />
      {activeRun?.external_job && <div className="space-y-3"><h3>Execution · {activeRun.state}</h3>{activeRun.result?.data ? (activeRun.result.adapter_id === 'pywake' ? <PyWakeResult data={activeRun.result.data} /> : <OpenFastResult data={activeRun.result.data} />) : <pre className="overflow-auto text-xs">{JSON.stringify({ error: activeRun.error, logs: activeRun.logs }, null, 2)}</pre>}{activeRun.state === 'succeeded' && <button className={button} onClick={() => act(() => download(`/v1/external-runs/${activeRun.id}/csv`, `${simulationName}.csv`))}>Export results CSV</button>}</div>}
    </section>)}
    {activeRun && portal('run', <div className="flex flex-col gap-2 rounded-lg border border-nv-edge p-3.5 text-[13px]">
      <p className="m-0 text-nv-muted">{activeRun.simulation_name || 'Unassigned execution'} · {activeRun.optimization ? `optimization using ${activeRun.optimization.solver.toUpperCase()}` : modelNames(activeRun.workflow).map((m) => m.toUpperCase()).join(' + ')}</p>
      <div className="flex items-center gap-3"><span className="flex-1">{activeRun.state} · {Math.round(activeRun.progress * 100)}%</span>
        {activeRun.state === 'succeeded' && !activeRun.optimization && !activeRun.study && !activeRun.external_job && <button className={button} onClick={() => act(() => download(`/v1/runs/${activeRun.id}/results.csv`, 'performance.csv'))}>Export CSV</button>}</div>
      <div className="h-1 overflow-hidden rounded-full bg-nv-edge"><div className="h-full bg-nv-accent transition-all" style={{ width: `${Math.round(activeRun.progress * 100)}%` }} /></div>
      {activeRun.diagnostics && <p className="m-0 text-xs text-nv-muted">Residual: {activeRun.diagnostics.convergence?.residual}. Diagnostics retained in run history.</p>}
      <details><summary className="cursor-pointer text-xs text-nv-muted">Execution logs</summary><pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-[11px] text-nv-muted">{(activeRun.logs || []).join('\n')}</pre></details>
    </div>)}
    {portal('notices', <>
      {message && <div role="status" className="flex items-start gap-3 rounded-lg border border-nv-ok/30 bg-nv-panel px-3.5 py-2.5 text-[13px] text-nv-ok-ink shadow-xl shadow-black/40"><span className="flex-1">{message}</span><button type="button" aria-label="Dismiss message" className="text-nv-muted hover:text-nv-ink" onClick={() => setMessage('')}>×</button></div>}
      {error && <div role="alert" className="flex items-start gap-3 rounded-lg border border-nv-err/40 bg-nv-panel px-3.5 py-2.5 text-[13px] text-nv-err-ink shadow-xl shadow-black/40"><span className="flex-1">{error}</span><button type="button" aria-label="Dismiss error" className="text-nv-muted hover:text-nv-ink" onClick={() => setError('')}>×</button></div>}
    </>)}
  </>;
});
export default EngineeringWorkspace;
