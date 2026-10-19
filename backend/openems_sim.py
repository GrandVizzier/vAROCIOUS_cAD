"""openEMS (FDTD) backend: build result -> CSXCAD model -> run -> S-parameters, Z, E-field snapshots.

Geometry comes from the exact Gmsh build (per-object closed shells / sheet triangles), so every
boolean the project used is already resolved. All coordinates are SI meters (DeltaUnit = 1).
"""
import json
import os
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CSXCAD_INSTALL_PATH", str(ROOT / "tools" / "openEMS"))

C0 = 299792458.0
EPS0 = 8.8541878128e-12
UNSUPPORTED = ("bc:master", "bc:slave", "bc:floquet")
PRIORITY = {"dielectric": 1, "port": 5, "metal": 10}
MIN_CELLS = 3  # per gap between CAD feature lines


class SimError(Exception):
    pass


def preflight(result):
    """Everything that would make a run pointless. Returns a list of problems (empty = go)."""
    problems = []
    sim = result.get("simulation")
    if not sim:
        problems.append('no "simulation" block in the project')
    elif sim["solver"] != "openems":
        problems.append(f"solver '{sim['solver']}' is not supported")
    groups = {g["name"] for g in result["groups"]}
    bad = sorted(g for g in groups if g.startswith(UNSUPPORTED))
    if bad:
        problems.append(f"openEMS has no periodic/Floquet boundaries ({', '.join(bad)}); "
                        "this model needs a FEM solver such as Palace")
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
    return problems


def _domain(result):
    pts = np.concatenate([np.reshape(o["positions"], (-1, 3)) for o in result["objects"] if o["positions"]])
    return pts.min(0), pts.max(0)


def grid_lines(result):
    """Feature lines from the CAD model (every curve/face extent) plus the domain bounds.
    Smoothing to the max cell size is done by CSXCAD (SmoothMeshLines)."""
    lo, hi = _domain(result)
    cell = max_cell(result)
    # features closer than this are one line: OCC pads curved-edge extents by ~0.1 µm and near-
    # coincident features would otherwise force µm cells (FDTD timestep scales with the smallest cell)
    merge = max(1e-6, cell / 25)
    lines = {}
    for k, a in enumerate("xyz"):
        f = np.array([lo[k], hi[k], *result["features"][a]])
        f = np.sort(f[(f >= lo[k] - 1e-9) & (f <= hi[k] + 1e-9)])
        keep = [f[0]]
        for c in f[1:]:
            if c - keep[-1] > merge:
                keep.append(c)
        f = np.array(keep)
        # at least MIN_CELLS across every feature gap (substrate thickness, gaps, trace widths),
        # but never cells finer than cell/10; SmoothMeshLines only fills gaps larger than the max cell
        fill = [np.linspace(p, q, MIN_CELLS + 1)[1:-1] for p, q in zip(f[:-1], f[1:])
                if (q - p) / MIN_CELLS >= cell / 10]
        lines[a] = np.sort(np.concatenate([f, *fill]))
    return lines


def max_cell(result):
    sim = result["simulation"]
    epsr = max([1.0] + [v["epsr"] for v in result["materials"].values() if v and not v["metal"]])
    # ponytail: one global max cell from the highest epsr; per-region sizing if cell counts get big
    return C0 / sim["sweep"]["stop"] / np.sqrt(epsr) / sim["mesh"]["cells_per_wavelength"]


def _shell(obj):
    """Merge the per-face-split viewer vertices back into a closed triangle shell, oriented
    outward (cavity shells inward). Gmsh's per-surface triangle orientation is not reliable."""
    P = np.reshape(obj["positions"], (-1, 3))
    tris = np.reshape(obj["indices"], (-1, 3))
    verts, inv = np.unique(np.round(P, 10), axis=0, return_inverse=True)
    tris = inv.reshape(-1)[tris]
    if obj["dim"] == 3:
        tris = _orient(verts, tris)
    return verts, tris


def _signed_volume(verts, tris):
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    return np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6


