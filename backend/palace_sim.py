"""Palace (FEM, frequency domain) backend: build result + .msh -> Palace config -> run ->
S-parameters, Z, and E-field snapshots (probed on a grid, same fields.npz as openEMS).

Palace reads the build's Gmsh mesh directly. Physical group ids are Palace attributes: volume groups
`mat:<material>` become domains, surface groups `bc:PEC` / `bc:radiation` / `port:<i>` boundaries.
The mesh is in SI meters (L0 = 1). Interior PEC sheets and port sheets are internal boundaries;
metal volumes are left out of the Palace mesh (PEC-walled holes).
"""
import json
import os
import re
import shutil
import subprocess
import time
from collections import deque
from pathlib import Path

import numpy as np

from .openems_sim import SimError, _domain

ROOT = Path(__file__).resolve().parents[1]
UNSUPPORTED = ("bc:master", "bc:slave", "bc:floquet")
S_DB = re.compile(r"\|S\[(\d+)\]\[(\d+)\]\| \(dB\)")
SWEEP_IT = re.compile(r"It (\d+)/(\d+):.*?(?:solve (\d+)/(\d+))?\)")
EXCITATION = re.compile(r"(?:Adding|Sweeping) excitation index \d+ \((\d+)/(\d+)\)")
SOLVED = re.compile(r"solver (?:converged|did not converge) in \d+ iterations")  # one linear solve done
ONLINE = "Beginning fast frequency sweep online phase"
MAX_SAMPLES = 20  # Palace's AdaptiveMaxSamples default: PROM samples (= solves) per excitation
PROBE_E = re.compile(r"(Re|Im)\{E_([xyz])\[(\d+)\]\} \(V/m\)")


def palace_binary():
    """$PALACE, then tools/palace/bin/palace (README: Palace setup), then PATH."""
    for c in (os.environ.get("PALACE"), ROOT / "tools" / "palace" / "bin" / "palace", shutil.which("palace")):
        if c and Path(c).is_file():
            return str(c)
    return None


def preflight(result):
    """Everything that would make a run pointless. Returns a list of problems (empty = go)."""
    problems = []
    sim = result.get("simulation")
    if not sim:
        problems.append('no "simulation" block in the project')
    elif sim["solver"] != "palace":
        problems.append(f"solver '{sim['solver']}' is not Palace")
    groups = {g["name"] for g in result["groups"]}
    bad = sorted(g for g in groups if g.startswith(UNSUPPORTED))
    if bad:
        # ponytail: Palace has periodic + Floquet ports; map master/slave pairs when a cell needs it
        problems.append(f"periodic/Floquet boundaries ({', '.join(bad)}) are not set up for Palace yet")
    if "bc:radiation" not in groups:
        problems.append('Palace needs a radiation boundary on the air box '
                        '({"type": "radiation", "target": "<air box>"})')
    if not result["files"].get("palace_msh"):
        problems.append("the build has no Palace mesh (.palace.msh); rebuild the project")
    if not result["ports"]:
        problems.append("no ports defined")
    elif not any(p["excite"] for p in result["ports"]):
        problems.append("no excited port")
    for p in result["ports"]:
        if not p["ok"]:
            problems.append(f"port {p['index']} ('{p['target']}'): " + "; ".join(p["problems"]))
    for m, v in result["materials"].items():
        if v is None:
            problems.append(f"material '{m}' has no epsr/tand; add it to \"materials\"")
    if palace_binary() is None:
        problems.append("Palace is not installed (expected tools/palace/bin/palace, "
                        "or set PALACE=<path to palace>)")
    return problems


