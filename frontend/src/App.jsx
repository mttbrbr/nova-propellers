import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { api, apiFetch as fetch, download } from './backend.js';
import EngineeringWorkspace from './workspaces/EngineeringWorkspace.jsx';
import StudiesWorkspace from './workspaces/StudiesWorkspace.jsx';
import IntegrationsWorkspace from './workspaces/IntegrationsWorkspace.jsx';
import { RotorAnalysisStage, RotorGeometryStage, RotorResultsStage, RotorSizingStage, requirementDefaults } from './stages/RotorStages.jsx';
import BlockWorkflows from './workspaces/BlockWorkflows.jsx';
import { Segmented } from './ui/controls.jsx';
import { request as backendRequest } from './backend.js';
import useExecutionMonitor from './useExecutionMonitor.js';
import AppHeader, { stages } from './shell/AppHeader.jsx';
import WorkspaceRail from './shell/WorkspaceRail.jsx';
import StageLayout, { StageTitle } from './shell/StageLayout.jsx';
import SizingStage from './stages/SizingStage.jsx';
import GeometryStage from './stages/GeometryStage.jsx';
import AnalysisStage from './stages/AnalysisStage.jsx';
import ResultsStage from './stages/ResultsStage.jsx';
import LibraryWorkspace from './stages/LibraryWorkspace.jsx';
import { forgetProject } from './lib/preferences.js';

const initial = {
  project_name: 'New propeller', propeller_type: 'traditional', diameter_mode: 'manual',
  thrust_target: 10, disk_loading: 220, diameter: 0.25, rpm: 5000, blades: 2,
  airfoil: 'NACA 4412', geometry_method: 'bezier',
};
const bezierDefaults = (diameter) => ({
  chord_points: [
    { x: 0, y: diameter * .105 }, { x: .32, y: diameter * .115 },
    { x: .72, y: diameter * .065 }, { x: 1, y: diameter * .018 },
  ],
  twist_points: [{ x: 0, y: 34 }, { x: .33, y: 25 }, { x: .72, y: 14 }, { x: 1, y: 7 }],
});
const stageIds = stages.map((stage) => stage.id);
const geometryFields = ['propeller_type', 'diameter', 'blades', 'airfoil', 'geometry_method', 'geometry_parameters', 'airfoil_assignments'];
const geometryKeyOf = (source) => JSON.stringify(Object.fromEntries(geometryFields.map((key) => [key, source?.[key] ?? null])));
const activeRun = (record) => Boolean(record) && ['queued', 'running', 'cancelling'].includes(record.state);

// Key-order independent JSON, used to tell whether a rotor run matches the current inputs.
const sortedValue = (value) => Array.isArray(value) ? value.map(sortedValue) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortedValue(value[key])])) : value;
const stableJson = (value) => JSON.stringify(sortedValue(value ?? null));

async function post(endpoint, body) {
  const response = await fetch(api(endpoint), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(result.detail || `HTTP error ${response.status}`);
  }
  return response;
}

