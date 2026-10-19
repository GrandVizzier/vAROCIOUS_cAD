import { useEffect, useState } from "react";
import { Result, SimSetup, SimStatus, cancelSim, ghz, setSimulation, startSim } from "./api";

const NUM = /^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$/;
/** frequencies are stored as SI expressions (Hz); the form shows plain numbers in GHz */
const toForm = (expr: string) => (NUM.test(expr) ? String(+(parseFloat(expr) / 1e9).toPrecision(9)) : expr);
const toStore = (text: string) => (NUM.test(text) ? `${text.trim()}e9` : text.trim());

function defaults(r: Result): SimSetup {
  const f0 = "f0" in r.values;
  return {
    solver: "openems",
    sweep: { start: f0 ? "0.8*f0" : "1e9", stop: f0 ? "1.2*f0" : "3e9", points: 401 },
    fields_at: f0 ? ["f0"] : [],
    mesh: { cells_per_wavelength: 20, ratio: 1.4 },
    absorber: "PML_8",
    end_criteria_db: -40,
    max_timesteps: 300000,
  };
}

export default function AnalysisTab({ id, r, source, readonly, sim, onError }: {
  id: string; r: Result; source: string; readonly: boolean; sim: SimStatus | null;
  onError: (e: string) => void;
}) {
  const stored: SimSetup | undefined = (() => { try { return JSON.parse(source).simulation; } catch { return undefined; } })();
  const [s, setS] = useState<SimSetup>({ ...defaults(r), ...stored });
  const [dirty, setDirty] = useState(false);
  useEffect(() => { setS({ ...defaults(r), ...stored }); setDirty(false); }, [source]); // eslint-disable-line

  const edit = (patch: Partial<SimSetup>) => { setS({ ...s, ...patch }); setDirty(true); };
  const save = async () => {
    try { await setSimulation(id, s); setDirty(false); } catch (e) { onError(String(e)); }
  };
  const running = sim?.status === "running";
  // port problems are listed under Excitations already
  const problems = (sim?.problems ?? []).filter((p) => !p.startsWith("port "));
  const portsOk = r.ports.length > 0 && r.ports.every((p) => p.ok);
  if (dirty) problems.push("Setup has unsaved changes");
  if (!stored) problems.push("No setup saved yet");
  const analyze = async () => {
    try { await startSim(id); } catch (e) { onError(String(e)); }
  };
  const ev = r.simulation;

  return (
    <div className="analysis">
      <div className="dialog">
        <div className="dialog-title">Driven Solution Setup — Setup1</div>
        <fieldset disabled={readonly || running}>
          <legend>General</legend>
          <label>Solver<select value="openems" disabled><option value="openems">openEMS (FDTD, time domain)</option></select></label>
          <label>Absorbing boundary
            <select value={s.absorber} onChange={(e) => edit({ absorber: e.target.value as SimSetup["absorber"] })}>
              <option value="PML_8">PML (8 cells)</option><option value="MUR">Mur 1st order</option>
            </select>
          </label>
        </fieldset>

        <fieldset disabled={readonly || running}>
          <legend>Frequency Sweep (interpolating — one broadband run per excited port)</legend>
          <label>Start (GHz or Hz expr)
            <input value={toForm(s.sweep.start)} onChange={(e) => edit({ sweep: { ...s.sweep, start: toStore(e.target.value) } })} />
            <span className="eval">{ev && ghz(ev.sweep.start)}</span>
          </label>
          <label>Stop (GHz or Hz expr)
            <input value={toForm(s.sweep.stop)} onChange={(e) => edit({ sweep: { ...s.sweep, stop: toStore(e.target.value) } })} />
            <span className="eval">{ev && ghz(ev.sweep.stop)}</span>
          </label>
          <label>Points
            <input type="number" min={2} max={10001} value={s.sweep.points}
                   onChange={(e) => edit({ sweep: { ...s.sweep, points: +e.target.value } })} />
          </label>
          <label>Save fields at (GHz, comma separated)
            <input value={s.fields_at.map(toForm).join(", ")}
                   onChange={(e) => edit({ fields_at: e.target.value.split(",").map((x) => x.trim()).filter(Boolean).map(toStore) })} />
            <span className="eval">{ev?.fields_at.map(ghz).join(", ")}</span>
          </label>
        </fieldset>

        <fieldset disabled={readonly || running}>
          <legend>Mesh &amp; Convergence</legend>
          <label>Cells per wavelength (at stop freq, in the densest dielectric)
            <input type="number" min={6} max={100} value={s.mesh.cells_per_wavelength}
                   onChange={(e) => edit({ mesh: { ...s.mesh, cells_per_wavelength: +e.target.value } })} />
          </label>
          <label>Max grading ratio
            <input type="number" step={0.05} min={1.05} max={2} value={s.mesh.ratio}
                   onChange={(e) => edit({ mesh: { ...s.mesh, ratio: +e.target.value } })} />
          </label>
          <label>Energy end criterion (dB)
            <input type="number" min={-80} max={-10} value={s.end_criteria_db}
                   onChange={(e) => edit({ end_criteria_db: +e.target.value })} />
          </label>
          <label>Max timesteps
            <input type="number" min={1000} step={1000} value={s.max_timesteps}
                   onChange={(e) => edit({ max_timesteps: +e.target.value })} />
          </label>
        </fieldset>

        <div className="dialog-buttons">
          {readonly && <span className="dim">Example projects are read-only (Analyze still works)</span>}
          <button disabled={readonly || !dirty || running} onClick={save}>Save Setup</button>
        </div>
      </div>

      <div className="dialog side">
        <div className="dialog-title">Validation Check</div>
        <ul className="checks">
          <li className={portsOk ? "ok" : "bad"}>{portsOk ? "✓" : "⚠"} Excitations ({r.ports.length})</li>
          {r.ports.flatMap((p) => p.problems.map((m) => <li key={p.index + m} className="bad sub">port {p.index}: {m}</li>))}
          <li className={problems.length ? "bad" : "ok"}>{problems.length ? "⚠" : "✓"} Analysis setup</li>
          {problems.map((m) => <li key={m} className="bad sub">{m}</li>)}
          <li className={sim?.stale ? "bad" : "ok"}>
            {sim?.results ? (sim.stale ? "⚠ Results are older than the geometry" : "✓ Results up to date") : "• No results yet"}
          </li>
        </ul>
        <div className="dialog-buttons">
          {running
            ? <button className="danger" onClick={() => cancelSim(id).catch((e) => onError(String(e)))}>Abort</button>
            : <button className="primary" disabled={problems.length > 0 || !portsOk} onClick={analyze}>Analyze</button>}
        </div>
        {sim && sim.status !== "idle" && (
          <div className="progress-box">
            <div className="dim">{sim.status === "running" ? sim.stage : `Last run: ${sim.status}`}</div>
            <div className="bar"><div style={{ width: `${sim.progress}%` }} /></div>
            {sim.results && !running && (
              <div className="dim">{sim.results.cells.toLocaleString()} cells · {sim.results.seconds}s
                {sim.results.warnings.map((w) => <div key={w} className="warn">⚠ {w}</div>)}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
