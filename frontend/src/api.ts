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
};

export type Build = {
  id: string;
  status: "building" | "ok" | "error";
  error: string | null;
  result: Result | null;
  source: string;
};

export type ProjectInfo = { id: string; mtime: number; status: string; readonly: boolean };

export type WsMsg = { type: "build" | "deleted"; id: string; status?: string; new?: boolean };

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

export const MATERIAL_COLORS: Record<string, string> = {
  PEC: "#d4a017",
  copper: "#c87533",
  FR4: "#3a8f4a",
  PTFE: "#e8e8e8",
  air: "#6fa8dc",
};

export function materialColor(m: string) {
  if (MATERIAL_COLORS[m]) return MATERIAL_COLORS[m];
  let h = 0;
  for (const ch of m) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 55%)`;
}

export const isTransparent = (o: Obj) => o.material === "air";