def _orient(verts, tris):
    """Consistent winding per connected shell (neighbours traverse a shared edge oppositely),
    then the largest shell points outward and the others (cavities) inward."""
    tris = tris.copy()
    edge_tris = {}
    for i, t in enumerate(tris):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            edge_tris.setdefault(frozenset((a, b)), []).append(i)
    comp = np.full(len(tris), -1)
    for seed in range(len(tris)):
        if comp[seed] >= 0:
            continue
        comp[seed] = seed
        stack = [seed]
        while stack:
            i = stack.pop()
            t = tris[i]
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                for j in edge_tris[frozenset((a, b))]:
                    if comp[j] >= 0:
                        continue
                    u = tris[j]
                    if (a, b) in ((u[0], u[1]), (u[1], u[2]), (u[2], u[0])):  # same direction: flip
                        tris[j] = u[::-1]
                    comp[j] = seed
                    stack.append(j)
    shells = {c: np.flatnonzero(comp == c) for c in np.unique(comp)}
    vol = {c: _signed_volume(verts, tris[idx]) for c, idx in shells.items()}
    # ponytail: largest |volume| shell = outer, all others = cavities (no islands inside cavities)
    outer = max(vol, key=lambda c: abs(vol[c]))
    for c, idx in shells.items():
        if (vol[c] > 0) != (c == outer):
            tris[idx] = tris[idx][:, ::-1]
    return tris


def build_model(result, excite_index, dump_fields=False):
    """Create the openEMS/CSXCAD model. Returns (FDTD, CSX, {port_index: port}, ncells)."""
    from CSXCAD import ContinuousStructure
    from openEMS import openEMS

    sim = result["simulation"]
    fa, fb = sim["sweep"]["start"], sim["sweep"]["stop"]
    fdtd = openEMS(NrTS=sim["max_timesteps"], EndCriteria=10 ** (sim["end_criteria_db"] / 10))
    # wide pulse (short in time) even for narrow sweeps: band edge at least half the centre freq
    fc_exc = (fa + fb) / 2
    fdtd.SetGaussExcite(fc_exc, max((fb - fa) / 2, fc_exc / 2))
    fdtd.SetBoundaryCond([sim["absorber"]] * 6)
    csx = ContinuousStructure()
    fdtd.SetCSX(csx)
    grid = csx.GetGrid()
    grid.SetDeltaUnit(1)
    for a, l in grid_lines(result).items():
        grid.AddLine(a, l)
    grid.SmoothMeshLines("all", max_cell(result), sim["mesh"]["ratio"])
    lines = [np.array(grid.GetLines(a)) for a in "xyz"]
    ncells = int(np.prod([len(l) for l in lines]))

    def snap(k, c):
        """Zero-thickness primitives (sheets, port boxes) must sit exactly on a grid line, or
        openEMS silently drops them ('Unused primitive'); float noise of ~1e-14 m is enough."""
        c = np.asarray(c, dtype=float)
        i = np.abs(lines[k][:, None] - np.atleast_1d(c)[None, :]).argmin(0)
        near = np.abs(lines[k][i] - np.atleast_1d(c)) < 1e-6
        return np.where(near, lines[k][i], np.atleast_1d(c)).reshape(c.shape)

    fc = (fa + fb) / 2
    props = {}
    for o in result["objects"]:
        mat = result["materials"].get(o["material"])
        if not o["indices"] or mat is None or o["material"] in ("air", "vacuum"):
            continue  # air is the openEMS background; port sheets are added below
        if o["material"] not in props:
            if mat["metal"]:
                props[o["material"]] = csx.AddMetal(o["material"])
            else:
                kappa = 2 * np.pi * fc * EPS0 * mat["epsr"] * mat["tand"]
                props[o["material"]] = csx.AddMaterial(o["material"], epsilon=mat["epsr"], kappa=kappa)
        prop, prio = props[o["material"]], PRIORITY["metal" if mat["metal"] else "dielectric"]
        verts, tris = _shell(o)
        if o["dim"] == 3:
            ph = prop.AddPolyhedron(priority=prio)
            for v in verts:
                ph.AddVertex(*v)
            for t in tris:
                ph.AddFace([int(i) for i in t])
        else:
            flat = [k for k in range(3) if np.ptp(verts[:, k]) < 1e-9]
            if not flat:
                raise SimError(f"sheet '{o['name']}' is not axis-aligned; openEMS needs XY/YZ/XZ sheets")
            n = flat[0]
            u, v = [k for k in range(3) if k != n]
            vu, vv, elev = snap(u, verts[:, u]), snap(v, verts[:, v]), float(snap(n, verts[0, n]))
            for t in tris:
                prop.AddPolygon([vu[t], vv[t]], "xyz"[n], elev, priority=prio)

    ports = {}
    for p in result["ports"]:
        axis = "xyz".index(p["direction"][1])
        start = [float(snap(k, c)) for k, c in enumerate(p["start"])]
        stop = [float(snap(k, c)) for k, c in enumerate(p["stop"])]
        if p["direction"][0] == "-":
            start[axis], stop[axis] = stop[axis], start[axis]
        ports[p["index"]] = fdtd.AddLumpedPort(p["index"], p["impedance"], start, stop, "xyz"[axis],
                                               1.0 if p["index"] == excite_index else 0,
                                               priority=PRIORITY["port"])

    if dump_fields and sim["fields_at"]:
        lo, hi = _domain(result)
        csx.AddDump("Ef", dump_type=10, file_type=1, frequency=sim["fields_at"]).AddBox(lo, hi)
    return fdtd, csx, ports, ncells


