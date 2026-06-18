import { Canvas, useFrame, useThree } from '@react-three/fiber';
import {
  Activity,
  AlertCircle,
  ArrowDownToLine,
  Boxes,
  CheckCircle2,
  ClipboardList,
  Cpu,
  Database,
  Eye,
  EyeOff,
  FileDown,
  Gauge,
  Grid3X3,
  Layers3,
  Loader2,
  Pause,
  Play,
  Rotate3D,
  RotateCw,
  Sparkles,
  Waves,
  Wind,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import * as THREE from 'three';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
const AIR_DENSITY = 1.225;

function apiPath(path) {
  return `${API_BASE_URL.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
}

const workflowTabs = [
  {
    id: 'brief',
    label: 'Sizing',
    title: 'Preliminary sizing',
    icon: ClipboardList,
  },
  {
    id: 'geometry',
    label: 'BEMT',
    title: 'BEMT blade refinement',
    icon: Layers3,
  },
  {
    id: 'optimize',
    label: 'Optimize',
    title: 'Larrabee circulation refinement',
    icon: Cpu,
  },
  {
    id: 'analysis',
    label: 'Review',
    title: 'Validation and export',
    icon: Activity,
  },
  {
    id: 'reports',
    label: 'Database',
    title: 'Saved propellers and airfoils',
    icon: Database,
  },
];

const fields = [
  { id: 'thrust_target', label: 'Thrust Target', unit: 'N', step: 0.5, min: 1, icon: Wind },
  { id: 'rpm', label: 'RPM', unit: 'rev/min', step: 100, min: 500, icon: Gauge },
  { id: 'diameter', label: 'Diameter', unit: 'm', step: 0.01, min: 0.05, icon: Boxes },
];

const initialProject = {
  name: 'Nova 10N Micro UAV',
  mission: 'Endurance quadcopter',
  notes: 'Hover-optimized propeller for rapid STL iteration',
  material: 'Carbon nylon prototype',
};

const initialInputs = {
  thrust_target: 10,
  rpm: 5000,
  diameter: 0.25,
  blades: 2,
  airfoil: 'NACA 4412',
  design_mode: 'bemt',
  profile_strategy: 'constant',
  design_alpha_deg: 5,
};

const airfoilOptions = ['NACA 0012', 'NACA 2412', 'NACA 4412', 'NACA 6409'];

const profileStrategies = [
  { value: 'constant', label: 'Constant profile' },
  { value: 'root_cambered', label: 'Root cambered' },
  { value: 'tip_thin', label: 'Thin tip' },
  { value: 'optimized', label: 'Optimized variation' },
];

function formatValue(value, digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) : '--';
}

function useDesignStats(inputs) {
  return useMemo(() => {
    const radius = inputs.diameter / 2;
    const diskArea = Math.PI * radius ** 2;
    const omega = (2 * Math.PI * inputs.rpm) / 60;
    const tipSpeed = omega * radius;
    const inducedVelocity = Math.sqrt(inputs.thrust_target / (2 * AIR_DENSITY * diskArea));
    const diskLoading = inputs.thrust_target / diskArea;
    const inflowAngle = Math.atan2(inducedVelocity, tipSpeed) * (180 / Math.PI);
    const tipMach = tipSpeed / 343;

    return {
      cards: [
        { label: 'Tip Speed', value: `${formatValue(tipSpeed, 0)} m/s` },
        { label: 'Disk Loading', value: `${formatValue(diskLoading, 0)} N/m2` },
        { label: 'Induced Flow', value: `${formatValue(inducedVelocity, 1)} m/s` },
        { label: 'Inflow Angle', value: `${formatValue(inflowAngle, 1)} deg` },
      ],
      checks: [
        {
          label: 'Tip Mach',
          value: formatValue(tipMach, 2),
          ok: tipMach < 0.65,
        },
        {
          label: 'Disk loading',
          value: `${formatValue(diskLoading, 0)} N/m2`,
          ok: diskLoading < 500,
        },
        {
          label: 'RPM range',
          value: `${inputs.rpm} rpm`,
          ok: inputs.rpm >= 1000 && inputs.rpm <= 30000,
        },
      ],
    };
  }, [inputs]);
}

function getPreliminarySizing(inputs) {
  const radius = inputs.diameter / 2;
  const diskArea = Math.PI * radius ** 2;
  const diskLoading = inputs.thrust_target / diskArea;
  const targetTipSpeed = diskLoading > 420 ? 135 : diskLoading > 260 ? 120 : 105;
  const recommendedRpm = Math.round(((targetTipSpeed / radius) * 60) / (2 * Math.PI) / 100) * 100;
  const recommendedBlades = diskLoading > 420 ? 4 : diskLoading > 260 ? 3 : 2;
  const recommendedAirfoil = diskLoading > 360 ? 'NACA 6409' : 'NACA 4412';

  return {
    rpm: Math.max(1200, Math.min(recommendedRpm, 30000)),
    blades: recommendedBlades,
    airfoil: recommendedAirfoil,
    tipSpeed: targetTipSpeed,
    diskLoading,
  };
}

function SceneOrbitControls() {
  const { camera, gl } = useThree();
  const controlsRef = useRef(null);

  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minDistance = 1.2;
    controls.maxDistance = 5.2;
    controlsRef.current = controls;

    return () => controls.dispose();
  }, [camera, gl]);

  useFrame(() => controlsRef.current?.update());
  return null;
}

function ReferenceRings() {
  return (
    <group rotation={[Math.PI / 2, 0, 0]}>
      {[0.55, 0.95, 1.35].map((radius) => (
        <mesh key={radius}>
          <torusGeometry args={[radius, 0.002, 8, 128]} />
          <meshBasicMaterial color="#27272a" transparent opacity={0.8} />
        </mesh>
      ))}
      <mesh>
        <torusGeometry args={[0.18, 0.003, 8, 96]} />
        <meshBasicMaterial color="#52525b" transparent opacity={0.9} />
      </mesh>
    </group>
  );
}

function PlaceholderPropeller({ bladeCount, displayMode, autoSpin }) {
  const groupRef = useRef(null);
  const bladeShape = useMemo(() => {
    const shape = new THREE.Shape();
    shape.moveTo(0.08, 0);
    shape.bezierCurveTo(0.28, 0.05, 0.73, 0.06, 1.18, 0.018);
    shape.bezierCurveTo(1.28, 0.007, 1.28, -0.007, 1.18, -0.018);
    shape.bezierCurveTo(0.73, -0.06, 0.28, -0.05, 0.08, 0);
    return shape;
  }, []);

  const bladeGeometry = useMemo(() => {
    const geometry = new THREE.ExtrudeGeometry(bladeShape, {
      depth: 0.018,
      bevelEnabled: true,
      bevelThickness: 0.004,
      bevelSize: 0.004,
      bevelSegments: 2,
      curveSegments: 32,
    });
    geometry.center();
    geometry.rotateY(Math.PI / 2);
    geometry.translate(0.66, 0, 0);
    return geometry;
  }, [bladeShape]);

  useFrame((_, delta) => {
    if (autoSpin && groupRef.current) {
      groupRef.current.rotation.z += delta * 0.2;
    }
  });

  return (
    <group ref={groupRef} rotation={[0.28, 0.18, -0.18]}>
      {Array.from({ length: bladeCount }).map((_, index) => (
        <mesh
          key={index}
          geometry={bladeGeometry}
          rotation={[0, 0, (index * Math.PI * 2) / bladeCount]}
        >
          <meshStandardMaterial
            color="#e4e4e7"
            metalness={0.16}
            roughness={0.45}
            wireframe={displayMode === 'wireframe'}
          />
        </mesh>
      ))}
      <mesh>
        <cylinderGeometry args={[0.14, 0.14, 0.08, 64]} />
        <meshStandardMaterial
          color="#fafafa"
          metalness={0.24}
          roughness={0.34}
          wireframe={displayMode === 'wireframe'}
        />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.19, 0.006, 12, 80]} />
        <meshStandardMaterial color="#71717a" roughness={0.55} />
      </mesh>
    </group>
  );
}

function GeneratedPropeller({ geometry, displayMode, autoSpin }) {
  const meshRef = useRef(null);
  const normalizedGeometry = useMemo(() => {
    const nextGeometry = geometry.clone();
    nextGeometry.computeVertexNormals();
    nextGeometry.computeBoundingBox();

    const box = nextGeometry.boundingBox;
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);

    nextGeometry.translate(-center.x, -center.y, -center.z);
    const scale = 1.85 / Math.max(size.x, size.y, size.z);
    nextGeometry.scale(scale, scale, scale);
    nextGeometry.rotateX(-Math.PI / 2);
    return nextGeometry;
  }, [geometry]);

  useEffect(() => () => normalizedGeometry.dispose(), [normalizedGeometry]);

  useFrame((_, delta) => {
    if (autoSpin && meshRef.current) {
      meshRef.current.rotation.y += delta * 0.24;
    }
  });

  return (
    <mesh ref={meshRef} geometry={normalizedGeometry} rotation={[0.36, 0.14, 0]}>
      <meshStandardMaterial
        color="#e4e4e7"
        metalness={0.18}
        roughness={0.46}
        side={THREE.DoubleSide}
        wireframe={displayMode === 'wireframe'}
      />
    </mesh>
  );
}

function AeroOverlay({ mode, analysisData, bladeCount, autoSpin }) {
  const groupRef = useRef(null);
  const overlayData = useMemo(() => {
    const stations = analysisData?.stations ?? [];
    const usableStations = stations.filter((_, index) => index % 4 === 0 || index === stations.length - 1);
    const maxThrust = Math.max(...usableStations.map((station) => Math.abs(station.d_thrust_n ?? 0)), 1e-6);
    const maxPower = Math.max(...usableStations.map((station) => Math.abs(station.d_power_w ?? 0)), 1e-6);

    return usableStations.map((station) => ({
      radius: 0.22 + Number(station.r_over_R) * 1.18,
      load: Math.max(0.12, Math.abs(station.d_thrust_n ?? 0) / maxThrust),
      power: Math.max(0.12, Math.abs(station.d_power_w ?? 0) / maxPower),
      alpha: Number(station.alpha_deg ?? 0),
      rOverR: Number(station.r_over_R ?? 0),
    }));
  }, [analysisData]);

  useFrame((_, delta) => {
    if (autoSpin && groupRef.current) {
      groupRef.current.rotation.z += delta * 0.24;
    }
  });

  if (mode === 'off' || !analysisData || overlayData.length === 0) {
    return null;
  }

  return (
    <group ref={groupRef} rotation={[0.36, 0.14, 0]}>
      {mode === 'velocity' ? (
        <VelocityVectors data={overlayData} bladeCount={bladeCount} />
      ) : null}
      {mode === 'loading' ? (
        <LoadingMap data={overlayData} bladeCount={bladeCount} />
      ) : null}
      {mode === 'vortices' ? (
        <TipVortices bladeCount={bladeCount} strength={overlayData.at(-1)?.load ?? 0.5} />
      ) : null}
    </group>
  );
}

function VelocityVectors({ data, bladeCount }) {
  return Array.from({ length: bladeCount }).flatMap((_, bladeIndex) => {
    const bladeAngle = (bladeIndex * Math.PI * 2) / bladeCount;
    return data.map((station, stationIndex) => {
      const length = 0.26 + station.power * 0.34;
      const x = station.radius * Math.cos(bladeAngle);
      const y = station.radius * Math.sin(bladeAngle);
      const angle = bladeAngle + Math.PI / 2;
      const z = 0.16 + station.rOverR * 0.08;

      return (
        <group key={`${bladeIndex}-${stationIndex}`} position={[x, y, z]} rotation={[0, 0, angle]}>
          <mesh position={[length / 2, 0, 0]} rotation={[0, 0, -Math.PI / 2]}>
            <cylinderGeometry args={[0.01, 0.01, length, 10]} />
            <meshBasicMaterial color="#22d3ee" transparent opacity={0.88} />
          </mesh>
          <mesh position={[length, 0, 0]} rotation={[0, 0, -Math.PI / 2]}>
            <coneGeometry args={[0.04, 0.09, 14]} />
            <meshBasicMaterial color="#cffafe" transparent opacity={0.95} />
          </mesh>
        </group>
      );
    });
  });
}

function LoadingMap({ data, bladeCount }) {
  return Array.from({ length: bladeCount }).flatMap((_, bladeIndex) => {
    const bladeAngle = (bladeIndex * Math.PI * 2) / bladeCount;
    return data.map((station, stationIndex) => {
      const color = station.alpha > 10 ? '#fbbf24' : station.load > 0.65 ? '#f97316' : '#38bdf8';
      const x = station.radius * Math.cos(bladeAngle);
      const y = station.radius * Math.sin(bladeAngle);

      return (
        <mesh
          key={`${bladeIndex}-${stationIndex}`}
          position={[x, y, 0.10 + station.load * 0.16]}
          rotation={[Math.PI / 2, 0, bladeAngle]}
        >
          <boxGeometry args={[0.16 + station.load * 0.28, 0.035, 0.06 + station.load * 0.14]} />
          <meshBasicMaterial color={color} transparent opacity={0.72} />
        </mesh>
      );
    });
  });
}

function TipVortices({ bladeCount, strength }) {
  return Array.from({ length: bladeCount }).map((_, bladeIndex) => {
    const points = [];
    const startAngle = (bladeIndex * Math.PI * 2) / bladeCount;
    for (let index = 0; index < 96; index += 1) {
      const t = index / 95;
      const angle = startAngle + t * Math.PI * 3.4;
      const radius = 1.28 + t * 0.16;
      points.push(
        new THREE.Vector3(
          radius * Math.cos(angle),
          radius * Math.sin(angle),
          -t * (0.85 + strength * 0.55),
        ),
      );
    }
    const curve = new THREE.CatmullRomCurve3(points);

    return (
      <mesh key={bladeIndex}>
        <tubeGeometry args={[curve, 96, 0.014 + strength * 0.01, 10, false]} />
        <meshBasicMaterial color="#a78bfa" transparent opacity={0.82} />
      </mesh>
    );
  });
}

function TextField({ label, value, onChange, disabled }) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium text-zinc-300">{label}</span>
      <input
        className="w-full rounded-md border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-zinc-600 disabled:cursor-not-allowed disabled:opacity-60"
        type="text"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function NumberField({ field, value, onChange, disabled }) {
  const Icon = field.icon;

  return (
    <label className="block">
      <span className="mb-2 flex items-center gap-2 text-sm font-medium text-zinc-300">
        <Icon className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        {field.label}
      </span>
      <div className="flex items-center rounded-md border border-zinc-800 bg-zinc-950/70 focus-within:border-zinc-600">
        <input
          className="min-w-0 flex-1 bg-transparent px-3 py-2.5 text-sm text-zinc-100 outline-none disabled:cursor-not-allowed disabled:opacity-60"
          type="number"
          value={value}
          min={field.min}
          step={field.step}
          disabled={disabled}
          onChange={(event) => onChange(field.id, Number(event.target.value))}
        />
        <span className="border-l border-zinc-800 px-3 text-xs text-zinc-500">
          {field.unit}
        </span>
      </div>
    </label>
  );
}

function SelectField({ label, value, options, onChange, disabled }) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium text-zinc-300">{label}</span>
      <select
        className="w-full rounded-md border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-zinc-600 disabled:cursor-not-allowed disabled:opacity-60"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value ?? option} value={option.value ?? option}>
            {option.label ?? option}
          </option>
        ))}
      </select>
    </label>
  );
}

function MetricStrip({ stats }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {stats.map((stat) => (
        <div key={stat.label} className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
          <div className="text-[11px] uppercase tracking-wide text-zinc-500">{stat.label}</div>
          <div className="mt-1 text-sm font-medium text-zinc-100">{stat.value}</div>
        </div>
      ))}
    </div>
  );
}

function DistributionChart({ title, stations, field, unit, color = '#e4e4e7' }) {
  const values = stations.map((station) => Number(station[field])).filter(Number.isFinite);
  if (!values.length) {
    return null;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1e-6);
  const points = stations
    .map((station, index) => {
      const x = stations.length <= 1 ? 0 : (index / (stations.length - 1)) * 100;
      const y = 42 - ((Number(station[field]) - min) / range) * 34;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-zinc-300">{title}</div>
        <div className="text-[11px] text-zinc-500">
          {formatValue(min, field === 'reynolds' ? 0 : 1)}-{formatValue(max, field === 'reynolds' ? 0 : 1)} {unit}
        </div>
      </div>
      <svg className="h-14 w-full overflow-visible" viewBox="0 0 100 48" preserveAspectRatio="none">
        <line x1="0" y1="43" x2="100" y2="43" stroke="#27272a" strokeWidth="1" />
        <line x1="0" y1="8" x2="100" y2="8" stroke="#18181b" strokeWidth="1" />
        <polyline points={points} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

function PolarPreviewChart({ rows }) {
  const groupedRows = useMemo(() => {
    if (!rows?.length) {
      return [];
    }

    const reynoldsGroups = rows.reduce((groups, row) => {
      const reynolds = Number(row.reynolds);
      groups[reynolds] = [...(groups[reynolds] ?? []), row];
      return groups;
    }, {});
    const reynoldsKeys = Object.keys(reynoldsGroups)
      .map(Number)
      .sort((a, b) => a - b);
    const selectedReynolds = reynoldsKeys[Math.floor(reynoldsKeys.length / 2)];
    return reynoldsGroups[selectedReynolds]
      .slice()
      .sort((a, b) => Number(a.alpha_deg) - Number(b.alpha_deg));
  }, [rows]);

  if (!groupedRows.length) {
    return null;
  }

  const clValues = groupedRows.map((row) => Number(row.cl));
  const cdValues = groupedRows.map((row) => Number(row.cd));
  const efficiencyValues = groupedRows.map((row) => Number(row.cl) / Math.max(Number(row.cd), 1e-6));
  const alphaValues = groupedRows.map((row) => Number(row.alpha_deg));
  const clMin = Math.min(...clValues);
  const clMax = Math.max(...clValues);
  const cdMin = Math.min(...cdValues);
  const cdMax = Math.max(...cdValues);
  const efficiencyMin = Math.min(...efficiencyValues);
  const efficiencyMax = Math.max(...efficiencyValues);
  const alphaMin = Math.min(...alphaValues);
  const alphaMax = Math.max(...alphaValues);

  const buildPoints = (values, min, max) => {
    const valueRange = Math.max(max - min, 1e-6);
    const alphaRange = Math.max(alphaMax - alphaMin, 1e-6);
    return groupedRows
      .map((row, index) => {
        const x = ((Number(row.alpha_deg) - alphaMin) / alphaRange) * 100;
        const y = 42 - ((values[index] - min) / valueRange) * 34;
        return `${x},${y}`;
      })
      .join(' ');
  };

  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-zinc-300">Polar slice</div>
        <div className="text-[11px] text-zinc-500">
          Re {Number(groupedRows[0].reynolds).toFixed(0)} | alpha {alphaMin}-{alphaMax} deg
        </div>
      </div>
      <svg className="h-20 w-full overflow-visible" viewBox="0 0 100 48" preserveAspectRatio="none">
        <line x1="0" y1="43" x2="100" y2="43" stroke="#27272a" strokeWidth="1" />
        <line x1="0" y1="8" x2="100" y2="8" stroke="#18181b" strokeWidth="1" />
        <polyline points={buildPoints(clValues, clMin, clMax)} fill="none" stroke="#67e8f9" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <polyline points={buildPoints(cdValues, cdMin, cdMax)} fill="none" stroke="#fbbf24" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <polyline points={buildPoints(efficiencyValues, efficiencyMin, efficiencyMax)} fill="none" stroke="#a7f3d0" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-2 flex gap-2 text-[11px] text-zinc-500">
        <span className="text-cyan-200">Cl</span>
        <span className="text-amber-200">Cd</span>
        <span className="text-emerald-200">Cl/Cd</span>
      </div>
    </div>
  );
}

function PolarDiagnostics({ detail }) {
  const quality = detail?.polar_quality;
  const sets = detail?.polar_sets ?? [];

  if (!detail) {
    return null;
  }

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-medium text-zinc-300">Polar data quality</div>
            <div className="mt-1 text-[11px] text-zinc-500">
              Active set #{quality?.active_set_id ?? '--'} | {quality?.reynolds?.length ?? 0} Reynolds slices | {quality?.alpha?.length ?? 0} alpha samples
            </div>
          </div>
          <span
            className={`rounded-md border px-2 py-1 text-[11px] ${
              quality?.status === 'ok'
                ? 'border-emerald-900/70 text-emerald-300'
                : 'border-amber-900/70 text-amber-300'
            }`}
          >
            {quality?.status ?? 'missing'}
          </span>
        </div>
        {quality?.warnings?.length ? (
          <div className="space-y-2">
            {quality.warnings.map((warning) => (
              <div key={warning} className="rounded border border-amber-900/60 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">
                {warning}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded border border-emerald-900/60 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-200">
            Active polar set passes the current MVP quality checks.
          </div>
        )}
      </div>

      <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
        <div className="mb-3 text-xs font-medium text-zinc-300">Polar sets</div>
        <div className="max-h-40 space-y-2 overflow-auto">
          {sets.map((set) => (
            <div key={set.id} className="rounded border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-zinc-200">{set.label}</span>
                <span className="text-zinc-500">#{set.id}</span>
              </div>
              <div className="mt-1 grid grid-cols-3 gap-2 text-zinc-500">
                <span>{set.method}</span>
                <span>Re {set.min_reynolds ?? '--'}-{set.max_reynolds ?? '--'}</span>
                <span>{set.points} pts</span>
              </div>
            </div>
          ))}
          {!sets.length ? (
            <div className="text-xs text-zinc-500">No polar sets available.</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function AnalysisWarnings({ summary }) {
  if (!summary) {
    return null;
  }

  const warnings = [
    Math.abs(summary.thrust_error_pct) > 12
      ? `Thrust error high: ${summary.thrust_error_pct}%. Adjust RPM, diameter or rerun optimization.`
      : null,
    summary.min_reynolds < 35000
      ? `Low Reynolds region detected: minimum Re ${summary.min_reynolds}. Small drone props may need lower-drag airfoils.`
      : null,
    summary.max_alpha_deg > 12
      ? `High local alpha: ${summary.max_alpha_deg} deg. Risk of stall in simplified polar model.`
      : null,
    summary.tip_mach > 0.65
      ? `Tip Mach ${summary.tip_mach}. Reduce RPM or diameter before export.`
      : null,
  ].filter(Boolean);

  if (!warnings.length) {
    return (
      <div className="rounded-md border border-emerald-900/60 bg-emerald-950/20 p-3 text-sm text-emerald-200">
        Computed operating point is within the current MVP limits.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {warnings.map((warning) => (
        <div key={warning} className="rounded-md border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200">
          {warning}
        </div>
      ))}
    </div>
  );
}

function WorkflowTabs({ activeTab, setActiveTab, hasGeometry }) {
  return (
    <nav className="grid grid-cols-5 gap-1 rounded-lg border border-zinc-800 bg-zinc-950/70 p-1">
      {workflowTabs.map((tab, index) => {
        const Icon = tab.icon;
        const isActive = activeTab === tab.id;
        const isComplete =
          tab.id === 'brief' ||
          (tab.id === 'geometry' && hasGeometry) ||
          (tab.id === 'optimize' && hasGeometry);

        return (
          <button
            key={tab.id}
            className={`flex min-h-16 flex-col items-start justify-between rounded-md px-3 py-2 text-left transition ${
              isActive
                ? 'bg-zinc-100 text-zinc-950'
                : 'text-zinc-500 hover:bg-zinc-900 hover:text-zinc-200'
            }`}
            type="button"
            onClick={() => setActiveTab(tab.id)}
          >
            <span className="flex w-full items-center justify-between">
              <Icon className="h-4 w-4" aria-hidden="true" />
              {isComplete ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> : null}
            </span>
            <span>
              <span className="block text-[11px] opacity-70">0{index + 1}</span>
              <span className="block text-xs font-medium">{tab.label}</span>
            </span>
          </button>
        );
      })}
    </nav>
  );
}

function PreliminaryPanel({ project, setProject, inputs, updateInput, stats, onNext }) {
  const sizing = getPreliminarySizing(inputs);

  const applySizing = () => {
    updateInput('rpm', sizing.rpm);
    updateInput('blades', sizing.blades);
    updateInput('airfoil', sizing.airfoil);
    updateInput('design_mode', 'preliminary');
    updateInput('profile_strategy', 'constant');
  };

  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Project envelope</h2>
            <p className="mt-1 text-xs text-zinc-500">Baseline information for the propeller run.</p>
          </div>
          <Cpu className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="space-y-4">
          <TextField
            label="Project Name"
            value={project.name}
            onChange={(value) => setProject((current) => ({ ...current, name: value }))}
          />
          <TextField
            label="Mission Profile"
            value={project.mission}
            onChange={(value) => setProject((current) => ({ ...current, mission: value }))}
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <TextField
              label="Project Notes"
              value={project.notes}
              onChange={(value) => setProject((current) => ({ ...current, notes: value }))}
            />
            <TextField
              label="Material"
              value={project.material}
              onChange={(value) => setProject((current) => ({ ...current, material: value }))}
            />
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Sizing inputs</h2>
            <p className="mt-1 text-xs text-zinc-500">Set the target envelope before running BEMT.</p>
          </div>
          <Gauge className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="space-y-4">
          <NumberField
            field={fields.find((field) => field.id === 'thrust_target')}
            value={inputs.thrust_target}
            onChange={updateInput}
          />
          <NumberField
            field={fields.find((field) => field.id === 'diameter')}
            value={inputs.diameter}
            onChange={updateInput}
          />
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
              <div className="text-[11px] uppercase tracking-wide text-zinc-500">Suggested RPM</div>
              <div className="mt-1 text-sm font-medium text-zinc-100">{sizing.rpm}</div>
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
              <div className="text-[11px] uppercase tracking-wide text-zinc-500">Suggested Blades</div>
              <div className="mt-1 text-sm font-medium text-zinc-100">{sizing.blades}</div>
            </div>
          </div>
          <button
            className="inline-flex h-10 w-full items-center justify-center rounded-md border border-zinc-800 bg-zinc-950 px-4 text-sm font-medium text-zinc-300 transition hover:border-zinc-700 hover:text-white"
            type="button"
            onClick={applySizing}
          >
            Apply Baseline Sizing
          </button>
        </div>
      </div>

      <MetricStrip stats={stats.cards} />
      <button
        className="inline-flex h-11 w-full items-center justify-center rounded-md bg-zinc-100 px-4 text-sm font-medium text-zinc-950 transition hover:bg-white"
        type="button"
        onClick={onNext}
      >
        Continue to Geometry
      </button>
    </section>
  );
}

function GeometryPanel({ inputs, updateInput, isLoading, onGenerate, error, airfoilChoices }) {
  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">BEMT refinement</h2>
            <p className="mt-1 text-xs text-zinc-500">Estimate thrust, torque and power from blade element loading.</p>
          </div>
          <Cpu className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
          <div className="text-sm font-medium text-zinc-200">Simplified BEMT</div>
          <p className="mt-1 text-xs leading-5 text-zinc-500">
            Uses the preliminary RPM, diameter and blade count, then solves chord and twist against local aerodynamic loading.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Design inputs</h2>
            <p className="mt-1 text-xs text-zinc-500">Parameters sent to the FastAPI geometry engine.</p>
          </div>
          <Layers3 className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="space-y-4">
          {fields.map((field) => (
            <NumberField
              key={field.id}
              field={field}
              value={inputs[field.id]}
              disabled={isLoading}
              onChange={updateInput}
            />
          ))}

          <label className="block">
            <span className="mb-2 flex items-center gap-2 text-sm font-medium text-zinc-300">
              <RotateCw className="h-4 w-4 text-zinc-500" aria-hidden="true" />
              Number of Blades
            </span>
            <select
              className="w-full rounded-md border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-100 outline-none focus:border-zinc-600 disabled:cursor-not-allowed disabled:opacity-60"
              value={inputs.blades}
              disabled={isLoading}
              onChange={(event) => updateInput('blades', Number(event.target.value))}
            >
              <option value="2">2 blades</option>
              <option value="3">3 blades</option>
              <option value="4">4 blades</option>
            </select>
          </label>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <SelectField
              label="Airfoil Family"
              value={inputs.airfoil}
              options={airfoilChoices}
              disabled={isLoading}
              onChange={(value) => updateInput('airfoil', value)}
            />
            <SelectField
              label="Profile Variation"
              value={inputs.profile_strategy}
              options={profileStrategies}
              disabled={isLoading}
              onChange={(value) => updateInput('profile_strategy', value)}
            />
          </div>

          <NumberField
            field={{
              id: 'design_alpha_deg',
              label: 'Design Alpha',
              unit: 'deg',
              step: 0.5,
              min: 1,
              icon: Activity,
            }}
            value={inputs.design_alpha_deg}
            disabled={isLoading}
            onChange={updateInput}
          />
        </div>
      </div>

      {error ? (
        <div className="flex items-start gap-2 rounded-md border border-red-900/70 bg-red-950/30 p-3 text-sm text-red-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}

      <button
        className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-md bg-zinc-100 px-4 text-sm font-medium text-zinc-950 transition hover:bg-white disabled:cursor-wait disabled:bg-zinc-300"
        type="button"
        onClick={() => onGenerate('bemt')}
        disabled={isLoading}
      >
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Play className="h-4 w-4" aria-hidden="true" />
        )}
        Run BEMT Geometry
      </button>
    </section>
  );
}

function OptimizePanel({ inputs, updateInput, isLoading, onGenerate, error, airfoilChoices }) {
  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Larrabee circulation design</h2>
            <p className="mt-1 text-xs text-zinc-500">Refine chord and twist from an optimum circulation distribution.</p>
          </div>
          <Cpu className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
          <div className="text-sm font-medium text-zinc-200">Optimum circulation refinement</div>
          <p className="mt-1 text-xs leading-5 text-zinc-500">
            Uses a Goldstein/Larrabee-style circulation shape, Prandtl losses, local inflow and target design Cl to compute chord and twist.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Optimization controls</h2>
            <p className="mt-1 text-xs text-zinc-500">Choose profile and radial variation for the advanced run.</p>
          </div>
          <Layers3 className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="space-y-4">
          <SelectField
            label="Airfoil Family"
            value={inputs.airfoil}
            options={airfoilChoices}
            disabled={isLoading}
            onChange={(value) => updateInput('airfoil', value)}
          />
          <SelectField
            label="Profile Variation"
            value={inputs.profile_strategy}
            options={profileStrategies}
            disabled={isLoading}
            onChange={(value) => updateInput('profile_strategy', value)}
          />
          <NumberField
            field={{
              id: 'design_alpha_deg',
              label: 'Design Alpha',
              unit: 'deg',
              step: 0.5,
              min: 1,
              icon: Activity,
            }}
            value={inputs.design_alpha_deg}
            disabled={isLoading}
            onChange={updateInput}
          />
        </div>
      </div>

      {error ? (
        <div className="flex items-start gap-2 rounded-md border border-red-900/70 bg-red-950/30 p-3 text-sm text-red-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}

      <button
        className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-md bg-zinc-100 px-4 text-sm font-medium text-zinc-950 transition hover:bg-white disabled:cursor-wait disabled:bg-zinc-300"
        type="button"
        onClick={() =>
          onGenerate('larrabee', {
            profile_strategy:
              inputs.profile_strategy === 'constant' ? 'optimized' : inputs.profile_strategy,
          })
        }
        disabled={isLoading}
      >
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Play className="h-4 w-4" aria-hidden="true" />
        )}
        Run Optimization
      </button>
    </section>
  );
}

function AnalysisPanel({
  project,
  stats,
  analysisData,
  analysisRuns,
  previewGeometry,
  meshWatertight,
  stlUrl,
  stlFilename,
  onGenerate,
  onSaveGeometry,
  isGeometrySaved,
  isLoading,
}) {
  const summary = analysisData?.summary;
  const geometry = analysisData?.geometry;
  const meshQuality = analysisData?.mesh_quality;
  const sampledStations = analysisData?.stations?.filter((_, index) => index % 5 === 0).slice(0, 6) ?? [];

  return (
    <section className="space-y-5">
      {analysisData ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-zinc-100">BEMT results</h2>
              <p className="mt-1 text-xs text-zinc-500">{analysisData.method}</p>
            </div>
            <Gauge className="h-4 w-4 text-zinc-500" aria-hidden="true" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            {[
              ['Estimated thrust', `${summary.estimated_thrust_n} N`],
              ['Target error', `${summary.thrust_error_pct} %`],
              ['Power', `${summary.power_w} W`],
              ['Torque', `${summary.torque_nm} Nm`],
              ['Figure of merit', summary.figure_of_merit],
              ['Mean Reynolds', summary.mean_reynolds],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
                <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
                <div className="mt-1 text-sm font-medium text-zinc-100">{value}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {summary ? <AnalysisWarnings summary={summary} /> : null}

      {analysisData ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-zinc-100">Aerodynamic overlays</h2>
              <p className="mt-1 text-xs text-zinc-500">Canvas layers derived from the BEMT station data.</p>
            </div>
            <Waves className="h-4 w-4 text-zinc-500" aria-hidden="true" />
          </div>
          <div className="grid grid-cols-1 gap-2 text-xs text-zinc-400 sm:grid-cols-3">
            <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-2">
              <span className="font-medium text-cyan-200">Flow</span> shows local velocity direction and relative power loading.
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-2">
              <span className="font-medium text-orange-200">Load map</span> shows qualitative blade loading from station thrust.
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-2">
              <span className="font-medium text-violet-200">Vortices</span> shows a qualitative helical tip wake.
            </div>
          </div>
        </div>
      ) : null}

      {analysisRuns.length > 1 ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-zinc-100">Run comparison</h2>
              <p className="mt-1 text-xs text-zinc-500">Session-only comparison of recent analyses.</p>
            </div>
            <Activity className="h-4 w-4 text-zinc-500" aria-hidden="true" />
          </div>
          <div className="space-y-2">
            {analysisRuns.slice(-4).map((run) => (
              <div
                key={run.id}
                className="grid grid-cols-4 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/55 px-3 py-2 text-xs"
              >
                <span className="font-medium text-zinc-200">{run.label}</span>
                <span className="text-zinc-500">{run.summary.estimated_thrust_n} N</span>
                <span className="text-zinc-500">{run.summary.power_w} W</span>
                <span className={Math.abs(run.summary.thrust_error_pct) < 10 ? 'text-emerald-300' : 'text-amber-300'}>
                  {run.summary.thrust_error_pct}%
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {geometry ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-zinc-100">Blade distribution</h2>
              <p className="mt-1 text-xs text-zinc-500">
                {geometry.stations} stations, {analysisData.airfoil}, {analysisData.profile_strategy}
              </p>
            </div>
            <Layers3 className="h-4 w-4 text-zinc-500" aria-hidden="true" />
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            {[
              ['Root chord', `${geometry.root_chord_mm} mm`],
              ['Mid chord', `${geometry.mid_chord_mm} mm`],
              ['Tip chord', `${geometry.tip_chord_mm} mm`],
              ['Root twist', `${geometry.root_twist_deg} deg`],
              ['Mid twist', `${geometry.mid_twist_deg} deg`],
              ['Tip twist', `${geometry.tip_twist_deg} deg`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md border border-zinc-800 bg-zinc-950/55 p-2">
                <div className="text-zinc-500">{label}</div>
                <div className="mt-1 font-medium text-zinc-100">{value}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            <DistributionChart
              title="Chord"
              stations={analysisData.stations}
              field="chord_mm"
              unit="mm"
              color="#f4f4f5"
            />
            <DistributionChart
              title="Twist"
              stations={analysisData.stations}
              field="twist_deg"
              unit="deg"
              color="#a1a1aa"
            />
            <DistributionChart
              title="Reynolds"
              stations={analysisData.stations}
              field="reynolds"
              unit=""
              color="#6ee7b7"
            />
            <DistributionChart
              title="Alpha"
              stations={analysisData.stations}
              field="alpha_deg"
              unit="deg"
              color="#fbbf24"
            />
            <DistributionChart
              title="Circulation"
              stations={analysisData.stations}
              field="circulation"
              unit="m2/s"
              color="#c4b5fd"
            />
          </div>
          <div className="mt-3 overflow-hidden rounded-md border border-zinc-800">
            <div className="grid grid-cols-5 bg-zinc-950/80 px-3 py-2 text-[11px] uppercase tracking-wide text-zinc-500">
              <span>r/R</span>
              <span>Chord</span>
              <span>Twist</span>
              <span>Re</span>
              <span>Gamma</span>
            </div>
            {sampledStations.map((station) => (
              <div key={station.r_over_R} className="grid grid-cols-5 border-t border-zinc-900 px-3 py-2 text-xs text-zinc-300">
                <span>{station.r_over_R}</span>
                <span>{station.chord_mm} mm</span>
                <span>{station.twist_deg} deg</span>
                <span>{station.reynolds}</span>
                <span>{station.circulation}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Quality gate</h2>
            <p className="mt-1 text-xs text-zinc-500">{project.name}</p>
          </div>
          <Activity className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="grid gap-2 xl:grid-cols-2 2xl:grid-cols-3">
          {stats.checks.map((check) => (
            <div
              key={check.label}
              className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950/55 px-3 py-2"
            >
              <span className="text-sm text-zinc-300">{check.label}</span>
              <span className={check.ok ? 'text-sm text-emerald-300' : 'text-sm text-amber-300'}>
                {check.value}
              </span>
            </div>
          ))}
          <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950/55 px-3 py-2">
            <span className="text-sm text-zinc-300">Mesh watertight</span>
            <span className={meshWatertight === 'true' ? 'text-sm text-emerald-300' : 'text-sm text-zinc-500'}>
              {meshWatertight ?? 'pending'}
            </span>
          </div>
          {meshQuality ? (
            <>
              <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950/55 px-3 py-2">
                <span className="text-sm text-zinc-300">Mesh size</span>
                <span className="text-sm text-zinc-500">
                  {meshQuality.vertices} vertices / {meshQuality.faces} faces
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950/55 px-3 py-2">
                <span className="text-sm text-zinc-300">Mesh bodies</span>
                <span className="text-sm text-zinc-500">
                  {meshQuality.bodies === -1 ? 'unavailable' : meshQuality.bodies}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950/55 px-3 py-2">
                <span className="text-sm text-zinc-300">Bounds</span>
                <span className="text-sm text-zinc-500">
                  {meshQuality.bounds_m?.join(' x ')} m
                </span>
              </div>
            </>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3">
        <button
          className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-zinc-100 px-4 text-sm font-medium text-zinc-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-45"
          type="button"
          onClick={onSaveGeometry}
          disabled={!analysisData || isGeometrySaved}
        >
          <Database className="h-4 w-4" aria-hidden="true" />
          {isGeometrySaved ? 'Geometry Saved' : 'Save Geometry to Database'}
        </button>
        <button
          className="inline-flex h-11 items-center justify-center gap-2 rounded-md border border-zinc-800 bg-zinc-950 px-4 text-sm font-medium text-zinc-300 transition hover:border-zinc-700 hover:text-white disabled:cursor-wait disabled:opacity-60"
          type="button"
          onClick={() => onGenerate('bemt')}
          disabled={isLoading}
        >
          {isLoading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
          Rebuild STL
        </button>
        <a
          className={`inline-flex h-11 items-center justify-center gap-2 rounded-md bg-zinc-100 px-4 text-sm font-medium text-zinc-950 transition hover:bg-white ${
            stlUrl ? '' : 'pointer-events-none opacity-45'
          }`}
          href={stlUrl || undefined}
          download={stlFilename}
          aria-disabled={!stlUrl}
        >
          <ArrowDownToLine className="h-4 w-4" aria-hidden="true" />
          Download STL
        </a>
      </div>

      {!previewGeometry ? (
        <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3 text-sm text-zinc-500">
          Generate geometry before exporting the propeller mesh.
        </div>
      ) : null}
    </section>
  );
}

function ReportsPanel({
  airfoils,
  selectedAirfoil,
  setSelectedAirfoil,
  selectedAirfoilDetail,
  savedPropellers,
  selectedPropellerDetail,
  newAirfoil,
  setNewAirfoil,
  airfoilEdit,
  setAirfoilEdit,
  onSelectPropeller,
  onOpenPropeller,
  onCreateAirfoil,
  onUpdateAirfoil,
  onDeleteAirfoil,
  onDeletePropeller,
  isLoading,
}) {
  const polarRows = selectedAirfoilDetail?.polars ?? [];
  const selectedAnalysis = selectedPropellerDetail?.analysis;
  const selectedPayload = selectedPropellerDetail?.payload;
  const selectedSummary = selectedAnalysis?.summary;
  const selectedGeometry = selectedAnalysis?.geometry;
  const selectedStations = selectedAnalysis?.stations ?? [];
  const selectedPropellerPolars =
    selectedAirfoilDetail?.name === selectedPropellerDetail?.airfoil ? polarRows : [];

  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4">
          <h2 className="text-sm font-medium text-zinc-100">Saved propellers</h2>
          <p className="mt-1 text-xs text-zinc-500">Open a stored design to inspect its inputs, report, polars and 3D render.</p>
        </div>
        <div className="space-y-2">
          {savedPropellers.map((report) => (
            <div
              key={report.id}
              className={`rounded-md border px-3 py-2 text-xs transition ${
                selectedPropellerDetail?.id === report.id
                  ? 'border-zinc-600 bg-zinc-800/70'
                  : 'border-zinc-800 bg-zinc-950/55'
              }`}
            >
              <button
                className="w-full text-left"
                type="button"
                onClick={() => onSelectPropeller(report.id)}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-zinc-200">{report.project_name}</span>
                  <span className="text-zinc-500">#{report.id}</span>
                </div>
                <div className="mt-1 grid grid-cols-4 gap-2 text-zinc-500">
                  <span>{report.design_mode}</span>
                  <span>{report.airfoil}</span>
                  <span>{report.summary.estimated_thrust_n} N</span>
                  <span>{report.summary.power_w} W</span>
                </div>
              </button>
              <div className="mt-2 flex items-center justify-between border-t border-zinc-900 pt-2">
                <span className="text-zinc-600">{report.created_at}</span>
                <button
                  className="text-red-300 transition hover:text-red-200"
                  type="button"
                  onClick={() => onDeletePropeller(report.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
          {!savedPropellers.length ? (
            <div className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3 text-sm text-zinc-500">
              No saved propellers yet.
            </div>
          ) : null}
        </div>
      </div>

      {selectedPropellerDetail ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-medium text-zinc-100">{selectedPropellerDetail.project_name}</h2>
              <p className="mt-1 text-xs text-zinc-500">
                {selectedPropellerDetail.design_mode} | {selectedPropellerDetail.airfoil} | saved {selectedPropellerDetail.created_at}
              </p>
            </div>
            <button
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-md bg-zinc-100 px-3 text-xs font-medium text-zinc-950 transition hover:bg-white disabled:cursor-wait disabled:opacity-60"
              type="button"
              onClick={onOpenPropeller}
              disabled={isLoading}
            >
              {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Eye className="h-3.5 w-3.5" aria-hidden="true" />}
              Open in 3D Canvas
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
            {[
              ['Thrust target', `${selectedPayload?.thrust_target} N`],
              ['RPM', `${selectedPayload?.rpm}`],
              ['Diameter', `${selectedPayload?.diameter} m`],
              ['Blades', selectedPayload?.blades],
              ['Estimated thrust', `${selectedSummary?.estimated_thrust_n} N`],
              ['Power', `${selectedSummary?.power_w} W`],
              ['Torque', `${selectedSummary?.torque_nm} Nm`],
              ['Figure of merit', selectedSummary?.figure_of_merit],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md border border-zinc-800 bg-zinc-950/55 p-3">
                <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
                <div className="mt-1 text-sm font-medium text-zinc-100">{value ?? '--'}</div>
              </div>
            ))}
          </div>

          {selectedGeometry ? (
            <div className="mt-4 grid grid-cols-3 gap-2 text-xs xl:grid-cols-6">
              {[
                ['Stations', selectedGeometry.stations],
                ['Root chord', `${selectedGeometry.root_chord_mm} mm`],
                ['Tip chord', `${selectedGeometry.tip_chord_mm} mm`],
                ['Root twist', `${selectedGeometry.root_twist_deg} deg`],
                ['Tip twist', `${selectedGeometry.tip_twist_deg} deg`],
                ['Mean Re', selectedSummary?.mean_reynolds],
              ].map(([label, value]) => (
                <div key={label} className="rounded-md border border-zinc-800 bg-zinc-950/55 p-2">
                  <div className="text-zinc-500">{label}</div>
                  <div className="mt-1 font-medium text-zinc-100">{value ?? '--'}</div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <DistributionChart title="Chord" stations={selectedStations} field="chord_mm" unit="mm" color="#f4f4f5" />
            <DistributionChart title="Twist" stations={selectedStations} field="twist_deg" unit="deg" color="#a1a1aa" />
            <DistributionChart title="Cl" stations={selectedStations} field="cl" unit="" color="#67e8f9" />
            <DistributionChart title="Cd" stations={selectedStations} field="cd" unit="" color="#fbbf24" />
          </div>

          <div className="mt-4 max-h-72 overflow-auto rounded-md border border-zinc-800">
            <div className="grid min-w-[980px] grid-cols-8 bg-zinc-950/80 px-3 py-2 text-[11px] uppercase tracking-wide text-zinc-500">
              <span>r/R</span>
              <span>Chord</span>
              <span>Twist</span>
              <span>Alpha</span>
              <span>Cl</span>
              <span>Cd</span>
              <span>Re</span>
              <span>dT</span>
            </div>
            {selectedStations.map((station) => (
              <div key={station.r_over_R} className="grid min-w-[980px] grid-cols-8 border-t border-zinc-900 px-3 py-2 text-xs text-zinc-300">
                <span>{station.r_over_R}</span>
                <span>{station.chord_mm} mm</span>
                <span>{station.twist_deg} deg</span>
                <span>{station.alpha_deg} deg</span>
                <span>{station.cl}</span>
                <span>{station.cd}</span>
                <span>{station.reynolds}</span>
                <span>{station.d_thrust_n} N</span>
              </div>
            ))}
          </div>

          {selectedPropellerPolars.length ? (
            <div className="mt-4 rounded-md border border-zinc-800 bg-zinc-950/35 p-3">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-medium text-zinc-300">Airfoil polars used by this run</div>
                  <div className="mt-1 text-[11px] text-zinc-500">
                    {selectedPropellerDetail.airfoil} | {selectedPropellerPolars.length} stored points
                  </div>
                </div>
                <Database className="h-4 w-4 text-zinc-500" aria-hidden="true" />
              </div>
              <PolarPreviewChart rows={selectedPropellerPolars} />
              <div className="mt-3 max-h-44 overflow-auto rounded-md border border-zinc-800">
                <div className="grid min-w-[640px] grid-cols-6 bg-zinc-950/80 px-3 py-2 text-[11px] uppercase tracking-wide text-zinc-500">
                  <span>Re</span>
                  <span>Alpha</span>
                  <span>Cl</span>
                  <span>Cd</span>
                  <span>Cm</span>
                  <span>Cl/Cd</span>
                </div>
                {selectedPropellerPolars.slice(0, 24).map((row) => (
                  <div
                    key={`${row.reynolds}-${row.alpha_deg}`}
                    className="grid min-w-[640px] grid-cols-6 border-t border-zinc-900 px-3 py-2 text-xs text-zinc-300"
                  >
                    <span>{row.reynolds}</span>
                    <span>{row.alpha_deg}</span>
                    <span>{Number(row.cl).toFixed(3)}</span>
                    <span>{Number(row.cd).toFixed(4)}</span>
                    <span>{Number(row.cm ?? 0).toFixed(3)}</span>
                    <span>{(Number(row.cl) / Math.max(Number(row.cd), 1e-6)).toFixed(1)}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-zinc-100">Airfoil database</h2>
            <p className="mt-1 text-xs text-zinc-500">Stored airfoils and polar tables used by the solver.</p>
          </div>
          <Database className="h-4 w-4 text-zinc-500" aria-hidden="true" />
        </div>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {airfoils.map((airfoil) => (
            <button
              key={airfoil.name}
              className={`w-full rounded-md border px-3 py-2 text-left text-sm transition ${
                selectedAirfoil === airfoil.name
                  ? 'border-zinc-600 bg-zinc-800 text-white'
                  : 'border-zinc-800 bg-zinc-950/55 text-zinc-400 hover:text-zinc-100'
              }`}
              type="button"
              onClick={() => setSelectedAirfoil(airfoil.name)}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{airfoil.name}</span>
                <span className="text-xs text-zinc-500">{airfoil.polar_points} points</span>
              </div>
              <div className="mt-1 text-xs text-zinc-500">
                {airfoil.source} | Re {airfoil.min_reynolds ?? '--'}-{airfoil.max_reynolds ?? '--'}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
        <div className="mb-4">
          <h2 className="text-sm font-medium text-zinc-100">Save custom airfoil</h2>
          <p className="mt-1 text-xs text-zinc-500">Create an airfoil record, then import polar points through the API.</p>
        </div>
        <div className="grid gap-3">
          <TextField
            label="Airfoil Name"
            value={newAirfoil.name}
            onChange={(value) => setNewAirfoil((current) => ({ ...current, name: value }))}
          />
          <TextField
            label="Notes"
            value={newAirfoil.notes}
            onChange={(value) => setNewAirfoil((current) => ({ ...current, notes: value }))}
          />
          <button
            className="inline-flex h-10 items-center justify-center rounded-md border border-zinc-800 bg-zinc-950 px-4 text-sm font-medium text-zinc-300 transition hover:border-zinc-700 hover:text-white"
            type="button"
            onClick={onCreateAirfoil}
          >
            Save Airfoil
          </button>
        </div>
      </div>

      {selectedAirfoilDetail ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
          <div className="mb-4">
            <h2 className="text-sm font-medium text-zinc-100">{selectedAirfoilDetail.name}</h2>
            <p className="mt-1 text-xs text-zinc-500">{selectedAirfoilDetail.notes}</p>
          </div>
          <PolarDiagnostics detail={selectedAirfoilDetail} />
          <PolarPreviewChart rows={polarRows} />
          <div className="mb-4 grid gap-3">
            <TextField
              label="Family"
              value={airfoilEdit.family}
              onChange={(value) => setAirfoilEdit((current) => ({ ...current, family: value }))}
            />
            <TextField
              label="Source"
              value={airfoilEdit.source}
              onChange={(value) => setAirfoilEdit((current) => ({ ...current, source: value }))}
            />
            <TextField
              label="Notes"
              value={airfoilEdit.notes}
              onChange={(value) => setAirfoilEdit((current) => ({ ...current, notes: value }))}
            />
            <div className="grid grid-cols-2 gap-2">
              <button
                className="inline-flex h-10 items-center justify-center rounded-md border border-zinc-800 bg-zinc-950 px-4 text-sm font-medium text-zinc-300 transition hover:border-zinc-700 hover:text-white"
                type="button"
                onClick={onUpdateAirfoil}
              >
                Update Airfoil Info
              </button>
              <button
                className="inline-flex h-10 items-center justify-center rounded-md border border-red-900/70 bg-red-950/30 px-4 text-sm font-medium text-red-200 transition hover:border-red-700"
                type="button"
                onClick={onDeleteAirfoil}
              >
                Delete Airfoil
              </button>
            </div>
          </div>
          <div className="max-h-80 overflow-auto rounded-md border border-zinc-800">
            <div className="grid min-w-[820px] grid-cols-8 bg-zinc-950/80 px-3 py-2 text-[11px] uppercase tracking-wide text-zinc-500">
              <span>Set</span>
              <span>Re</span>
              <span>Mach</span>
              <span>Alpha</span>
              <span>Cl</span>
              <span>Cd</span>
              <span>Cm</span>
              <span>Source</span>
            </div>
            {polarRows.map((row) => (
              <div
                key={`${row.polar_set_id}-${row.reynolds}-${row.alpha_deg}`}
                className="grid min-w-[820px] grid-cols-8 border-t border-zinc-900 px-3 py-2 text-xs text-zinc-300"
              >
                <span>{row.polar_set_id}</span>
                <span>{row.reynolds}</span>
                <span>{Number(row.mach ?? 0).toFixed(2)}</span>
                <span>{row.alpha_deg}</span>
                <span>{Number(row.cl).toFixed(3)}</span>
                <span>{Number(row.cd).toFixed(4)}</span>
                <span>{Number(row.cm ?? 0).toFixed(3)}</span>
                <span className="truncate text-zinc-500">{row.source}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 rounded-md border border-zinc-800 bg-zinc-950/55 p-3 text-xs text-zinc-500">
            Import endpoint: <span className="text-zinc-300">POST /api/airfoils/{selectedAirfoilDetail.name}/polars</span>
            <br />
            Body: <span className="text-zinc-300">{'{"source":"xfoil","method":"xfoil","label":"Re sweep Ncrit 9","mach":0.03,"ncrit":9,"points":[{"reynolds":100000,"alpha_deg":4,"cl":0.82,"cd":0.022,"cm":-0.08}]}'}</span>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ViewToggle({
  displayMode,
  setDisplayMode,
  autoSpin,
  setAutoSpin,
  showMesh,
  setShowMesh,
  flowMode,
  setFlowMode,
  hasAnalysis,
}) {
  return (
    <div className="absolute right-5 top-5 z-10 flex max-w-[min(720px,calc(100%-2.5rem))] flex-wrap items-center justify-end gap-2 lg:right-8 lg:top-6">
      <div className="flex rounded-md border border-zinc-800 bg-zinc-950/85 p-1 backdrop-blur">
        <button
          className={`inline-flex h-8 items-center gap-2 rounded px-2.5 text-xs transition ${
            displayMode === 'shaded' ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:text-zinc-200'
          }`}
          type="button"
          onClick={() => setDisplayMode('shaded')}
        >
          <Boxes className="h-3.5 w-3.5" aria-hidden="true" />
          Shaded
        </button>
        <button
          className={`inline-flex h-8 items-center gap-2 rounded px-2.5 text-xs transition ${
            displayMode === 'wireframe'
              ? 'bg-zinc-800 text-white'
              : 'text-zinc-500 hover:text-zinc-200'
          }`}
          type="button"
          onClick={() => setDisplayMode('wireframe')}
        >
          <Grid3X3 className="h-3.5 w-3.5" aria-hidden="true" />
          Wire
        </button>
      </div>
      <button
        className={`inline-flex h-10 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/85 px-3 text-xs transition backdrop-blur ${
          showMesh ? 'text-white' : 'text-zinc-500 hover:text-zinc-200'
        }`}
        type="button"
        onClick={() => setShowMesh((current) => !current)}
        title={showMesh ? 'Hide mesh' : 'Show mesh'}
        aria-pressed={showMesh}
      >
        {showMesh ? (
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {showMesh ? 'Mesh' : 'Hidden'}
      </button>
      <button
        className={`inline-flex h-10 items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/85 px-3 text-xs transition backdrop-blur ${
          autoSpin ? 'text-white' : 'text-zinc-500 hover:text-zinc-200'
        }`}
        type="button"
        onClick={() => setAutoSpin((current) => !current)}
        title={autoSpin ? 'Pause rotation' : 'Resume rotation'}
        aria-pressed={autoSpin}
      >
        {autoSpin ? (
          <Rotate3D className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <Pause className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        {autoSpin ? 'Rotating' : 'Paused'}
      </button>
      <div className="flex rounded-md border border-zinc-800 bg-zinc-950/85 p-1 backdrop-blur">
        {[
          ['off', 'Off'],
          ['velocity', 'Velocity'],
          ['loading', 'Load map'],
          ['vortices', 'Tip wake'],
        ].map(([value, label]) => (
          <button
            key={value}
            className={`inline-flex h-8 items-center gap-2 rounded px-2.5 text-xs transition ${
              flowMode === value ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:text-zinc-200'
            } ${!hasAnalysis && value !== 'off' ? 'pointer-events-none opacity-40' : ''}`}
            type="button"
            onClick={() => setFlowMode(value)}
            disabled={!hasAnalysis && value !== 'off'}
          >
            {value === 'off' ? null : <Waves className="h-3.5 w-3.5" aria-hidden="true" />}
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AeroLegend({ mode, hasAnalysis }) {
  if (mode === 'off') {
    return null;
  }

  const content = {
    velocity: {
      title: 'Velocity vectors',
      body: 'Cyan arrows show qualitative local flow direction. Longer arrows indicate higher local power loading.',
      scale: ['short = low power', 'long = high power'],
    },
    loading: {
      title: 'Blade loading map',
      body: 'Blocks sit above blade stations. Height and size follow local thrust contribution from BEMT.',
      scale: ['blue = lower load', 'orange = higher load', 'yellow = high alpha'],
    },
    vortices: {
      title: 'Tip wake',
      body: 'Purple helices show a qualitative tip vortex trail. This is a diagnostic wake sketch, not CFD.',
      scale: ['thicker = stronger tip loading'],
    },
  }[mode];

  if (!hasAnalysis || !content) {
    return null;
  }

  return (
    <div className="pointer-events-none absolute bottom-14 left-5 z-10 max-w-sm rounded-md border border-zinc-800 bg-zinc-950/85 p-3 text-xs text-zinc-400 backdrop-blur lg:left-8">
      <div className="mb-1 text-sm font-medium text-zinc-100">{content.title}</div>
      <p className="leading-5">{content.body}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        {content.scale.map((item) => (
          <span key={item} className="rounded border border-zinc-800 px-2 py-1 text-[11px] text-zinc-500">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function PropellerCanvas({
  previewGeometry,
  inputs,
  displayMode,
  autoSpin,
  showMesh,
  flowMode,
  analysisData,
  compact = false,
}) {
  return (
    <Canvas camera={{ position: [0, 0.1, compact ? 3.35 : 3.0], fov: compact ? 42 : 36 }}>
      <color attach="background" args={['#09090b']} />
      <fog attach="fog" args={['#09090b', 3.8, 6.2]} />
      <ambientLight intensity={0.82} />
      <directionalLight position={[2.8, 3.4, 4.2]} intensity={2.4} />
      <directionalLight position={[-3.5, -1.2, -2.6]} intensity={0.72} />
      <ReferenceRings />
      <gridHelper args={[3.4, 34, '#3f3f46', '#18181b']} />
      {showMesh && previewGeometry ? (
        <GeneratedPropeller
          geometry={previewGeometry}
          displayMode={displayMode}
          autoSpin={autoSpin}
        />
      ) : null}
      {showMesh && !previewGeometry ? (
        <PlaceholderPropeller
          bladeCount={inputs.blades}
          displayMode={displayMode}
          autoSpin={autoSpin}
        />
      ) : null}
      <AeroOverlay
        mode={flowMode}
        analysisData={analysisData}
        bladeCount={inputs.blades}
        autoSpin={autoSpin}
      />
      <SceneOrbitControls />
    </Canvas>
  );
}

function DatabaseWorkspace({
  project,
  inputs,
  previewGeometry,
  displayMode,
  autoSpin,
  showMesh,
  flowMode,
  analysisData,
  meshWatertight,
  stlFilename,
  stlUrl,
  reportsPanel,
}) {
  return (
    <section className="min-h-[620px] overflow-auto bg-zinc-950">
      <div className="mx-auto w-full max-w-[1600px] px-5 py-5 lg:px-8 lg:py-6">
        <div className="mb-5 grid gap-5 border-b border-zinc-900 pb-5 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-sm text-zinc-500">
                  <Database className="h-4 w-4" aria-hidden="true" />
                  Propeller database
                </div>
                <h2 className="mt-2 text-2xl font-semibold tracking-normal text-white">
                  Saved designs and aerodynamic reports
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-400">
                  Select a saved propeller to inspect the full station table, polar data and generated geometry state.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                {[
                  ['Project', project.name],
                  ['Airfoil', inputs.airfoil],
                  ['Mode', inputs.design_mode],
                  ['STL', stlUrl ? stlFilename : 'not loaded'],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-28 rounded-md border border-zinc-800 bg-zinc-950/70 p-2">
                    <div className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</div>
                    <div className="mt-1 truncate font-medium text-zinc-200">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <aside>
            <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/35">
              <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
                <div>
                  <div className="text-sm font-medium text-zinc-100">Render preview</div>
                  <div className="mt-1 text-xs text-zinc-500">
                    {previewGeometry ? 'Loaded generated mesh' : `${inputs.airfoil} placeholder`}
                  </div>
                </div>
                {meshWatertight ? (
                  <span className="rounded-md border border-zinc-800 px-2 py-1 text-xs text-zinc-500">
                    Watertight {meshWatertight}
                  </span>
                ) : null}
              </div>
              <div className="relative h-[240px] bg-[radial-gradient(circle_at_50%_42%,#18181b_0%,#09090b_55%,#09090b_100%)]">
                <PropellerCanvas
                  previewGeometry={previewGeometry}
                  inputs={inputs}
                  displayMode={displayMode}
                  autoSpin={autoSpin}
                  showMesh={showMesh}
                  flowMode={flowMode}
                  analysisData={analysisData}
                  compact
                />
              </div>
              <div className="grid grid-cols-3 gap-2 border-t border-zinc-800 p-3 text-xs text-zinc-500">
                <span>{inputs.blades} blades</span>
                <span>{inputs.diameter} m</span>
                <span>{inputs.rpm} rpm</span>
              </div>
            </div>
          </aside>
        </div>
        {reportsPanel}
      </div>
    </section>
  );
}

function App() {
  const [project, setProject] = useState(initialProject);
  const [inputs, setInputs] = useState(initialInputs);
  const [activeTab, setActiveTab] = useState('brief');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [stlUrl, setStlUrl] = useState('');
  const [stlFilename, setStlFilename] = useState('nova_propeller.stl');
  const [previewGeometry, setPreviewGeometry] = useState(null);
  const [meshWatertight, setMeshWatertight] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [analysisRuns, setAnalysisRuns] = useState([]);
  const [displayMode, setDisplayMode] = useState('shaded');
  const [autoSpin, setAutoSpin] = useState(true);
  const [showMesh, setShowMesh] = useState(true);
  const [flowMode, setFlowMode] = useState('off');
  const [apiStatus, setApiStatus] = useState('checking');
  const [airfoils, setAirfoils] = useState([]);
  const [savedPropellers, setSavedPropellers] = useState([]);
  const [selectedAirfoil, setSelectedAirfoil] = useState('NACA 4412');
  const [selectedAirfoilDetail, setSelectedAirfoilDetail] = useState(null);
  const [newAirfoil, setNewAirfoil] = useState({ name: '', notes: '' });
  const [airfoilEdit, setAirfoilEdit] = useState({ family: '', source: '', notes: '' });
  const [savedGeometryId, setSavedGeometryId] = useState(null);
  const [selectedPropellerDetail, setSelectedPropellerDetail] = useState(null);
  const stats = useDesignStats(inputs);
  const airfoilChoices = airfoils.length ? airfoils.map((airfoil) => airfoil.name) : airfoilOptions;

  const refreshDatabaseViews = async () => {
    const [airfoilsResponse, propellersResponse] = await Promise.all([
      fetch(apiPath('/airfoils')),
      fetch(apiPath('/propellers')),
    ]);
    if (airfoilsResponse.ok) {
      const airfoilData = await airfoilsResponse.json();
      setAirfoils(airfoilData);
      if (airfoilData.length && !airfoilData.some((airfoil) => airfoil.name === selectedAirfoil)) {
        setSelectedAirfoil(airfoilData[0].name);
      }
    }
    if (propellersResponse.ok) {
      setSavedPropellers(await propellersResponse.json());
    }
  };

  useEffect(() => {
    let isMounted = true;

    fetch(apiPath('/health'))
      .then((response) => {
        if (!response.ok) {
          throw new Error('Health check failed');
        }
        if (isMounted) {
          setApiStatus('online');
          refreshDatabaseViews().catch(() => {});
        }
      })
      .catch(() => {
        if (isMounted) {
          setApiStatus('offline');
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedAirfoil) {
      return;
    }

    fetch(apiPath(`/airfoils/${encodeURIComponent(selectedAirfoil)}`))
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        setSelectedAirfoilDetail(data);
        if (data) {
          setAirfoilEdit({
            family: data.family ?? '',
            source: data.source ?? '',
            notes: data.notes ?? '',
          });
        }
      })
      .catch(() => setSelectedAirfoilDetail(null));
  }, [selectedAirfoil]);

  useEffect(() => {
    return () => {
      if (stlUrl) {
        URL.revokeObjectURL(stlUrl);
      }
    };
  }, [stlUrl]);

  const updateInput = (key, value) => {
    setInputs((current) => ({ ...current, [key]: value }));
  };

  const handleGenerate = async (designMode = 'bemt', overrides = {}) => {
    setIsLoading(true);
    setError('');
    const payload = {
      ...inputs,
      ...overrides,
      design_mode: designMode,
      project_name: project.name,
    };
    setInputs(payload);
    setSavedGeometryId(null);

    try {
      const analysisResponse = await fetch(apiPath('/analyze-propeller'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!analysisResponse.ok) {
        let serverDetail = '';
        try {
          const errorBody = await analysisResponse.json();
          serverDetail = Array.isArray(errorBody.detail)
            ? errorBody.detail.map((item) => item.msg).join(' ')
            : errorBody.detail;
        } catch {
          serverDetail = '';
        }
        throw new Error(serverDetail || `Analysis failed with status ${analysisResponse.status}`);
      }

      const analysis = await analysisResponse.json();

      const response = await fetch(apiPath('/generate-propeller'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let serverDetail = '';
        try {
          const errorBody = await response.json();
          serverDetail = Array.isArray(errorBody.detail)
            ? errorBody.detail.map((item) => item.msg).join(' ')
            : errorBody.detail;
        } catch {
          serverDetail = '';
        }

        const message =
          response.status === 422
            ? 'Input fuori range: controlla spinta, RPM, diametro e numero pale.'
            : serverDetail || `Geometry generation failed with status ${response.status}`;
        throw new Error(message);
      }

      const blob = await response.blob();
      const arrayBuffer = await blob.arrayBuffer();
      const loader = new STLLoader();
      const geometry = loader.parse(arrayBuffer);
      const objectUrl = URL.createObjectURL(blob);
      const disposition = response.headers.get('content-disposition') ?? '';
      const filenameMatch = disposition.match(/filename="([^"]+)"/);
      const watertightHeader = response.headers.get('x-mesh-watertight');

      if (stlUrl) {
        URL.revokeObjectURL(stlUrl);
      }

      setPreviewGeometry((current) => {
        current?.dispose();
        return geometry;
      });
      setStlUrl(objectUrl);
      setStlFilename(filenameMatch?.[1] ?? 'nova_propeller.stl');
      setMeshWatertight(watertightHeader);
      setAnalysisData(analysis);
      setAnalysisRuns((current) => [
        ...current,
        {
          id: `${Date.now()}-${designMode}`,
          label: analysis.method,
          summary: analysis.summary,
        },
      ]);
      refreshDatabaseViews().catch(() => {});
      setApiStatus('online');
      setActiveTab('analysis');
    } catch (caughtError) {
      const isNetworkError = caughtError instanceof TypeError;
      setApiStatus(isNetworkError ? 'offline' : 'online');
      setError(
        caughtError.message ||
          'Backend non raggiungibile. Verifica che docker compose sia avviato.',
      );
      setActiveTab('geometry');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveGeometry = async () => {
    if (!analysisData) {
      return;
    }

    const payload = {
      ...inputs,
      project_name: project.name,
    };
    const response = await fetch(apiPath('/propellers'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_name: project.name,
        payload,
        analysis: analysisData,
      }),
    });

    if (response.ok) {
      const result = await response.json();
      setSavedGeometryId(result.id);
      refreshDatabaseViews().catch(() => {});
      fetch(apiPath(`/propellers/${result.id}`))
        .then((detailResponse) => (detailResponse.ok ? detailResponse.json() : null))
        .then((detail) => {
          if (detail) {
            setSelectedPropellerDetail(detail);
            setSelectedAirfoil(detail.airfoil);
          }
        })
        .catch(() => {});
    }
  };

  const handleSelectPropeller = async (id) => {
    const response = await fetch(apiPath(`/propellers/${id}`));
    if (!response.ok) {
      return;
    }

    const detail = await response.json();
    setSelectedPropellerDetail(detail);
    setSelectedAirfoil(detail.airfoil);
  };

  const handleOpenPropeller = async () => {
    if (!selectedPropellerDetail?.payload) {
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const payload = selectedPropellerDetail.payload;
      const response = await fetch(apiPath('/generate-propeller'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let serverDetail = '';
        try {
          const errorBody = await response.json();
          serverDetail = Array.isArray(errorBody.detail)
            ? errorBody.detail.map((item) => item.msg).join(' ')
            : errorBody.detail;
        } catch {
          serverDetail = '';
        }
        throw new Error(serverDetail || `Geometry generation failed with status ${response.status}`);
      }

      const blob = await response.blob();
      const arrayBuffer = await blob.arrayBuffer();
      const loader = new STLLoader();
      const geometry = loader.parse(arrayBuffer);
      const objectUrl = URL.createObjectURL(blob);
      const disposition = response.headers.get('content-disposition') ?? '';
      const filenameMatch = disposition.match(/filename="([^"]+)"/);
      const watertightHeader = response.headers.get('x-mesh-watertight');

      if (stlUrl) {
        URL.revokeObjectURL(stlUrl);
      }

      setProject((current) => ({
        ...current,
        name: selectedPropellerDetail.project_name,
      }));
      setInputs(payload);
      setPreviewGeometry((current) => {
        current?.dispose();
        return geometry;
      });
      setStlUrl(objectUrl);
      setStlFilename(filenameMatch?.[1] ?? `nova_propeller_${selectedPropellerDetail.id}.stl`);
      setMeshWatertight(watertightHeader);
      setAnalysisData(selectedPropellerDetail.analysis);
      setSavedGeometryId(selectedPropellerDetail.id);
      setApiStatus('online');
      setActiveTab('reports');
    } catch (caughtError) {
      const isNetworkError = caughtError instanceof TypeError;
      setApiStatus(isNetworkError ? 'offline' : 'online');
      setError(caughtError.message || 'Unable to open saved propeller.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateAirfoil = async () => {
    if (!newAirfoil.name.trim()) {
      return;
    }

    const response = await fetch(apiPath('/airfoils'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newAirfoil.name.trim(),
        family: 'custom',
        source: 'user',
        notes: newAirfoil.notes,
      }),
    });

    if (response.ok) {
      setSelectedAirfoil(newAirfoil.name.trim());
      setNewAirfoil({ name: '', notes: '' });
      refreshDatabaseViews().catch(() => {});
    }
  };

  const handleUpdateAirfoil = async () => {
    if (!selectedAirfoilDetail) {
      return;
    }

    const response = await fetch(apiPath(`/airfoils/${encodeURIComponent(selectedAirfoilDetail.name)}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: selectedAirfoilDetail.name,
        family: airfoilEdit.family,
        camber: selectedAirfoilDetail.camber,
        thickness: selectedAirfoilDetail.thickness,
        source: airfoilEdit.source,
        notes: airfoilEdit.notes,
      }),
    });

    if (response.ok) {
      const updated = await response.json();
      setSelectedAirfoilDetail({ ...updated, polars: selectedAirfoilDetail.polars });
      refreshDatabaseViews().catch(() => {});
    }
  };

  const handleDeleteAirfoil = async () => {
    if (!selectedAirfoilDetail) {
      return;
    }

    const response = await fetch(apiPath(`/airfoils/${encodeURIComponent(selectedAirfoilDetail.name)}`), {
      method: 'DELETE',
    });

    if (response.ok) {
      setSelectedAirfoilDetail(null);
      setSelectedAirfoil('NACA 4412');
      refreshDatabaseViews().catch(() => {});
    }
  };

  const handleDeletePropeller = async (id) => {
    const response = await fetch(apiPath(`/propellers/${id}`), {
      method: 'DELETE',
    });

    if (response.ok) {
      if (savedGeometryId === id) {
        setSavedGeometryId(null);
      }
      if (selectedPropellerDetail?.id === id) {
        setSelectedPropellerDetail(null);
      }
      refreshDatabaseViews().catch(() => {});
    }
  };

  const activeWorkflow = workflowTabs.find((tab) => tab.id === activeTab);
  const reportsPanel = (
    <ReportsPanel
      airfoils={airfoils}
      selectedAirfoil={selectedAirfoil}
      setSelectedAirfoil={setSelectedAirfoil}
      selectedAirfoilDetail={selectedAirfoilDetail}
      savedPropellers={savedPropellers}
      selectedPropellerDetail={selectedPropellerDetail}
      newAirfoil={newAirfoil}
      setNewAirfoil={setNewAirfoil}
      airfoilEdit={airfoilEdit}
      setAirfoilEdit={setAirfoilEdit}
      onSelectPropeller={handleSelectPropeller}
      onOpenPropeller={handleOpenPropeller}
      onCreateAirfoil={handleCreateAirfoil}
      onUpdateAirfoil={handleUpdateAirfoil}
      onDeleteAirfoil={handleDeleteAirfoil}
      onDeletePropeller={handleDeletePropeller}
      isLoading={isLoading}
    />
  );

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="grid min-h-screen grid-cols-1 xl:grid-cols-[460px_minmax(0,1fr)]">
        <aside className="border-b border-zinc-800 bg-zinc-950/95 px-5 py-5 xl:border-b-0 xl:border-r xl:px-6">
          <div className="flex min-h-full flex-col gap-6">
            <header className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2 text-sm text-zinc-500">
                  <Sparkles className="h-4 w-4" aria-hidden="true" />
                  Nova Propeller Studio
                </div>
                <span
                  className={`rounded-md border px-2 py-1 text-xs ${
                    apiStatus === 'online'
                      ? 'border-emerald-900/70 text-emerald-300'
                      : apiStatus === 'offline'
                        ? 'border-red-900/70 text-red-300'
                        : 'border-zinc-800 text-zinc-500'
                  }`}
                >
                  API {apiStatus}
                </span>
              </div>
              <div>
                <h1 className="text-2xl font-semibold tracking-normal text-white">
                  Propeller workflow
                </h1>
                <p className="mt-2 max-w-sm text-sm leading-6 text-zinc-400">
                  Move from preliminary sizing to generated STL and export checks.
                </p>
              </div>
              <WorkflowTabs
                activeTab={activeTab}
                setActiveTab={setActiveTab}
                hasGeometry={Boolean(previewGeometry)}
              />
            </header>

            <div className="flex items-center justify-between border-b border-zinc-900 pb-3">
              <div>
                <div className="text-xs uppercase tracking-wide text-zinc-500">
                  Active Phase
                </div>
                <div className="mt-1 text-sm font-medium text-zinc-100">
                  {activeWorkflow?.title}
                </div>
              </div>
              <FileDown className="h-4 w-4 text-zinc-600" aria-hidden="true" />
            </div>

            {activeTab === 'brief' ? (
              <PreliminaryPanel
                project={project}
                setProject={setProject}
                inputs={inputs}
                updateInput={updateInput}
                stats={stats}
                onNext={() => setActiveTab('geometry')}
              />
            ) : null}

            {activeTab === 'geometry' ? (
              <GeometryPanel
                inputs={inputs}
                updateInput={updateInput}
                isLoading={isLoading}
                onGenerate={handleGenerate}
                error={error}
                airfoilChoices={airfoilChoices}
              />
            ) : null}

            {activeTab === 'optimize' ? (
              <OptimizePanel
                inputs={inputs}
                updateInput={updateInput}
                isLoading={isLoading}
                onGenerate={handleGenerate}
                error={error}
                airfoilChoices={airfoilChoices}
              />
            ) : null}

            {activeTab === 'analysis' ? (
              <AnalysisPanel
                project={project}
                stats={stats}
                analysisData={analysisData}
                analysisRuns={analysisRuns}
                previewGeometry={previewGeometry}
                meshWatertight={meshWatertight}
                stlUrl={stlUrl}
                stlFilename={stlFilename}
                onGenerate={handleGenerate}
                onSaveGeometry={handleSaveGeometry}
                isGeometrySaved={Boolean(savedGeometryId)}
                isLoading={isLoading}
              />
            ) : null}

            {activeTab === 'reports' ? (
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 p-4">
                <div className="flex items-start gap-3">
                  <Database className="mt-0.5 h-4 w-4 text-zinc-500" aria-hidden="true" />
                  <div>
                    <h2 className="text-sm font-medium text-zinc-100">Database workspace</h2>
                    <p className="mt-1 text-xs leading-5 text-zinc-500">
                      The database view uses the main workspace to give tables, reports and polar data more room.
                    </p>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </aside>

        {activeTab === 'reports' ? (
          <DatabaseWorkspace
            project={project}
            inputs={inputs}
            previewGeometry={previewGeometry}
            displayMode={displayMode}
            autoSpin={autoSpin}
            showMesh={showMesh}
            flowMode={flowMode}
            analysisData={analysisData}
            meshWatertight={meshWatertight}
            stlFilename={stlFilename}
            stlUrl={stlUrl}
            reportsPanel={reportsPanel}
          />
        ) : (
        <section className="relative min-h-[620px] overflow-hidden bg-[radial-gradient(circle_at_50%_42%,#18181b_0%,#09090b_46%,#09090b_100%)]">
          <div className="absolute left-5 top-5 z-10 flex max-w-[calc(100%-180px)] flex-wrap items-center gap-2 text-xs text-zinc-500 lg:left-8 lg:top-6">
            <span className="rounded-md border border-zinc-800 bg-zinc-950/80 px-2.5 py-1">
              {project.name}
            </span>
            <span className="rounded-md border border-zinc-800 bg-zinc-950/80 px-2.5 py-1">
              {previewGeometry ? 'Generated STL' : `${inputs.airfoil} standby`}
            </span>
            <span className="rounded-md border border-zinc-800 bg-zinc-950/80 px-2.5 py-1">
              {inputs.design_mode}
            </span>
            {meshWatertight ? (
              <span className="rounded-md border border-zinc-800 bg-zinc-950/80 px-2.5 py-1">
                Watertight {meshWatertight}
              </span>
            ) : null}
          </div>

          <ViewToggle
            displayMode={displayMode}
            setDisplayMode={setDisplayMode}
            autoSpin={autoSpin}
            setAutoSpin={setAutoSpin}
            showMesh={showMesh}
            setShowMesh={setShowMesh}
            flowMode={flowMode}
            setFlowMode={setFlowMode}
            hasAnalysis={Boolean(analysisData)}
          />

          <AeroLegend mode={flowMode} hasAnalysis={Boolean(analysisData)} />

          {!analysisData ? (
            <div className="pointer-events-none absolute bottom-14 left-5 z-10 rounded-md border border-zinc-800 bg-zinc-950/85 px-3 py-2 text-xs text-zinc-500 backdrop-blur lg:left-8">
              Run BEMT or Optimize to enable velocity, load and wake overlays.
            </div>
          ) : null}

          {isLoading ? (
            <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center bg-zinc-950/20">
              <div className="flex items-center gap-3 rounded-md border border-zinc-800 bg-zinc-950/85 px-4 py-3 text-sm text-zinc-300 backdrop-blur">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Solving blade stations
              </div>
            </div>
          ) : null}

          <PropellerCanvas
            previewGeometry={previewGeometry}
            inputs={inputs}
            displayMode={displayMode}
            autoSpin={autoSpin}
            showMesh={showMesh}
            flowMode={flowMode}
            analysisData={analysisData}
          />

          <div className="pointer-events-none absolute inset-x-0 bottom-0 border-t border-zinc-900 bg-zinc-950/75 px-5 py-3 backdrop-blur-sm lg:px-8">
            <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-500">
              <span>
                {inputs.blades} blades | {inputs.diameter} m | {inputs.rpm} rpm | {displayMode} | {showMesh ? 'mesh visible' : 'mesh hidden'} | aero {flowMode}
              </span>
              <span>{stlUrl ? stlFilename : `${project.mission} | ${inputs.airfoil}`}</span>
            </div>
          </div>
        </section>
        )}
      </div>
    </main>
  );
}

export default App;