def config(result, mesh_path, post_dir):
    """The Palace configuration (a dict; written as config.json)."""
    sim = result["simulation"]
    p = sim["palace"]
    gid = {(g["dim"], g["name"]): g["id"] for g in result["groups"]}
    materials = []
    for (dim, name), i in sorted(gid.items(), key=lambda kv: kv[1]):
        if dim != 3:
            continue
        mat = result["materials"].get(name.removeprefix("mat:"))
        if mat is not None and mat["metal"]:
            continue  # metal volumes are holes in the .palace.msh (engine.build); their skin is bc:PEC
        if mat is None:
            materials.append({"Attributes": [i]})
        else:
            materials.append({"Attributes": [i], "Permittivity": mat["epsr"], "LossTan": mat["tand"]})
    boundaries = {"Absorbing": {"Attributes": [gid[(2, "bc:radiation")]], "Order": p["absorbing_order"]}}
    if (2, "bc:PEC") in gid:
        boundaries["PEC"] = {"Attributes": [gid[(2, "bc:PEC")]]}
    # integer excitation = own port index: one run sweeps each excited port in turn (full S matrix)
    boundaries["LumpedPort"] = [
        {"Index": q["index"], "R": q["impedance"], "Excitation": q["index"] if q["excite"] else 0,
         "Attributes": [gid[(2, f"port:{q['index']}")]], "Direction": q["direction"].upper()}
        for q in result["ports"]]
    return {
        "Problem": {"Type": "Driven", "Verbose": 2, "Output": str(post_dir)},
        "Model": {"Mesh": str(mesh_path), "L0": 1.0},
        "Domains": {"Materials": materials},
        "Boundaries": boundaries,
        "Solver": {
            "Order": p["order"],
            "Device": "CPU",
            "Driven": {
                "Samples": [{"Type": "Linear", "MinFreq": sim["sweep"]["start"] / 1e9,
                             "MaxFreq": sim["sweep"]["stop"] / 1e9, "NSample": sim["sweep"]["points"]}],
                "AdaptiveTol": p["adaptive_tol"],
            },
            # ComplexCoarseSolve: 21 vs 108 GMRES iterations, 1.8x faster per solve, same S11, on the
            # 28/39 GHz stacked patch (286k unknowns); ~20% more memory
            "Linear": {"Type": "Default", "KSPType": "GMRES", "Tol": 1e-8, "MaxIts": 300,
                       "ComplexCoarseSolve": True},
        },
    }


class Progress:
    """Palace output line -> (percent or None, stage or None); one instance per run.

    Adaptive sweep: the offline phase (most of the runtime) does one full solve per PROM sample,
    port by port; each excited port gets an equal share of 85 %, filled up to MAX_SAMPLES solves
    (it jumps ahead when a port converges earlier). The online sweep ("It a/b", cheap) takes the
    rest. Without the adaptive sweep every "It a/b" line is one full solve."""

    def __init__(self, sim):
        self.adaptive = sim["palace"]["adaptive_tol"] > 0
        self.port, self.ports, self.solves, self.online = 1, 1, 0, False

    def __call__(self, line):
        if ONLINE in line:
            self.online = True
            return 85.0, "fast sweep"
        if self.adaptive and not self.online:
            m = EXCITATION.search(line)
            if m:
                self.port, self.ports, self.solves = int(m.group(1)), int(m.group(2)), 0
                return self._offline(), f"port {self.port}/{self.ports}: starting"
            if SOLVED.search(line):
                self.solves += 1
                return self._offline(), f"port {self.port}/{self.ports}: solve {self.solves}"
        m = SWEEP_IT.search(line)
        if m:
            a, b = (int(m.group(3)), int(m.group(4))) if m.group(3) else (int(m.group(1)), int(m.group(2)))
            return (85 + 14 * a / b if self.adaptive else 99 * a / b), f"frequency {a}/{b}"
        return None, None

    def _offline(self):
        return 85 * (self.port - 1 + min(self.solves, MAX_SAMPLES) / MAX_SAMPLES) / self.ports


def read_port_s(path):
    """port-S.csv -> (freqs Hz, {"i,j": [re, im]}); S[i][j] = output port i, excitation j."""
    with open(path, encoding="utf-8") as f:
        header = [h.strip() for h in f.readline().split(",")]
    data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    S = {}
    for c, h in enumerate(header):
        m = S_DB.fullmatch(h)
        if m:
            i, j = m.groups()
            arg = header.index(f"arg(S[{i}][{j}]) (deg.)")
            s = 10 ** (data[:, c] / 20) * np.exp(1j * np.deg2rad(data[:, arg]))
            S[f"{i},{j}"] = [s.real.tolist(), s.imag.tolist()]
    return data[:, 0] * 1e9, S