def _converged(run_dir, port_index, end_db):
    """Did the port voltage decay? Compares the tail of the time signal to its peak."""
    u = np.loadtxt(run_dir / f"port_ut_{port_index}", comments="%")
    v = np.abs(u[:, 1])
    tail = v[-max(10, len(v) // 50):].max()
    # end criterion is on energy (dB = 10 log), amplitude decays half as fast in dB; 10 dB slack
    return 20 * np.log10(tail / v.max() + 1e-30) < end_db / 2 + 10


def run(result, out_dir, log=print):
    """Run one FDTD simulation per excited port. Writes results.json (+ fields.npz)."""
    problems = preflight(result)
    if problems:
        raise SimError("; ".join(problems))
    sim = result["simulation"]
    out = Path(out_dir).resolve()  # openEMS Run() changes the working directory
    out.mkdir(parents=True, exist_ok=True)
    freqs = np.linspace(sim["sweep"]["start"], sim["sweep"]["stop"], sim["sweep"]["points"])
    S, Z, warnings, t0 = {}, {}, [], time.time()
    ncells = 0
    excited = [p["index"] for p in result["ports"] if p["excite"]]
    for k in excited:
        run_dir = out / f"run_port{k}"
        first = k == excited[0]  # field snapshots only from the first excitation
        fdtd, csx, ports, ncells = build_model(result, k, dump_fields=first)
        log(f"[sim] exciting port {k}: {ncells:,} cells, max cell {max_cell(result) * 1e3:.3g} mm")
        fdtd.Run(str(run_dir), cleanup=True, verbose=0)
        for j, pj in ports.items():
            pj.CalcPort(str(run_dir), freqs, ref_impedance=result["ports"][j - 1]["impedance"])
        inc = ports[k].uf_inc
        for j, pj in ports.items():
            s = pj.uf_ref / inc
            S[f"{j},{k}"] = [s.real.tolist(), s.imag.tolist()]
        z = ports[k].uf_tot / ports[k].if_tot
        Z[str(k)] = [z.real.tolist(), z.imag.tolist()]
        if not _converged(run_dir, k, sim["end_criteria_db"]):
            warnings.append(f"port {k} run stopped before the fields decayed; raise max_timesteps")
        if first and sim["fields_at"]:
            # normalise like HFSS: 1 W incident at the excited port, phase referenced to the
            # incident wave (dump DFT and port DFT share openEMS's convention; checked to 1e-4)
            ff = np.array(sim["fields_at"])
            ports[k].CalcPort(str(run_dir), ff, ref_impedance=result["ports"][k - 1]["impedance"])
            scale = np.sqrt(2 * result["ports"][k - 1]["impedance"] * 1.0) / ports[k].uf_inc
            _save_fields(run_dir / "Ef.h5", sim["fields_at"], out / "fields.npz", scale)

    k = excited[0]
    mag = np.hypot(*np.array(S[f"{k},{k}"]))
    res = {
        "name": result["name"],
        "source_hash": result.get("source_hash"),
        "freqs": freqs.tolist(),
        "S": S,
        "Z": Z,
        "ports": [{"index": p["index"], "impedance": p["impedance"]} for p in result["ports"]],
        "fields_at": sim["fields_at"] if (out / "fields.npz").exists() else [],
        "cells": ncells,
        "seconds": round(time.time() - t0, 1),
        "summary": {"f_min_s": float(freqs[np.argmin(mag)]), "s_min_db": float(20 * np.log10(mag.min()))},
        "warnings": warnings,
        "finished_at": time.time(),
    }
    (out / "results.json").write_text(json.dumps(res), encoding="utf-8")
    return res


def _save_fields(h5, freqs, path, scale):
    """E-field snapshots, V/m for 1 W incident (scale: complex factor per frequency)."""
    from openEMS.utilities import HDF5Dump

    with HDF5Dump(str(h5)) as h:
        x, y, z = h.GetMesh()["lines"]  # SI meters
        E = np.stack([h.GetFieldAtFrequency(f) * s for f, s in zip(freqs, scale)])  # (nf, 3, nx, ny, nz)
    np.savez_compressed(path, freqs=np.array(freqs), x=x, y=y, z=z,
                        re=E.real.astype(np.float32), im=E.imag.astype(np.float32))
