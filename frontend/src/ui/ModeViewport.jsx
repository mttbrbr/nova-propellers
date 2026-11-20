import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState } from 'react';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import * as THREE from 'three';

// Animated mode shape of a turbine (tower, nacelle, rotor) built from the layout of a modal result.
// A mode is a set of complex fields along the tower (fa, ss) and along every blade (flap, edge):
// displacement(t) = Re(field · e^{iφ}), φ advancing at a fixed visual rate (not the physical frequency).
// Scene axes: y up, z downwind (fore-aft, flap), x lateral (side-side). The rotor is frozen with blade 1 up.

const ramp = ['#3A1C0B', '#A84A12', '#FF9A52', '#FFE8D6'].map((hex) => new THREE.Color(hex));
const ghost = new THREE.Color('#3A424E');
const VISUAL_HZ = 0.6;

function rampColor(t, target) {
  const scaled = Math.min(0.9999, Math.max(0, t)) * (ramp.length - 1);
  const index = Math.floor(scaled);
  return target.copy(ramp[index]).lerp(ramp[index + 1], scaled - index);
}

const at = (pair, i, c, s) => pair ? pair[0][i] * c - (pair[1] ? pair[1][i] : 0) * s : 0;

export const views = {
  iso: { label: '3D', position: [3.1, 1.4, 4.0] },
  side: { label: 'Side', position: [5.2, 0.3, 0.001] },
  front: { label: 'Front', position: [0.001, 0.3, -5.2] },
};

function Controls({ view, target }) {
  const { camera, gl } = useThree();
  const controls = useRef(null);
  useEffect(() => {
    camera.up.set(0, 1, 0);
    camera.position.set(target[0] + views[view].position[0], target[1] + views[view].position[1], target[2] + views[view].position[2]);
    const instance = new OrbitControls(camera, gl.domElement);
    instance.enableDamping = true;
    instance.dampingFactor = 0.08;
    instance.minDistance = 0.8;
    instance.maxDistance = 12;
    instance.target.set(...target);
    instance.update();
    controls.current = instance;
    return () => instance.dispose();
  }, [camera, gl, view, target]);
  useFrame(() => controls.current?.update());
  return null;
}

// Geometry in scene units (the larger of total height and rotor diameter maps to 2).
function frame(layout) {
  const H = layout.tower_height_m || 0;
  const R = (layout.hub_radius_m || 0) + (layout.blade_length_m || 0);
  const shaft = layout.shaft_height_m || 0, overhang = layout.overhang_m || 0;
  const reference = Math.max(H + shaft + R, 2 * R, 1e-6);
  const k = 2 / reference;
  const hub = [0, (H + shaft) * k, H ? overhang * k : 0];
  return { k, H: H * k, hub, hubRadius: (layout.hub_radius_m || 0) * k, blade: (layout.blade_length_m || 0) * k, blades: layout.blades || 3,
    shaft: shaft * k, centre: [0, H ? (H + shaft) * k / 2 + (R * k) / 4 : 0, 0] };
}

function Tube({ points, magnitudes, radius, peak }) {
  const mesh = useRef(null);
  useEffect(() => () => mesh.current?.geometry.dispose(), []);
  useEffect(() => {
    if (!mesh.current || points.length < 2) return;
    const curve = new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p)));
    const segments = (points.length - 1) * 3;
    const geometry = new THREE.TubeGeometry(curve, segments, radius, 8, false);
    const colors = new Float32Array(geometry.attributes.position.count * 3);
    const color = new THREE.Color();
    for (let i = 0; i <= segments; i += 1) {
      const u = i / segments * (magnitudes.length - 1);
      const j = Math.min(Math.floor(u), magnitudes.length - 2);
      const m = magnitudes.length > 1 ? magnitudes[j] + (magnitudes[j + 1] - magnitudes[j]) * (u - j) : magnitudes[0] || 0;
      rampColor(0.15 + 0.85 * m / Math.max(peak, 1e-9), color);
      for (let r = 0; r <= 8; r += 1) color.toArray(colors, (i * 9 + r) * 3);
    }
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const old = mesh.current.geometry;
    mesh.current.geometry = geometry;
    old.dispose();
  });
  return <mesh ref={mesh}><bufferGeometry /><meshStandardMaterial vertexColors roughness={0.55} metalness={0.05} /></mesh>;
}

function GhostLine({ points }) {
  const geometry = useMemo(() => new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(...p))), [points]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <line geometry={geometry}><lineBasicMaterial color={ghost} transparent opacity={0.7} /></line>;
}

