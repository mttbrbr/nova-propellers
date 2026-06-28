import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import * as THREE from 'three';


function SceneControls() {
  const { camera, gl } = useThree();

  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = true;
    controls.minDistance = 1.4;
    controls.maxDistance = 7;
    return () => controls.dispose();
  }, [camera, gl]);

  return null;
}


function WhiteGrid() {
  const ref = useRef();

  useEffect(() => {
    if (!ref.current) return;
    ref.current.material.transparent = true;
    ref.current.material.opacity = 0.28;
  }, []);

  return (
    <gridHelper
      ref={ref}
      args={[4, 32, '#ffffff', '#71717a']}
      rotation={[Math.PI / 2, 0, 0]}
    />
  );
}


function Propeller({ geometry, displayMode }) {
  const ref = useRef();
  const normalized = useMemo(() => {
    const clone = geometry.clone();
    clone.center();
    clone.computeVertexNormals();
    clone.computeBoundingSphere();
    return {
      geometry: clone,
      scale: 2.2 / Math.max((clone.boundingSphere?.radius || 1) * 2, 1e-6),
    };
  }, [geometry]);

  useEffect(() => () => normalized.geometry.dispose(), [normalized]);
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.z += delta * 0.12;
  });

  return (
    <mesh
      ref={ref}
      geometry={normalized.geometry}
      scale={normalized.scale}
      rotation={[0.68, 0.12, 0]}
    >
      <meshPhysicalMaterial
        color={displayMode === 'mesh' ? '#ffffff' : '#e4e4e7'}
        metalness={displayMode === 'mesh' ? 0 : 0.32}
        roughness={displayMode === 'mesh' ? 0.15 : 0.28}
        clearcoat={displayMode === 'mesh' ? 0 : 0.65}
        clearcoatRoughness={0.22}
        wireframe={displayMode === 'mesh'}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}


export default function PropellerViewport({ geometry, displayMode }) {
  return (
    <Canvas camera={{ position: [0, -3.2, 2.25], fov: 36 }} dpr={[1, 2]}>
      <color attach="background" args={['#08080a']} />
      <hemisphereLight args={['#ffffff', '#18181b', 1.5]} />
      <directionalLight position={[3, -4, 6]} intensity={4.2} color="#ffffff" />
      <directionalLight position={[-4, 2, 2]} intensity={2.2} color="#93c5fd" />
      <pointLight position={[0, 1, -3]} intensity={1.6} color="#c4b5fd" />
      <WhiteGrid />
      {geometry && <Propeller geometry={geometry} displayMode={displayMode} />}
      <SceneControls />
    </Canvas>
  );
}
