import { useMemo } from "react";
import * as THREE from "three";
import { Canvas } from "@react-three/fiber";
import { Bounds, GizmoHelper, GizmoViewport, Grid, OrbitControls } from "@react-three/drei";
import { Obj, isTransparent, materialColor } from "./api";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1); // Z-up

function ObjectMesh({ obj, selected, wireframe, onSelect }: {
  obj: Obj; selected: boolean; wireframe: boolean; onSelect: (n: string) => void;
}) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(obj.positions, 3));
    g.setIndex(obj.indices);
    g.computeVertexNormals();
    return g;
  }, [obj]);
  const air = isTransparent(obj);
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
          color={materialColor(obj.material)}
          emissive={selected ? "#ff5a1f" : "#000000"}
          emissiveIntensity={selected ? 0.6 : 0}
          transparent={air}
          opacity={air ? (selected ? 0.25 : 0.1) : 1}
          depthWrite={!air}
          side={THREE.DoubleSide}
          // sheets sit on volume faces: pull them forward to avoid z-fighting
          polygonOffset={sheet}
          polygonOffsetFactor={sheet ? -1 : 0}
          polygonOffsetUnits={sheet ? -4 : 0}
          metalness={obj.material === "PEC" ? 0.2 : 0}
          roughness={0.5}
        />
      </mesh>
      {wireframe && (
        <mesh geometry={geom} raycast={() => null}>
          <meshBasicMaterial wireframe color="#000000" transparent opacity={air ? 0.15 : 0.35} />
        </mesh>
      )}
    </group>
  );
}

export default function Viewport({ fitKey, objects, hidden, selected, wireframe, onSelect }: {
  fitKey: string; objects: Obj[]; hidden: Set<string>; selected: string | null;
  wireframe: boolean; onSelect: (n: string | null) => void;
}) {
  const visible = objects.filter((o) => !hidden.has(o.name) && o.indices.length);
  return (
    <Canvas camera={{ position: [150, -150, 120], fov: 40, near: 0.1, far: 1e6 }}
            onPointerMissed={() => onSelect(null)}>
      <color attach="background" args={["#14161a"]} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[1, -1, 2]} intensity={1.6} />
      <directionalLight position={[-1, 1, -1]} intensity={0.4} />
      <Bounds key={fitKey} fit clip observe={false} margin={1.3}>
        {/* geometry is in meters; display in mm */}
        <group scale={1000}>
          {visible.map((o) => (
            <ObjectMesh key={o.name} obj={o} selected={o.name === selected}
                        wireframe={wireframe} onSelect={onSelect} />
          ))}
        </group>
      </Bounds>
      <Grid rotation={[Math.PI / 2, 0, 0]} cellSize={10} sectionSize={50} infiniteGrid
            fadeDistance={2000} cellColor="#2a2e35" sectionColor="#3b414b" />
      <OrbitControls makeDefault />
      <GizmoHelper alignment="bottom-right" margin={[70, 70]}>
        <GizmoViewport axisColors={["#e5534b", "#57ab5a", "#539bf5"]} labelColor="#fff" />
      </GizmoHelper>
    </Canvas>
  );
}
