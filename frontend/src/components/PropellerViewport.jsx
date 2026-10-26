import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Box, Check, Layers, Maximize } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import * as THREE from 'three';
import { formatValue, interpolate } from '../lib/blade.js';
import { IconButton, MenuItem, Popover } from '../ui/controls.jsx';

const views = {
  iso: { label: 'Isometric', position: [2.45, -2.8, 1.85], up: [0, 0, 1] },
  axis: { label: 'Along the axis', position: [0, 0, 4.1], up: [0, 1, 0] },
  side: { label: 'Side', position: [0, -4.1, 0.02], up: [0, 0, 1] },
};
const ramp = ['#1D3B52', '#2F7DA0', '#9BE3F7', '#EAF9FD'].map((hex) => new THREE.Color(hex));
export const rampGradient = 'linear-gradient(90deg, #1D3B52, #2F7DA0 40%, #9BE3F7 75%, #EAF9FD)';

function rampColor(t, target) {
  const scaled = Math.min(0.9999, Math.max(0, t)) * (ramp.length - 1);
  const index = Math.floor(scaled);
  return target.copy(ramp[index]).lerp(ramp[index + 1], scaled - index);
}

function SceneControls({ view, fitKey }) {
  const { camera, gl } = useThree();
  const controls = useRef(null);
  useEffect(() => {
    const preset = views[view] || views.iso;
    camera.up.set(...preset.up);
    camera.position.set(...preset.position);
    camera.lookAt(0, 0, 0);
    // OrbitControls reads camera.up when created, so each view gets fresh controls.
    const instance = new OrbitControls(camera, gl.domElement);
    instance.enableDamping = true;
    instance.dampingFactor = 0.08;
    instance.minDistance = 1.2;
    instance.maxDistance = 9;
    instance.target.set(0, 0, 0);
    instance.update();
    controls.current = instance;
    return () => instance.dispose();
  }, [camera, gl, view, fitKey]);
  useFrame(() => controls.current?.update());
  return null;
}

function Propeller({ geometry, displayMode, station, rootFraction, colorField }) {
  const prepared = useMemo(() => {
    const clone = geometry.clone();
    clone.computeBoundingBox();
    const box = clone.boundingBox;
    // Keep the rotation axis (z) on the origin; only centre along the axis.
    clone.translate(0, 0, -(box.min.z + box.max.z) / 2);
    const position = clone.attributes.position;
    const radii = new Float32Array(position.count);
    let tip = 1e-9;
    for (let index = 0; index < position.count; index += 1) {
      radii[index] = Math.hypot(position.getX(index), position.getY(index));
      tip = Math.max(tip, radii[index]);
    }
    clone.computeVertexNormals();
    return { geometry: clone, radii, tip, scale: 1.05 / tip };
  }, [geometry]);
  useEffect(() => () => prepared.geometry.dispose(), [prepared]);

  const root = prepared.tip * (rootFraction ?? 0.14);
  useEffect(() => {
    const target = prepared.geometry;
    if (!colorField?.points?.length) { target.deleteAttribute('color'); return; }
    const colors = new Float32Array(prepared.radii.length * 3);
    const color = new THREE.Color();
    const hub = new THREE.Color('#3A424E');
    const [low, high] = colorField.domain;
    prepared.radii.forEach((radius, index) => {
      if (radius < root * 0.97) hub.toArray(colors, index * 3);
      else {
        const span = Math.min(1, Math.max(0, (radius - root) / Math.max(prepared.tip - root, 1e-9)));
        rampColor((interpolate(colorField.points, span) - low) / Math.max(high - low, 1e-12), color).toArray(colors, index * 3);
      }
    });
    target.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  }, [prepared, colorField, root]);

  const ring = useMemo(() => {
    if (station == null) return null;
    const radius = root + station * (prepared.tip - root);
    const points = Array.from({ length: 129 }, (_, index) => {
      const angle = index / 128 * Math.PI * 2;
      return new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
    });
    return new THREE.BufferGeometry().setFromPoints(points);
  }, [station, root, prepared]);
  useEffect(() => () => ring?.dispose(), [ring]);

  const colored = Boolean(colorField?.points?.length);
  return <group scale={prepared.scale}>
    <mesh geometry={prepared.geometry}>
      <meshPhysicalMaterial key={`${colored}-${displayMode}`} vertexColors={colored} color={colored ? '#ffffff' : '#dfe3e8'}
        metalness={displayMode === 'mesh' ? 0 : colored ? 0.05 : 0.3} roughness={colored ? 0.55 : 0.3} clearcoat={displayMode === 'mesh' || colored ? 0 : 0.6}
        clearcoatRoughness={0.22} wireframe={displayMode === 'mesh'} side={THREE.DoubleSide} />
    </mesh>
    {ring && <lineLoop geometry={ring}><lineBasicMaterial color="#4CC9F0" /></lineLoop>}
  </group>;
}

