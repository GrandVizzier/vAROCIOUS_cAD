export type Obj = {
  name: string;
  op: string;
  material: string;
  dim: number;
  entities: number;
  positions: number[]; // meters
  indices: number[];
};

export type Result = {
  name: string;
  description: string;
  units: string;
  variables: Record<string, string>;
  values: Record<string, number>;
  objects: Obj[];
  groups: { name: string; dim: number; count: number }[];
  stats: { volumes: number; surfaces: number; nodes?: number; tetrahedra?: number };
  warnings: string[];
  files: { msh?: string; step?: string };
  build_seconds: number;
  ports: PortInfo[];
  simulation: SimSetupValues | null;
  materials: Record<string, { metal: boolean; epsr?: number; tand?: number } | null>;
};

export type PortInfo = {
  index: number; target: string; type: string; direction: string; impedance: number | null;
  excite: boolean; ok: boolean; problems: string[];
};

export type SimSetup = {
  solver: "openems";
  sweep: { start: string; stop: string; points: number };
  fields_at: string[];
  mesh: { cells_per_wavelength: number; ratio: number };
  absorber: "PML_8" | "MUR";
  end_criteria_db: number;
  max_timesteps: number;
};

/** evaluated setup as returned in the build result (Hz) */
export type SimSetupValues = Omit<SimSetup, "sweep" | "fields_at"> & {
  sweep: { start: number; stop: number; points: number }; fields_at: number[];
};

export type SimResults = {
  freqs: number[];
  S: Record<string, [number[], number[]]>; // "i,j" -> [re, im]
  Z: Record<string, [number[], number[]]>; // port -> [re, im]
  ports: { index: number; impedance: number }[];
  fields_at: number[];
  cells: number;
  seconds: number;
  warnings: string[];
};

export type SimStatus = {
  status: "idle" | "running" | "done" | "error" | "cancelled";
  progress: number;
  stage: string;
  log: string[];
  problems: string[];
  results: SimResults | null;
  stale: boolean;
};

export type FieldPlane = {
  freq: number; plane: "x" | "y" | "z"; pos: number; u_axis: string; v_axis: string;
  u: number[]; v: number[]; re: number[][][]; im: number[][][];
  range: Record<"x" | "y" | "z", [number, number]>;
};

export type Build = {
  id: string;
  status: "building" | "ok" | "error";
  error: string | null;
  result: Result | null;
  source: string;
};

export type ProjectInfo = { id: string; mtime: number; status: string; readonly: boolean };

export type WsMsg = {
  type: "build" | "deleted" | "sim"; id: string; status?: string; new?: boolean;
  progress?: number; stage?: string;
};

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()) || r.statusText}`);
  return r.json();
}

export const listProjects = () => fetch("/projects").then((r) => json<ProjectInfo[]>(r));
export const getBuild = (id: string) => fetch(`/build/${id}`).then((r) => json<Build>(r));
export const setVariables = (id: string, vars: Record<string, string>) =>
  fetch(`/projects/${id}/variables`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(vars),
  }).then((r) => json<{ ok: boolean }>(r));

const put = (url: string, body: unknown) =>
  fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => json<{ ok: boolean }>(r));
export const setSimulation = (id: string, s: SimSetup) => put(`/projects/${id}/simulation`, s);
export const getSim = (id: string) => fetch(`/sim/${id}`).then((r) => json<SimStatus>(r));
export const startSim = (id: string) => fetch(`/simulate/${id}`, { method: "POST" }).then((r) => json<{ ok: boolean }>(r));
export const cancelSim = (id: string) =>
  fetch(`/simulate/${id}/cancel`, { method: "POST" }).then((r) => json<{ ok: boolean }>(r));
export const getField = (id: string, f: number, plane: string, pos: number) =>
  fetch(`/sim/${id}/field?f=${f}&plane=${plane}&pos=${pos}`).then((r) => json<FieldPlane>(r));

export const ghz = (hz: number) => `${+(hz / 1e9).toPrecision(6)} GHz`;

export const MATERIAL_COLORS: Record<string, string> = {
  PEC: "#d4a017",
  copper: "#c87533",
  FR4: "#3a8f4a",
  PTFE: "#e8e8e8",
  air: "#6fa8dc",
  TLY5: "#9fb0c2",
  RO4450F: "#d6cf8f",
};

const METALS = new Set(["PEC", "copper", "Cu"]);

/** air nearly invisible, dielectrics translucent (to see vias/probes inside), metals opaque */
export const opacity = (o: Obj) =>
  o.material === "air" ? 0.06 : METALS.has(o.material) || o.dim === 2 ? 1 : 0.4;

export function materialColor(m: string) {
  if (MATERIAL_COLORS[m]) return MATERIAL_COLORS[m];
  let h = 0;
  for (const ch of m) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 55%)`;
}
