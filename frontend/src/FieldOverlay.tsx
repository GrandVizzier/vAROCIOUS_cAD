import { useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { FieldPlane } from "./api";

export type FieldScale = "log" | "lin";
const DB_RANGE = 40;

/** HFSS-style rainbow: blue (low) -> cyan -> green -> yellow -> red (high) */
export const rainbow = (t: number) => new THREE.Color().setHSL((1 - Math.min(1, Math.max(0, t))) * 0.667, 1, 0.5);

/** magnitude -> [0,1] colour coordinate */
export function colorScale(maxMag: number, scale: FieldScale) {
  return scale === "log"
    ? (m: number) => (20 * Math.log10(Math.max(m, 1e-30) / maxMag) + DB_RANGE) / DB_RANGE
    : (m: number) => m / maxMag;
}

/** peak |E| per node and a robust max (99th percentile; port gaps spike) */
export function magnitudes(fp: FieldPlane) {
  const nu = fp.u.length, nv = fp.v.length, mag = new Float32Array(nu * nv);
  for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) {
    let s = 0;
    for (let c = 0; c < 3; c++) s += fp.re[c][i][j] ** 2 + fp.im[c][i][j] ** 2;
    mag[i * nv + j] = Math.sqrt(s);
  }
  const sorted = Float32Array.from(mag).sort();
  return { mag, max: sorted[Math.floor(sorted.length * 0.99)] || 1 };
}

export default function FieldOverlay({ fp, phase, scale, vectors }: {
  fp: FieldPlane; phase: number; scale: FieldScale; vectors: boolean;
}) {
  const k = "xyz".indexOf(fp.plane), ku = "xyz".indexOf(fp.u_axis), kv = "xyz".indexOf(fp.v_axis);
  const nu = fp.u.length, nv = fp.v.length;
  const { mag, max } = useMemo(() => magnitudes(fp), [fp]);

  const plane = useMemo(() => {
    const pos = new Float32Array(nu * nv * 3), col = new Float32Array(nu * nv * 3), idx: number[] = [];
    const t = colorScale(max, scale);
    for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) {
      const n = i * nv + j;
      pos[n * 3 + k] = fp.pos; pos[n * 3 + ku] = fp.u[i]; pos[n * 3 + kv] = fp.v[j];
      rainbow(t(mag[n])).toArray(col, n * 3);
      if (i < nu - 1 && j < nv - 1) idx.push(n, n + nv, n + 1, n + 1, n + nv, n + nv + 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.setIndex(idx);
    return g;
  }, [fp, mag, max, scale, k, ku, kv, nu, nv]);

  // arrows on a sub-grid (<= 28 per axis), uniform length, coloured by magnitude
  const step = [Math.max(1, Math.ceil(nu / 28)), Math.max(1, Math.ceil(nv / 28))];
  const nodes = useMemo(() => {
    const out: number[] = [];
    for (let i = 0; i < nu; i += step[0]) for (let j = 0; j < nv; j += step[1]) out.push(i * nv + j);
    return out;
  }, [nu, nv, step[0], step[1]]); // eslint-disable-line
  const len = 0.8 * Math.min(
    (fp.u[nu - 1] - fp.u[0]) / Math.max(1, Math.ceil(nu / step[0])),
    (fp.v[nv - 1] - fp.v[0]) / Math.max(1, Math.ceil(nv / step[1])));
  const cone = useMemo(() => new THREE.ConeGeometry(len * 0.22, len, 8).translate(0, len / 2, 0), [len]);
  const inst = useRef<THREE.InstancedMesh>(null);

  useLayoutEffect(() => {
    const m = inst.current;
    if (!m || !vectors) return;
    const c = Math.cos(phase), s = Math.sin(phase), t = colorScale(max, scale);
    const up = new THREE.Vector3(0, 1, 0), dir = new THREE.Vector3(), q = new THREE.Quaternion();
    const mat = new THREE.Matrix4(), p = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1);
    nodes.forEach((n, a) => {
      const i = Math.floor(n / nv), j = n % nv;
      dir.set(...([0, 1, 2].map((cc) => fp.re[cc][i][j] * c - fp.im[cc][i][j] * s) as [number, number, number]));
      const inst_mag = dir.length();
      p.setComponent(k, fp.pos).setComponent(ku, fp.u[i]).setComponent(kv, fp.v[j]);
      q.setFromUnitVectors(up, inst_mag > 0 ? dir.normalize() : up);
      mat.compose(p, q, inst_mag > 0 ? one : new THREE.Vector3(0, 0, 0));
      m.setMatrixAt(a, mat);
      m.setColorAt(a, rainbow(t(mag[n])));
    });
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  }, [nodes, phase, fp, max, scale, vectors, mag, k, ku, kv, nv]);

  return (
    <group>
      <mesh geometry={plane} raycast={() => null}>
        <meshBasicMaterial vertexColors side={THREE.DoubleSide} transparent opacity={vectors ? 0.55 : 0.85} depthWrite={false} />
      </mesh>
      {vectors && (
        <instancedMesh key={nodes.length + ":" + len} ref={inst} args={[cone, undefined, nodes.length]} raycast={() => null}>
          <meshBasicMaterial />
        </instancedMesh>
      )}
    </group>
  );
}