def field_grid(result, n):
    """Probe points for the E-field snapshot: a uniform grid over the model's bounding box with
    `n` points along the longest side, cell-centred so no point sits on the outer boundary."""
    lo, hi = _domain(result)
    h = (hi - lo).max() / n
    counts = [max(2, round((b - a) / h)) for a, b in zip(lo, hi)]
    return [a + (np.arange(c) + 0.5) * (b - a) / c for a, b, c in zip(lo, hi, counts)]


def fields_config(result, mesh_path, post_dir, axes):
    """Second Palace run: solve only at fields_at, first excited port, E probed on `axes`."""
    cfg = config(result, mesh_path, post_dir)
    k = next(q["index"] for q in result["ports"] if q["excite"])
    for port in cfg["Boundaries"]["LumpedPort"]:
        port["Excitation"] = k if port["Index"] == k else 0
    cfg["Solver"]["Driven"] = {"Samples": [{"Type": "Point",
                                            "Freq": [f / 1e9 for f in result["simulation"]["fields_at"]]}]}
    X, Y, Z = np.meshgrid(*axes, indexing="ij")
    cfg["Domains"]["Postprocessing"] = {"Probe": [
        {"Index": i + 1, "Center": [float(x), float(y), float(z)]}
        for i, (x, y, z) in enumerate(zip(X.ravel(), Y.ravel(), Z.ravel()))]}
    return cfg


def read_probe_e(path, shape):
    """probe-E.csv -> complex E, shape (nf, 3, nx, ny, nz). Probes outside the mesh read 0."""
    with open(path, encoding="utf-8") as f:
        header = [h.strip() for h in f.readline().split(",")]
    data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    E = np.zeros((len(data), 3, int(np.prod(shape))), complex)
    for c, h in enumerate(header):
        m = PROBE_E.fullmatch(h)
        if m:
            part, comp, idx = m.groups()
            E[:, "xyz".index(comp), int(idx) - 1] += data[:, c] * (1 if part == "Re" else 1j)
    return np.nan_to_num(E).reshape(len(data), 3, *shape)


def incident_scale(post_dir, port):
    """Per-frequency factor to the overlay's normalisation (peak phasors, 1 W incident, as openEMS):
    V_inc = sqrt(2 R P). Palace normalises its excitation to V_inc = sqrt(R P) (port-V.csv
    V_inc = 7.071 V at 50 ohm), so this comes out as sqrt(2); read it rather than assume it."""
    path = Path(post_dir) / "port-V.csv"
    with open(path, encoding="utf-8") as f:
        header = [h.strip() for h in f.readline().split(",")]
    data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    v_inc = data[:, header.index(f"V_inc[{port['index']}] (V)")]
    return np.sqrt(2 * port["impedance"] * 1.0) / v_inc