function Turbine({ layout, mode, amplitude, playing, phase }) {
  const f = useMemo(() => frame(layout), [layout]);
  const x = mode.x;
  const n = x.length;
  const scale = amplitude * 0.12 * 2;
  const [, setTick] = useState(0);
  // the geometry depends on the phase: advance it and re-render on every frame while playing
  useFrame((_, dt) => { if (playing) { phase.current += dt * 2 * Math.PI * VISUAL_HZ; setTick((t) => t + 1); } });
  const c = Math.cos(phase.current), s = Math.sin(phase.current);
  const parts = [];
  const ghosts = [];
  let top = [0, 0, 0], tilt = [0, 0];
  if (f.H) {
    const tower = mode.tower || {};
    const pts = [], mags = [];
    for (let i = 0; i < n; i += 1) {
      const fa = at(tower.fa, i, c, s) * scale, ss = at(tower.ss, i, c, s) * scale;
      pts.push([ss, x[i] * f.H, fa]);
      mags.push(Math.hypot(fa, ss));
    }
    top = pts[n - 1].slice();
    const dy = (x[n - 1] - x[n - 2]) * f.H || 1;
    tilt = [(pts[n - 1][2] - pts[n - 2][2]) / dy, (pts[n - 1][0] - pts[n - 2][0]) / dy];
    parts.push({ key: 'tower', points: pts, magnitudes: mags, radius: 0.028 });
    ghosts.push({ key: 'tower', points: x.map((v) => [0, v * f.H, 0]) });
  }
  const hub = [f.hub[0] + top[0] + tilt[1] * f.shaft, f.hub[1], f.hub[2] + top[2] + tilt[0] * f.shaft];
  if (f.blade) {
    for (let b = 0; b < f.blades; b += 1) {
      const psi = 2 * Math.PI * b / f.blades;
      const er = [Math.sin(psi), Math.cos(psi), 0], et = [Math.cos(psi), -Math.sin(psi), 0];
      const field = (mode.blades && (mode.blades[b] || mode.blades[0])) || {};
      const pts = [], mags = [], rest = [];
      for (let i = 0; i < n; i += 1) {
        const r = f.hubRadius + x[i] * f.blade;
        const flap = at(field.flap, i, c, s) * scale, edge = at(field.edge, i, c, s) * scale;
        // the whole rotor follows the tower-top rotation (fore-aft tilt, side-side roll)
        const p = [hub[0] + r * er[0] + edge * et[0], hub[1] + r * er[1] + edge * et[1], hub[2] + flap];
        p[2] += tilt[0] * (p[1] - hub[1]);
        p[0] += tilt[1] * (p[1] - hub[1]);
        pts.push(p);
        mags.push(Math.hypot(flap, edge) + Math.hypot(top[0], top[2]));
        rest.push([f.hub[0] + r * er[0], f.hub[1] + r * er[1], f.hub[2]]);
      }
      parts.push({ key: `blade${b}`, points: pts, magnitudes: mags, radius: 0.016 });
      ghosts.push({ key: `blade${b}`, points: rest });
    }
  }
  const peak = Math.max(scale, 1e-9);
  return <group>
    {ghosts.map((g) => <GhostLine key={g.key} points={g.points} />)}
    {parts.map((p) => <Tube key={p.key} points={p.points} magnitudes={p.magnitudes} radius={p.radius} peak={peak} />)}
    {f.blade > 0 && <mesh position={hub}><sphereGeometry args={[Math.max(f.hubRadius, 0.03), 20, 14]} /><meshStandardMaterial color="#2A303A" /></mesh>}
    {f.H > 0 && f.blade > 0 && <mesh position={[(top[0] + hub[0]) / 2, f.H + f.shaft / 2, (top[2] + hub[2]) / 2]}>
      <boxGeometry args={[0.07, Math.max(f.shaft, 0.04), Math.max(Math.abs(f.hub[2]) * 1.4, 0.12)]} /><meshStandardMaterial color="#232933" /></mesh>}
    <gridHelper args={[3, 12, '#232933', '#171B21']} position={[0, f.H ? 0 : -(f.hubRadius + f.blade) * 1.1, 0]} />
  </group>;
}

export default function ModeViewport({ layout, mode, amplitude = 0.5, playing = true, view = 'iso', label }) {
  const phase = useRef(Math.PI / 2);
  const f = useMemo(() => frame(layout || {}), [layout]);
  if (!mode || !layout || (!layout.tower_height_m && !layout.blade_length_m)) {
    return <div className="grid h-full place-items-center text-xs text-nv-muted">No geometry to draw for this mode</div>;
  }
  return <Canvas role="img" aria-label={label || 'Animated mode shape'} camera={{ fov: 32, near: 0.01, far: 50 }} dpr={[1, 2]} gl={{ antialias: true }}>
    <color attach="background" args={['#0E1014']} />
    <ambientLight intensity={0.55} />
    <directionalLight position={[3, 4, 2]} intensity={1.1} />
    <directionalLight position={[-2, 1, -3]} intensity={0.35} />
    <Controls view={view} target={f.centre} />
    <Turbine layout={layout} mode={mode} amplitude={amplitude} playing={playing} phase={phase} />
  </Canvas>;
}