function App() {
  const [phase, setPhase] = useState('sizing');
  const [lastStage, setLastStage] = useState('sizing');
  const [inputs, setInputs] = useState(initial);
  const [bezier, setBezier] = useState(bezierDefaults(initial.diameter));
  const [laguerre, setLaguerre] = useState({
    chord_coefficients: [.02625, .0195, -.01125, -.0045],
    twist_coefficients: [34, 25, -8, 1],
  });
  const [airfoils, setAirfoils] = useState(['NACA 4412']);
  const [coordinateAirfoils, setCoordinateAirfoils] = useState([]);
  const [useAirfoilLoft, setUseAirfoilLoft] = useState(false);
  const [bezierProfileAssignments, setBezierProfileAssignments] = useState(['', '', '', '']);
  const [laguerreProfileAssignments, setLaguerreProfileAssignments] = useState([
    { radial_fraction: 0, airfoil: '' },
    { radial_fraction: 1, airfoil: '' },
  ]);
  const [loftPreview, setLoftPreview] = useState(null);
  const [computationalMethods, setComputationalMethods] = useState([]);
  const [sizing, setSizing] = useState(null);
  const [model, setModel] = useState('bemt');
  const [designMode, setDesignMode] = useState('direct');
  const [inverseSolver, setInverseSolver] = useState('bemt');
  const [inverseResult, setInverseResult] = useState(null);
  // Live preview of the editable geometry (Geometry and Analysis stages).
  const [canonical, setCanonical] = useState(null);
  const [mesh, setMesh] = useState(null);
  const [stlUrl, setStlUrl] = useState('');
  const [geometryStamp, setGeometryStamp] = useState('');
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const previewSequence = useRef(0);
  // The execution currently shown in Results; frozen with its own geometry.
  const [analyses, setAnalyses] = useState([]);
  const [resultGeometry, setResultGeometry] = useState(null);
  const [resultMesh, setResultMesh] = useState(null);
  const [resultStlUrl, setResultStlUrl] = useState('');
  const [resultContext, setResultContext] = useState(null);
  const [resultStamp, setResultStamp] = useState('');
  const [reportModel, setReportModel] = useState('');
  const resultViewGeneration = useRef(0);
  const [station, setStationValue] = useState(0.7);
  const [selectedPoint, setSelectedPoint] = useState({ curve: 'chord', index: 1 });
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [libraryTab, setLibraryTab] = useState('projects');
  const [studyRequest, setStudyRequest] = useState(null);
  const [compareModels, setCompareModels] = useState([]);
  const [selectedAirfoil, setSelectedAirfoil] = useState('NACA 4412');
  const [airfoilDetail, setAirfoilDetail] = useState(null);
  const [airfoilForm, setAirfoilForm] = useState({ name: '', family: 'custom', source: 'user', notes: '' });
  const [airfoilEdit, setAirfoilEdit] = useState({ family: '', source: '', notes: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savedId, setSavedId] = useState(null);
  const workbench = useRef(null);
  const [executionStamp, setExecutionStamp] = useState('');
  const [guidedCompatible, setGuidedCompatible] = useState(true);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [studyExecution, setStudyExecution] = useState(null);
  const [selectedStudyRun, setSelectedStudyRun] = useState(null);
  const [externalExecution, setExternalExecution] = useState(null);
  const [integrationDraft, setIntegrationDraft] = useState({});
  const [workspaceContext, setWorkspaceContext] = useState(null);
  const [slots, setSlots] = useState({});
  const [workflowMode, setWorkflowMode] = useState('project');
  // Rotor family of the open simulation. The air propeller uses the native
  // propeller pipeline; the other families use rotor-engine simulations whose
  // specification is edited in the same four Design stages.
  const [rotorFamily, setRotorFamily] = useState('propeller');
  const [rotorCatalog, setRotorCatalog] = useState(null);
  const [rotorSpecs, setRotorSpecs] = useState({});
  const [rotorRun, setRotorRun] = useState(null);
  const slotCallbacks = useRef({});
  // Stable callback refs: each named slot element is handed to the controller.
  const slotRef = useCallback((name) => {
    if (!slotCallbacks.current[name]) {
      slotCallbacks.current[name] = (element) => setSlots((current) => current[name] === element ? current : { ...current, [name]: element });
    }
    return slotCallbacks.current[name];
  }, []);
  const setStation = useCallback((value) => setStationValue(Math.min(1, Math.max(0, Number(value) || 0))), []);
  const trackExternalExecution = useCallback((record) => setExternalExecution((previous) => {
    if (!record || (activeRun(previous) && record.id !== previous.id)) return previous;
    return record;
  }), []);
  const trackStudyExecution = useCallback((record) => setStudyExecution((previous) => {
    if (!record || (activeRun(previous) && record.id !== previous.id)) return previous;
    return record;
  }), []);

  const payload = useMemo(() => ({
    project_name: inputs.project_name, propeller_type: inputs.propeller_type,
    thrust_target: inputs.thrust_target, rpm: inputs.rpm, diameter: inputs.diameter,
    blades: inputs.blades, airfoil: inputs.airfoil, geometry_method: inputs.geometry_method,
    geometry_parameters: inputs.geometry_method === 'bezier' ? bezier : laguerre,
    airfoil_assignments: useAirfoilLoft ? (inputs.geometry_method === 'bezier'
      ? bezier.chord_points.map((point, index) => ({ radial_fraction: point.x, airfoil: bezierProfileAssignments[index] || '' }))
      : laguerreProfileAssignments) : [],
  }), [inputs, bezier, laguerre, useAirfoilLoft, bezierProfileAssignments, laguerreProfileAssignments]);
  const geometryKey = geometryKeyOf(payload);
  const geometryCurrent = Boolean(canonical) && geometryStamp === geometryKey;
  const set = (key, value) => setInputs((current) => ({ ...current, [key]: value }));
  useEffect(() => { backendRequest('/v1/rotors/catalog').then(setRotorCatalog).catch(() => {}); }, []);
  const rotorSpec = rotorFamily === 'propeller' || !rotorCatalog ? null : rotorSpecs[rotorFamily]
    || { ...rotorCatalog.defaults[rotorFamily], requirements: { ...requirementDefaults[rotorFamily] } };
  const setRotorSpec = (spec) => setRotorSpecs((all) => ({ ...all, [rotorFamily]: spec }));
  const rotorStale = Boolean(rotorRun && rotorSpec && stableJson(rotorRun.inputs?.spec) !== stableJson(rotorSpec));
  const chooseFamily = (family) => { if (family !== rotorFamily) { setRotorFamily(family); setRotorRun(null); } };
  const openRotor = useCallback((spec) => {
    setRotorRun(null);
    if (!spec) { setRotorFamily('propeller'); return; }
    setRotorFamily(spec.kind); setRotorSpecs((all) => ({ ...all, [spec.kind]: spec }));
  }, []);
  const run = async (action) => {
    setBusy(true); setError('');
    try { await action(); } catch (caught) { setError(caught.message); } finally { setBusy(false); }
  };
  const refresh = () => fetch(api('/propellers')).then((r) => r.ok ? r.json() : []).then(setProjects).catch(() => {});
  const refreshAirfoils = () => fetch(api('/airfoils')).then((r) => r.json()).then((rows) => {
    setAirfoils(rows.map((row) => row.name));
    const available = rows.filter((row) => row.has_coordinates).map((row) => row.name);
    setCoordinateAirfoils(available);
    setBezierProfileAssignments((current) => bezier.chord_points.map((_, index) =>
      available.includes(current[index]) ? current[index] : available[Math.min(index, available.length - 1)] || ''
    ));
    setLaguerreProfileAssignments((current) => current.map((assignment, index) => ({
      ...assignment,
      airfoil: available.includes(assignment.airfoil) ? assignment.airfoil : available[Math.min(index, available.length - 1)] || '',
    })));
  });

  useEffect(() => {
    refreshAirfoils().catch(() => {});
    fetch(api('/computational-methods')).then((r) => r.json()).then(setComputationalMethods).catch(() => {});
    refresh();
    // Bootstrap once; later refreshes are triggered explicitly after database changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedAirfoil) return;
    fetch(api(`/airfoils/${encodeURIComponent(selectedAirfoil)}`)).then((response) => response.ok ? response.json() : null)
      .then((detail) => {
        setAirfoilDetail(detail);
        if (detail) setAirfoilEdit({ family: detail.family, source: detail.source, notes: detail.notes });
      }).catch(() => setAirfoilDetail(null));
  }, [selectedAirfoil]);

  const clearPreview = () => {
    previewSequence.current += 1;
    setMesh((current) => { current?.dispose(); return null; });
    setStlUrl((current) => { if (current) URL.revokeObjectURL(current); return ''; });
    setCanonical(null); setGeometryStamp(''); setPreviewError(''); setPreviewBusy(false);
  };
  const clearResult = () => {
    resultViewGeneration.current += 1;
    setAnalyses([]); setResultGeometry(null); setResultContext(null); setResultStamp('');
    setResultMesh((current) => { current?.dispose(); return null; });
    setResultStlUrl((current) => { if (current) URL.revokeObjectURL(current); return ''; });
  };

  // Regenerate the preview shortly after geometry edits; stale responses are dropped.
  const generatePreview = useCallback(async (body, key) => {
    const sequence = ++previewSequence.current;
    setPreviewBusy(true);
    try {
      const result = await (await post('/geometries', body)).json();
      const blob = await (await post('/geometries/stl', body)).blob();
      const parsed = new STLLoader().parse(await blob.arrayBuffer());
      if (sequence !== previewSequence.current) { parsed.dispose(); return; }
      setMesh((current) => { current?.dispose(); return parsed; });
      setStlUrl((current) => { if (current) URL.revokeObjectURL(current); return URL.createObjectURL(blob); });
      setCanonical(result.geometry); setGeometryStamp(key); setSavedId(null); setPreviewError('');
    } catch (caught) {
      if (sequence === previewSequence.current) setPreviewError(caught.message);
    } finally {
      if (sequence === previewSequence.current) setPreviewBusy(false);
    }
  }, []);
  useEffect(() => {
    if (!['geometry', 'analysis'].includes(phase) || geometryStamp === geometryKey) return undefined;
    const timer = window.setTimeout(() => generatePreview(payload, geometryKey), geometryStamp ? 350 : 0);
    return () => window.clearTimeout(timer);
    // The geometry key captures every field that changes the generated blade.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, geometryKey, geometryStamp]);

  const estimate = () => run(async () => {
    const result = await (await post('/sizing/actuator-disk', {
      thrust_target: inputs.thrust_target, disk_loading: inputs.disk_loading,
    })).json();
    setSizing(result); set('diameter', result.diameter_m); setBezier(bezierDefaults(result.diameter_m));
  });

  const optimizeGeometry = () => run(async () => {
    const result = await workbench.current.optimize(inverseSolver, inverseSolver === 'vlm' ? 100 : 180);
    setInverseResult(result);
  });
  const applyInverseResult = () => {
    if (!inverseResult) return;
    setBezier(inverseResult.geometry_parameters);
    set('geometry_method', 'bezier');
    setInverseResult(null);
  };

  const setBezierPointCount = (curve, requestedCount) => {
    const count = Math.max(2, Math.min(10, Number(requestedCount) || 2));
    const key = `${curve}_points`;
    const previous = bezier[key];
    if (count === previous.length) return;
    const sample = (x) => {
      const right = previous.findIndex((point) => point.x >= x);
      if (right <= 0) return previous[0].y;
      const left = right - 1;
      const weight = (x - previous[left].x) / Math.max(previous[right].x - previous[left].x, 1e-9);
      return previous[left].y * (1 - weight) + previous[right].y * weight;
    };
    const points = Array.from({ length: count }, (_, index) => {
      const x = index / (count - 1);
      return { x, y: sample(x) };
    });
    setBezier({ ...bezier, [key]: points });
    if (curve === 'chord') {
      setBezierProfileAssignments(points.map((point) => {
        const nearest = previous.reduce(
          (best, candidate, index) => Math.abs(candidate.x - point.x) < best.distance ? { index, distance: Math.abs(candidate.x - point.x) } : best,
          { index: 0, distance: Infinity },
        );
        return bezierProfileAssignments[nearest.index] || coordinateAirfoils[0] || '';
      }));
    }
    setInverseResult(null);
  };

  const importDatFile = (file) => run(async () => {
    const content = await file.text();
    const name = file.name.replace(/\.dat$/i, '');
    const result = await (await post('/airfoils/import-dat', { name, content })).json();
    await refreshAirfoils();
    setSelectedAirfoil(result.airfoil.name);
    setLibraryTab('airfoils');
  });

  const previewLoft = () => run(async () => {
    const assignments = inputs.geometry_method === 'bezier'
      ? bezier.chord_points.map((point, index) => ({ radial_fraction: point.x, airfoil: bezierProfileAssignments[index] || '' }))
      : laguerreProfileAssignments;
    const result = await (await post('/airfoils/loft', { assignments, radial_fraction: 0.5, method: 'linear' })).json();
    setLoftPreview(result.coordinates);
  });

  const addLaguerreProfileStation = () => {
    if (laguerreProfileAssignments.length >= 10) return;
    const sorted = [...laguerreProfileAssignments].sort((a, b) => a.radial_fraction - b.radial_fraction);
    const gaps = sorted.slice(0, -1).map((item, index) => sorted[index + 1].radial_fraction - item.radial_fraction);
    const index = gaps.indexOf(Math.max(...gaps));
    const radial_fraction = (sorted[index].radial_fraction + sorted[index + 1].radial_fraction) / 2;
    setLaguerreProfileAssignments([...sorted, { radial_fraction, airfoil: sorted[index].airfoil || coordinateAirfoils[0] || '' }]
      .sort((a, b) => a.radial_fraction - b.radial_fraction));
    setLoftPreview(null);
  };
  const updateLaguerreProfileStation = (index, patch) => {
    setLaguerreProfileAssignments((current) => current.map((assignment, itemIndex) => itemIndex === index ? { ...assignment, ...patch } : assignment)
      .sort((a, b) => a.radial_fraction - b.radial_fraction));
    setLoftPreview(null);
  };

  const receiveResult = async (result, snapshot, runId, stamp, caseIndex = null, runContext = null) => {
    const generation = ++resultViewGeneration.current;
    setResultContext({ runId, run: runContext, simulationName: runContext?.simulation_name || (caseIndex != null ? 'Parameter study' : 'Unassigned execution'),
      simulationRevision: runContext?.simulation_revision, models: [...new Set(result.analyses.map((a) => a.model))], rpm: snapshot.rpm, caseIndex, studyCase: runContext?.study_case });
    setResultStamp(stamp);
    setResultGeometry(result.geometry);
    setAnalyses(result.analyses); setReportModel(result.analyses[0]?.node_id || result.analyses[0]?.model || '');
    setSavedId(null);
    setResultMesh((current) => { current?.dispose(); return null; });
    setResultStlUrl((current) => { if (current) URL.revokeObjectURL(current); return ''; });
    if (!result.geometry) return;
    const response = await fetch(api(caseIndex == null ? `/v1/runs/${runId}/stl` : `/v1/runs/${runId}/cases/${caseIndex}/stl`));
    const blob = await response.blob();
    const buffer = await blob.arrayBuffer();
    if (generation !== resultViewGeneration.current) return;
    setResultMesh(new STLLoader().parse(buffer));
    setResultStlUrl(URL.createObjectURL(blob));
  };
  const openDraft = (stored) => {
    clearResult(); clearPreview();
    setDesignMode('direct'); setLoftPreview(null);
    setInputs((current) => ({ ...current, ...stored }));
    if (stored.geometry_method === 'bezier') setBezier(stored.geometry_parameters);
    if (stored.geometry_method === 'laguerre') setLaguerre(stored.geometry_parameters);
    setUseAirfoilLoft(Boolean(stored.airfoil_assignments?.length));
    if (stored.airfoil_assignments?.length) {
      setBezierProfileAssignments(stored.airfoil_assignments.map((a) => a.airfoil));
      setLaguerreProfileAssignments(stored.airfoil_assignments);
    }
    setSizing(null); setInverseResult(null); setSelectedProject(null); setSavedId(null);
  };

  const save = () => run(async () => {
    const result = await (await post('/projects', {
      project_name: inputs.project_name, inputs: payload, geometry: canonical, analyses,
    })).json();
    setSavedId(result.id); refresh();
  });

  const open = (id) => run(async () => {
    const detail = await (await fetch(api(`/propellers/${id}`))).json();
    workbench.current?.reset();
    setSizing(null); setInverseResult(null); setDesignMode('direct'); clearPreview();
    const stored = detail.payload;
    setInputs((current) => ({ ...current, ...stored, project_name: detail.project_name }));
    if (stored.geometry_method === 'bezier') setBezier(stored.geometry_parameters);
    if (stored.geometry_method === 'laguerre') setLaguerre(stored.geometry_parameters);
    if (stored.airfoil_assignments?.length) {
      setUseAirfoilLoft(true);
      if (stored.geometry_method === 'bezier') {
        const sorted = [...stored.airfoil_assignments].sort((a, b) => a.radial_fraction - b.radial_fraction);
        setBezierProfileAssignments(sorted.map((assignment) => assignment.airfoil));
      } else {
        setLaguerreProfileAssignments(stored.airfoil_assignments);
      }
    } else {
      setUseAirfoilLoft(false);
    }
    setSavedId(id); setSelectedProject(detail);
  });

  const remove = async (id) => { await fetch(api(`/propellers/${id}`), { method: 'DELETE' }); refresh(); };
  const createAirfoil = () => run(async () => {
    const response = await post('/airfoils', {
      name: airfoilForm.name, family: airfoilForm.family, source: airfoilForm.source,
      notes: airfoilForm.notes, camber: 0, thickness: 0.12,
    });
    const detail = await response.json();
    setAirfoils((current) => [...new Set([...current, detail.name])].sort());
    setSelectedAirfoil(detail.name); setAirfoilForm({ name: '', family: 'custom', source: 'user', notes: '' });
  });
  const updateAirfoil = () => run(async () => {
    const response = await fetch(api(`/airfoils/${encodeURIComponent(selectedAirfoil)}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: selectedAirfoil, ...airfoilEdit, camber: airfoilDetail.camber, thickness: airfoilDetail.thickness }),
    });
    if (!response.ok) throw new Error('Airfoil update failed');
    const updated = await response.json();
    setAirfoilDetail((current) => ({ ...current, ...updated }));
  });
  const deleteAirfoil = () => run(async () => {
    const response = await fetch(api(`/airfoils/${encodeURIComponent(selectedAirfoil)}`), { method: 'DELETE' });
    if (!response.ok) throw new Error('Airfoil deletion failed');
    const remaining = airfoils.filter((name) => name !== selectedAirfoil);
    setAirfoils(remaining); setSelectedAirfoil(remaining[0] || ''); setAirfoilDetail(null);
    await refreshAirfoils();
  });

  const workspace = stageIds.includes(phase) ? 'design' : phase;
  const go = (target) => {
    let id = target === 'design' ? lastStage : target;
    if (!guidedCompatible && ['sizing', 'geometry', 'analysis'].includes(id)) id = 'workflow';
    if (stageIds.includes(id)) setLastStage(id);
    setPhase(id);
  };
  const chooseModel = (value) => { setModel(value); workbench.current?.setModel(value); };
  const resetProject = async () => {
    if (!await workbench.current?.guard()) return;
    workbench.current?.reset();
    openDraft({ ...initial, geometry_parameters: bezierDefaults(initial.diameter), airfoil_assignments: [] });
    setModel('bemt'); setGuidedCompatible(true); setLastStage('sizing'); setPhase('sizing');
  };

  useExecutionMonitor(studyExecution, setStudyExecution, setError);
  useExecutionMonitor(externalExecution, setExternalExecution, setError);

  const nativeRun = activeRun(studyExecution) ? studyExecution : activeRun(externalExecution) ? externalExecution : workspaceContext?.activeRun;
  const runActive = activeRun(nativeRun);
  const runDisabled = busy || Boolean(workspaceContext?.busy) || !workspaceContext?.ready;
  const defaultSimulation = (geometryDefinition) => openDraft({ ...initial, project_name: inputs.project_name, ...(geometryDefinition || Object.fromEntries(geometryFields.map((key) => [key, payload[key]]))) });
  const handleRun = () => {
    if (runActive || runDisabled) return;
    run(async () => {
      await workbench.current.execute();
      // "Also compare with" runs the same frozen simulation with the extra solvers afterwards.
      const extra = guidedCompatible ? compareModels.filter((id) => id !== model) : [];
      if (extra.length) trackStudyExecution(await workbench.current.solverComparison([model, ...extra]));
    });
  };
  const openSavedProject = (id, simulationId = null) => { workbench.current?.openProjectById(id, simulationId); go('design'); };
  const compareProjects = (ids) => { setStudyRequest({ type: 'design', projectIds: ids, nonce: Date.now() }); go('studies'); };
  const deleteProjects = async (ids) => {
    for (const id of ids) {
      await fetch(api(`/v2/projects/${id}`), { method: 'DELETE' });
      forgetProject(id);
    }
    if (ids.includes(workbench.current?.projectId())) {
      workbench.current.reset();
      openDraft({ ...initial, geometry_parameters: bezierDefaults(initial.diameter), airfoil_assignments: [] });
      setModel('bemt'); setGuidedCompatible(true);
    }
    await workbench.current?.refresh();
  };
  const handleCancel = () => run(() => nativeRun.study || nativeRun.comparison || nativeRun.external_job
    ? fetch(api(`/v1/runs/${nativeRun.id}/cancel`), { method: 'POST' }) : workbench.current.cancel());
  const handleSave = () => { if (!runDisabled) workbench.current?.save(); };

  // Keyboard shortcuts; handlers are read through a ref so the listener is installed once.
  const shortcuts = useRef({});
  useEffect(() => { shortcuts.current = { handleRun, handleSave, go, phase, setStation, station }; });
  useEffect(() => {
    const onKey = (event) => {
      const actions = shortcuts.current;
      const typing = event.target.closest?.('input, select, textarea, [role="slider"]');
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); actions.handleRun(); }
      else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); actions.handleSave(); }
      else if (event.altKey && ['1', '2', '3', '4'].includes(event.key)) { event.preventDefault(); actions.go(stageIds[Number(event.key) - 1]); }
      else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'p') { event.preventDefault(); window.dispatchEvent(new Event('nova:open-project-picker')); }
      else if (!typing && ['ArrowLeft', 'ArrowRight'].includes(event.key) && ['geometry', 'results'].includes(actions.phase)) {
        event.preventDefault();
        actions.setStation(Math.round((actions.station + (event.key === 'ArrowRight' ? 0.05 : -0.05)) * 100) / 100);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  // Opening Results without a loaded run shows the latest run of the simulation.
  const latestRun = workspaceContext?.lastRun;
  useEffect(() => {
    if (phase !== 'results' || !latestRun) return;
    if (rotorFamily === 'propeller' ? !analyses.length : !rotorRun) workbench.current?.openRun(latestRun);
  }, [phase, analyses.length, latestRun, rotorFamily, rotorRun]);

  const completed = rotorFamily !== 'propeller' ? { sizing: true, geometry: true, analysis: Boolean(rotorRun && !rotorStale) } : {
    sizing: Number(inputs.diameter) > 0,
    geometry: geometryCurrent && !previewError,
    analysis: Boolean(workspaceContext?.lastRun && !workspaceContext?.lastRunStale),
  };
  const exportResultStl = () => {
    if (!resultStlUrl) return;
    const link = document.createElement('a'); link.href = resultStlUrl; link.download = 'nova_result_geometry.stl'; link.click();
  };

  let body;
  const rotorStage = rotorFamily !== 'propeller' && stageIds.includes(phase);
  if (rotorStage && !rotorSpec) body = <div className="grid flex-1 place-items-center text-[13px] text-nv-muted">Loading rotor models…</div>;
  else if (rotorStage && phase === 'sizing') body = <RotorSizingStage family={rotorFamily} onFamily={chooseFamily} spec={rotorSpec} setSpec={setRotorSpec} catalog={rotorCatalog}
    projectName={inputs.project_name} onProjectName={(v) => set('project_name', v)} onContinue={() => go('geometry')} />;
  else if (rotorStage && phase === 'geometry') body = <RotorGeometryStage family={rotorFamily} spec={rotorSpec} setSpec={setRotorSpec} catalog={rotorCatalog} onContinue={() => go('analysis')} />;
  else if (rotorStage && phase === 'analysis') body = <RotorAnalysisStage family={rotorFamily} spec={rotorSpec} setSpec={setRotorSpec} catalog={rotorCatalog} onRun={handleRun} runDisabled={runDisabled || runActive} />;
  else if (rotorStage && phase === 'results') body = <RotorResultsStage family={rotorFamily} run={rotorRun} stale={rotorStale}
    runs={(workspaceContext?.simulationRuns || []).filter((r) => r.simulation_kind === 'rotor')} onRun={handleRun} runDisabled={runDisabled || runActive} onNavigate={go} />;
  else if (phase === 'sizing') body = <SizingStage inputs={inputs} set={set} sizing={sizing} onEstimate={estimate} busy={busy} onContinue={() => go('geometry')}
    family={rotorFamily} onFamily={chooseFamily} />;
  else if (phase === 'geometry') body = <GeometryStage g={{
    inputs, set, airfoils, coordinateAirfoils, bezier, setBezier, laguerre, setLaguerre, designMode, setDesignMode, setBezierPointCount,
    useAirfoilLoft, setUseAirfoilLoft, bezierProfileAssignments, setBezierProfileAssignments, laguerreProfileAssignments, updateLaguerreProfileStation,
    removeLaguerreStation: (index) => setLaguerreProfileAssignments((current) => current.filter((_, itemIndex) => itemIndex !== index)),
    addLaguerreProfileStation, previewLoft, loftPreview, setLoftPreview, inverseSolver, setInverseSolver, inverseResult, optimize: optimizeGeometry,
    applyInverse: applyInverseResult, clearInverse: () => setInverseResult(null), methods: computationalMethods, busy, slotRef,
    preview: { canonical, mesh, busy: previewBusy, error: previewError, stlUrl }, published: workspaceContext?.geometry, station, setStation, selectedPoint, setSelectedPoint,
  }} />;
  else if (phase === 'analysis') body = <AnalysisStage a={{
    // Guided workflows have a single analysis node driven by the local model state.
    inputs, set, model, chooseModel, methods: computationalMethods, context: workspaceContext, slotRef, station,
    preview: { canonical, mesh, busy: previewBusy }, openRun: (record) => workbench.current?.openRun(record), onRun: handleRun, runDisabled: runDisabled || runActive,
    onCompare: () => { setStudyRequest({ type: 'solver', nonce: Date.now() }); go('studies'); }, compareModels, setCompareModels,
  }} />;
  else if (phase === 'results') body = <ResultsStage r={{
    analyses, context: workspaceContext, resultContext, station, setStation, reportModel, setReportModel, resultGeometry, resultMesh, previewMesh: mesh, resultStlUrl,
    openRun: (record) => workbench.current?.openRun(record), exportCsv: (id) => run(() => download(`/v1/runs/${id}/results.csv`, 'performance.csv')), exportStl: exportResultStl,
    onRun: handleRun, runDisabled: runDisabled || runActive, onNavigate: go, projectName: inputs.project_name,
  }} />;
  else if (phase === 'workflow' && workflowMode === 'blocks') body = <BlockWorkflows />;
  else if (phase === 'workflow') body = <StageLayout inputsLabel="Workflow inputs" contentLabel="Workflow" flush
    inputs={<>
      <StageTitle title="Workflow" detail="Inspect, customize and execute the project graph." />
      <div ref={slotRef('graphSide')} className="flex flex-col gap-2.5" />
      <section aria-label="Airfoil and air data" className="flex flex-col gap-2.5"><div ref={slotRef('data')} className="flex flex-col gap-2.5" /></section>
      <div ref={slotRef('explorer')} />
    </>}
    content={<section ref={slotRef('graph')} aria-label="Workflow editor" className="min-h-[600px] min-w-0 flex-1 xl:h-full xl:min-h-0" />} />;
  else if (phase === 'studies') body = <StudiesWorkspace projectId={activeProjectId} projectControls={workbench} methods={computationalMethods} studyRequest={studyRequest}
    onOpenSource={(record) => { workbench.current?.openProjectById(record.project_id, record.simulation_id); go('analysis'); }}
    configurationBusy={busy || workspaceContext?.busy || !workspaceContext?.ready} selectedRun={selectedStudyRun} activeStudy={studyExecution} onExecutionChange={trackStudyExecution}
    onInverseDesign={() => { setDesignMode('inverse'); go('geometry'); }}
    onInspect={(result, snapshot, runId, index, runContext) => { receiveResult(result, snapshot, runId, `study:${runId}:${index}`, index, runContext).catch((e) => setError(e.message)); go('results'); }} />;
  else if (phase === 'integrations') body = <div className="min-h-0 flex-1 overflow-auto"><IntegrationsWorkspace activeExecution={externalExecution} onExecutionChange={trackExternalExecution} draft={integrationDraft} onDraftChange={setIntegrationDraft} /></div>;
  else body = <LibraryWorkspace l={{
    tab: libraryTab, setTab: setLibraryTab, methods: computationalMethods,
    currentProjectId: activeProjectId, openProject: openSavedProject, compareProjects, deleteProjects, newProject: resetProject,
    exportProject: (row) => run(() => download(`/v2/projects/${row.id}/archive`, `${row.name}.nova`)),
    importProject: (file) => workbench.current?.importArchive(file),
    configure: (id) => { if (guidedCompatible) chooseModel(id); go('analysis'); },
    airfoils, selectedAirfoil, setSelectedAirfoil, airfoilDetail, airfoilForm, setAirfoilForm, airfoilEdit, setAirfoilEdit,
    importDat: importDatFile, createAirfoil, updateAirfoil, deleteAirfoil, busy,
    projects, selectedProject, open, remove, save, savedId, geometryCurrent,
    downloadStl: (item) => run(() => download(`/propellers/${item.id}/stl`, `${item.project_name}.stl`)),
  }} />;

  return <div className="flex min-h-screen flex-col bg-nv-canvas text-nv-ink xl:h-screen xl:overflow-hidden">
    <AppHeader context={workspaceContext} projectSlot={slotRef('projectSelector')} simulationSlot={slotRef('simulationSelector')} manageSlot={slotRef('manage')} menuSlot={slotRef('menu')}
      phase={phase} onNavigate={go} guidedCompatible={guidedCompatible} completed={completed}
      onSave={handleSave} saveDisabled={runDisabled} run={runActive ? nativeRun : null} onRun={handleRun} onCancel={handleCancel} runDisabled={runDisabled}
      onNewProject={resetProject} onCloseProject={resetProject} projectActionsDisabled={busy || Boolean(workspaceContext?.busy)} />
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <WorkspaceRail workspace={workspace} onSelect={go} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {workspace === 'workflow' && <div className="flex items-center gap-3 border-b border-nv-line px-6 py-2"><span className="text-xs text-nv-muted">Workflow type</span>
          <div className="w-[300px]"><Segmented label="Workflow type" size="sm" value={workflowMode} onChange={setWorkflowMode}
            options={[['project', 'Project graph'], ['blocks', 'Block workflows']]} /></div></div>}
        {!guidedCompatible && workspace === 'workflow' && workflowMode === 'project' && <p className="m-0 border-b border-nv-line px-6 py-2 text-xs text-nv-muted">Customized graph: the guided stages are not available for this project. Continue here in Workflow.</p>}
        {phase === 'results' && analyses.length > 0 && resultStamp && executionStamp && resultStamp !== executionStamp && !resultStamp.startsWith('study:') &&
          <p className="m-0 border-b border-nv-warn/30 bg-nv-warn/10 px-6 py-2 text-xs text-nv-warn-ink">These results belong to an earlier configuration; the current inputs have changed since this run.</p>}
        {body}
      </div>
    </div>
    <EngineeringWorkspace ref={workbench} inputs={payload} model={model}
      onResult={receiveResult} onOpen={openDraft} onProjectChange={setActiveProjectId} onConfigChange={setExecutionStamp} onCompatibility={setGuidedCompatible} onAdvanced={() => setPhase('workflow')}
      onNewDraft={defaultSimulation} onContextChange={setWorkspaceContext} onLoadedModel={setModel} onShowResults={() => go('results')}
      onShowStudies={(record) => { setSelectedStudyRun(record || null); go('studies'); }} onBrowseProjects={() => { setLibraryTab('projects'); go('library'); }} uiBusy={busy} slots={slots}
      rotorFamily={rotorFamily} rotorSpec={rotorSpec} onRotorOpen={openRotor} onRotorResult={(record) => { setRotorRun(record); go('results'); }} />
    <div className="pointer-events-none fixed bottom-4 left-4 z-50 flex w-[min(440px,calc(100vw-32px))] flex-col gap-2 md:left-[72px]">
      <div ref={slotRef('notices')} className="pointer-events-auto flex flex-col gap-2" />
      {error && <div role="alert" className="pointer-events-auto flex items-start gap-3 rounded-lg border border-nv-err/40 bg-nv-panel px-3.5 py-2.5 text-[13px] text-nv-err-ink shadow-xl shadow-black/40">
        <span className="flex-1">{error}</span><button type="button" aria-label="Dismiss error" className="text-nv-muted hover:text-nv-ink" onClick={() => setError('')}>×</button></div>}
    </div>
  </div>;
}

export default App;