def _palace(cfg, work, processes, log, warnings=None):
    """Write config.json in `work`, run Palace there; raises SimError on failure."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tail = deque(maxlen=20)
    with open(work / "palace.log", "w", encoding="utf-8") as logf:
        proc = subprocess.Popen([palace_binary(), "-np", str(processes), "config.json"], cwd=work,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        for line in proc.stdout:
            logf.write(line)
            line = line.rstrip()
            if line:
                tail.append(line)
                log(line)
                if warnings is not None and "reached maximum" in line:
                    warnings.append("adaptive sweep hit its sample limit; lower adaptive_tol or check the model")
        code = proc.wait()
    if code != 0:
        raise SimError(f"Palace exited with code {code}: " + " | ".join(list(tail)[-5:]))


def _mesh_path(result):
    mesh = Path(result["files"]["palace_msh"])
    return (mesh if mesh.is_absolute() else ROOT / mesh).resolve()


def _fields(result, out, points, log):
    """Fields job: probe E at fields_at on a `points` grid, write out/fields.npz. Returns the grid shape."""
    sim = result["simulation"]
    axes = field_grid(result, points)
    shape = tuple(len(a) for a in axes)
    log(f"[sim] Palace: E-field at {len(sim['fields_at'])} frequencies on a "
        f"{shape[0]}×{shape[1]}×{shape[2]} probe grid")
    fw = out / "palace" / "fields"
    shutil.rmtree(fw, ignore_errors=True)
    _palace(fields_config(result, _mesh_path(result), fw / "postpro", axes), fw, sim["palace"]["processes"], log)
    port = next(q for q in result["ports"] if q["excite"])
    E = read_probe_e(fw / "postpro" / "probe-E.csv", shape)
    E *= incident_scale(fw / "postpro", port)[:, None, None, None, None]
    np.savez_compressed(out / "fields.npz", freqs=np.array(sim["fields_at"]), x=axes[0], y=axes[1], z=axes[2],
                        re=E.real.astype(np.float32), im=E.imag.astype(np.float32))
    return list(shape)


def recompute_fields(result, out_dir, points, log=print):
    """Re-probe the E-field of the last Palace run on a `points` grid (no new sweep). Needs results
    from the current geometry; updates fields.npz and the field entries of results.json."""
    if not 8 <= points <= 100:
        raise SimError(f"field_points must be 8-100 (got {points})")
    out = Path(out_dir).resolve()
    path = out / "results.json"
    res = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if not res or res.get("solver") != "palace":
        raise SimError("no Palace results to recompute fields for; run Analyze with Palace first")
    if res.get("source_hash") != result.get("source_hash"):
        raise SimError("the results are older than the geometry; run Analyze again")
    if not result["simulation"]["fields_at"]:
        raise SimError('no field frequencies; tick "Plot E-field" in the Analysis tab and Analyze')
    problems = preflight(result)
    if problems:
        raise SimError("; ".join(problems))
    grid = _fields(result, out, points, log)
    res.update(fields_at=result["simulation"]["fields_at"], field_points=points, field_grid=grid,
               fields_updated_at=time.time())
    path.write_text(json.dumps(res), encoding="utf-8")
    return res


def run(result, out_dir, log=print):
    """Palace sweep (all excited ports), then E-field snapshots if fields_at is set.
    Writes results.json (+ fields.npz) in the openEMS backend's format."""
    problems = preflight(result)
    if problems:
        raise SimError("; ".join(problems))
    sim = result["simulation"]
    p = sim["palace"]
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "fields.npz").unlink(missing_ok=True)  # an older run's fields would be stale
    work = out / "palace"
    shutil.rmtree(work, ignore_errors=True)
    tets = result["stats"].get("tetrahedra", 0)
    log(f"[sim] Palace: {tets:,} tetrahedra, order {p['order']}, {p['processes']} MPI processes")
    t0 = time.time()
    warnings = []
    _palace(config(result, _mesh_path(result), work / "postpro"), work, p["processes"], log, warnings)
    csv = work / "postpro" / "port-S.csv"
    if not csv.exists():
        raise SimError("Palace finished without writing port-S.csv")

    freqs, S = read_port_s(csv)
    Z = {}
    for q in result["ports"]:
        key = f"{q['index']},{q['index']}"
        if q["excite"] and key in S:
            s = np.array(S[key][0]) + 1j * np.array(S[key][1])
            z = q["impedance"] * (1 + s) / (1 - s)  # lumped port: Z_in from the reflection
            Z[str(q["index"])] = [z.real.tolist(), z.imag.tolist()]

    grid = _fields(result, out, p["field_points"], log) if sim["fields_at"] else None

    k = next(q["index"] for q in result["ports"] if q["excite"])
    mag = np.hypot(*np.array(S[f"{k},{k}"]))
    res = {
        "name": result["name"],
        "solver": "palace",
        "source_hash": result.get("source_hash"),
        "freqs": freqs.tolist(),
        "S": S,
        "Z": Z,
        "ports": [{"index": q["index"], "impedance": q["impedance"]} for q in result["ports"]],
        "fields_at": sim["fields_at"] if grid else [],
        "field_points": p["field_points"] if grid else None,
        "field_grid": grid,
        "cells": tets,
        "seconds": round(time.time() - t0, 1),
        "summary": {"f_min_s": float(freqs[np.argmin(mag)]), "s_min_db": float(20 * np.log10(mag.min()))},
        "warnings": warnings,
        "finished_at": time.time(),
    }
    (out / "results.json").write_text(json.dumps(res), encoding="utf-8")
    return res