function Scene({ geometry, displayMode, view, fitKey, station, rootFraction, colorField }) {
  return <Canvas camera={{ position: views.iso.position, fov: 34 }} dpr={[1, 2]}>
    <color attach="background" args={['#0A0C0F']} />
    <hemisphereLight args={['#ffffff', '#16181d', 1.4]} />
    <directionalLight position={[3, -4, 6]} intensity={3.6} color="#ffffff" />
    <directionalLight position={[-4, 2, 2]} intensity={1.8} color="#9fd9f2" />
    <gridHelper args={[4, 24, '#2A303A', '#1C2027']} rotation={[Math.PI / 2, 0, 0]} position={[0, 0, -0.45]} />
    {geometry && <Propeller geometry={geometry} displayMode={displayMode} station={station} rootFraction={rootFraction} colorField={colorField} />}
    <SceneControls view={view} fitKey={fitKey} />
  </Canvas>;
}

// Square render panel with a single vertical tool strip; every group opens on click.
export default function PropellerViewport({ geometry, station = null, rootFraction, colorField = null, emptyMessage = 'The preview appears once the geometry is valid.',
  busy = false, overlay = null, stationLabel = null, label = '3D preview of the propeller' }) {
  const [displayMode, setDisplayMode] = useState('surface');
  const [view, setView] = useState('iso');
  const [fitKey, setFitKey] = useState(0);
  useEffect(() => {
    const fit = (event) => {
      if (event.key.toLowerCase() !== 'f' || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.target.closest?.('input, select, textarea, [contenteditable="true"]')) return;
      setFitKey((key) => key + 1);
    };
    document.addEventListener('keydown', fit);
    return () => document.removeEventListener('keydown', fit);
  }, []);
  return <div className="relative aspect-square w-full overflow-hidden rounded-xl border border-nv-line bg-[#0A0C0F]">
    <div role="img" aria-label={label} className="absolute inset-0">
      <Scene geometry={geometry} displayMode={displayMode} view={view} fitKey={fitKey} station={station} rootFraction={rootFraction} colorField={colorField} />
    </div>
    {!geometry && <div className="pointer-events-none absolute inset-0 grid place-items-center p-8 text-center text-[13px] text-nv-muted">{emptyMessage}</div>}
    {busy && <span role="status" className="absolute bottom-3 right-3 rounded-md bg-nv-hover/90 px-2.5 py-1 text-xs text-nv-muted">Updating preview…</span>}
    {overlay && <div className="absolute left-3.5 top-3.5">{overlay}</div>}
    {stationLabel && geometry && <span className="absolute bottom-3.5 left-3.5 rounded-md border border-nv-accent bg-nv-hover/90 px-2 py-1 font-mono text-xs text-nv-ink-strong">{stationLabel}</span>}
    {colorField?.points?.length > 0 && <div className="absolute bottom-3.5 right-3.5 w-48 text-xs text-nv-muted" aria-label={`Color scale for ${colorField.label}`}>
      <div className="mb-1.5 text-nv-reference">{colorField.label}</div>
      <div className="h-2 rounded-full" style={{ background: rampGradient }} />
      <div className="mt-1 flex justify-between font-mono"><span>{formatValue(colorField.domain[0])}</span><span>{formatValue(colorField.domain[1])} {colorField.unit}</span></div>
    </div>}
    <div role="toolbar" aria-label="Viewport tools" aria-orientation="vertical" className="absolute right-3.5 top-3.5 flex flex-col gap-0.5 rounded-[10px] border border-nv-edge bg-nv-panel/95 p-1">
      <Popover label="Camera view" align="right" width="w-48" trigger={({ ref, open, toggle }) =>
        <IconButton ref={ref} label="Camera view" tooltipSide="left" icon={Box} active={open} aria-expanded={open} onClick={toggle} />}>
        {(close) => <div className="p-1.5">{Object.entries(views).map(([id, preset]) =>
          <MenuItem key={id} role="menuitemradio" aria-checked={view === id} onClick={() => { setView(id); close(); }}>{preset.label}{view === id && <Check size={15} className="text-nv-accent" aria-hidden="true" />}</MenuItem>)}</div>}
      </Popover>
      <Popover label="Display mode" align="right" width="w-44" trigger={({ ref, open, toggle }) =>
        <IconButton ref={ref} label="Display mode" tooltipSide="left" icon={Layers} active={open} aria-expanded={open} onClick={toggle} />}>
        {(close) => <div className="p-1.5">{[['surface', 'Surface'], ['mesh', 'Mesh']].map(([id, name]) =>
          <MenuItem key={id} role="menuitemradio" aria-checked={displayMode === id} onClick={() => { setDisplayMode(id); close(); }}>{name}{displayMode === id && <Check size={15} className="text-nv-accent" aria-hidden="true" />}</MenuItem>)}</div>}
      </Popover>
      <span aria-hidden="true" className="mx-1.5 my-0.5 h-px bg-nv-edge" />
      <IconButton label="Fit to view" shortcut="F" tooltipSide="left" icon={Maximize} onClick={() => setFitKey((key) => key + 1)} />
    </div>
  </div>;
}
