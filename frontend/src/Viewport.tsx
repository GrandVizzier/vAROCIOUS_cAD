import { useMemo } from "react";
import type { ReactNode } from "react";
import * as THREE from "three";
import { Canvas } from "@react-three/fiber";
import { Bounds, Edges, GizmoHelper, GizmoViewport, Grid, OrbitControls } from "@react-three/drei";
import { Obj, materialColor, opacity } from "./api";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1); // Z-up

const SELECT = "#e040fb"; // HFSS-style magenta selection

function ObjectMesh({ obj, selected, wireframe, onSelect, dark }: {
  obj: Obj; selected: boolean; wireframe: boolean; onSelect: (n: string) => void; dark: boolean;
}) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(obj.positions, 3));
    g.setIndex(obj.indices);
    g.computeVertexNormals();
    return g;
  }, [obj]);
  const air = obj.material === "air";
  const alpha = opacity(obj);
  const sheet = obj.dim === 2;
  return (
    <group>
      <mesh
        geometry={geom}
        // air encloses everything: let clicks pass through it (select it from the tree)
        raycast={air ? () => null : undefined}
        onClick={(e) => { e.stopPropagation(); onSelect(obj.name); }}
      >
        <meshStandardMaterial
          color={selected ? SELECT : materialColor(obj.material)}
          transparent={alpha < 1}
          opacity={selected ? Math.max(alpha, 0.25) : alpha}
          depthWrite={alpha === 1}
          side={THREE.DoubleSide}
          // sheets sit on volume faces: push volumes back so sheets (and all edge lines) win
          polygonOffset={!sheet}
          polygonOffsetFactor={sheet ? 0 : 2}
          polygonOffsetUnits={sheet ? 0 : 4}
          metalness={0}
          roughness={0.6}
        />
        {/* CAD feature edges (not mesh edges), like the HFSS modeler */}
        <Edges threshold={20} color={selected ? "#8e00a8" : air ? (dark ? "#8090a0" : "#55606e") : dark ? "#d0d6de" : "#000000"} />
      </mesh>
      {wireframe && (
        <mesh geometry={geom} raycast={() => null}>
          <meshBasicMaterial wireframe color={dark ? "#c0c8d0" : "#1f2a38"} transparent opacity={air ? 0.12 : 0.3} />
        </mesh>
      )}
    </group>
  );
}

export default function Viewport({ fitKey, objects, hidden, selected, wireframe, grid, onSelect, children, dark = false }: {
  fitKey: string; objects: Obj[]; hidden: Set<string>; selected: string | null;
  wireframe: boolean; grid: boolean; onSelect: (n: string | null) => void; children?: ReactNode; dark?: boolean;
}) {
  const visible = objects.filter((o) => !hidden.has(o.name) && o.indices.length);
  return (
    // transparent canvas over the CSS gradient background (.viewport)
    <Canvas gl={{ alpha: true, antialias: true }}
            camera={{ position: [150, -150, 120], fov: 35, near: 0.1, far: 1e6 }}
            onPointerMissed={() => onSelect(null)}>
      <ambientLight intensity={0.9} />
      <directionalLight position={[1, -1, 2]} intensity={1.4} />
      <directionalLight position={[-1, 1, -1]} intensity={0.5} />
      <Bounds key={fitKey} fit clip observe={false} margin={1.3}>
        {/* geometry is in meters; display in mm */}
        <group scale={1000}>
          {visible.map((o) => (
            <ObjectMesh key={o.name} obj={o} selected={o.name === selected}
                        wireframe={wireframe} onSelect={onSelect} dark={dark} />
          ))}
        </group>
      </Bounds>
      {/* overlays (field plots) live outside Bounds so they don't change the camera fit */}
      <group scale={1000}>{children}</group>
      {grid && (
        <Grid rotation={[Math.PI / 2, 0, 0]} cellSize={10} sectionSize={50} infiniteGrid
              fadeDistance={2000} cellColor="#b8c2cf" sectionColor="#8f9bab" />
      )}
      <OrbitControls makeDefault />
      <GizmoHelper alignment="bottom-left" margin={[70, 70]}>
        <GizmoViewport axisColors={["#d32f2f", "#2e7d32", "#1565c0"]} labelColor="#fff" />
      </GizmoHelper>
    </Canvas>
  );
}
