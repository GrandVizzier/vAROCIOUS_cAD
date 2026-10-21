import json
from pathlib import Path

import numpy as np
import pytest

from backend import palace_sim as P
from backend import solvers
from backend.engine import build, palace_mesh_size
from backend.tests.test_openems import DIPOLE

HAVE_PALACE = P.palace_binary() is not None
PALACE_DIPOLE = {**DIPOLE, "simulation": {**DIPOLE["simulation"], "solver": "palace", "fields_at": [],
                                          "palace": {"processes": 2}}}


def _build(tmp_path, project):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "d.json"
    p.write_text(json.dumps(project))
    return build(p, tmp_path, mesh=True)


@pytest.fixture
def result(tmp_path):
    return _build(tmp_path, PALACE_DIPOLE)


def test_dispatch_and_preflight(result, monkeypatch):
    assert solvers.backend(result) is P
    monkeypatch.setattr(P, "palace_binary", lambda: "/opt/palace")
    assert P.preflight(result) == []
    groups = [g for g in result["groups"] if g["name"] != "bc:radiation"]
    assert any("radiation boundary" in p for p in P.preflight({**result, "groups": groups}))
    per = {**result, "groups": result["groups"] + [{"name": "bc:master1", "dim": 2, "id": 99}]}
    assert any("periodic" in p for p in P.preflight(per))
    monkeypatch.setattr(P, "palace_binary", lambda: None)
    assert any("not installed" in p for p in P.preflight(result))


def test_mesh_is_sized_for_the_solver(result, tmp_path):
    # 4 GHz stop in air, 6 elements per wavelength
    assert palace_mesh_size(result["simulation"], result["materials"]) == pytest.approx(299792458 / 4e9 / 6)
    geometry_only = _build(tmp_path / "o", DIPOLE)  # openEMS project: geometry-driven tetra mesh
    assert result["stats"]["tetrahedra"] > geometry_only["stats"]["tetrahedra"]


def test_config_maps_groups_to_attributes(result, tmp_path):
    cfg = P.config(result, tmp_path / "d.msh", tmp_path / "post")
    gid = {(g["dim"], g["name"]): g["id"] for g in result["groups"]}
    assert cfg["Model"] == {"Mesh": str(tmp_path / "d.msh"), "L0": 1.0}
    assert cfg["Domains"]["Materials"] == [{"Attributes": [gid[(3, "mat:air")]], "Permittivity": 1.0,
                                            "LossTan": 0.0}]
    b = cfg["Boundaries"]
    assert b["Absorbing"]["Attributes"] == [gid[(2, "bc:radiation")]]
    assert b["PEC"]["Attributes"] == [gid[(2, "bc:PEC")]]
    assert b["LumpedPort"] == [{"Index": 1, "R": 50.0, "Excitation": 1, "Attributes": [gid[(2, "port:1")]],
                                "Direction": "+Y"}]
    samples = cfg["Solver"]["Driven"]["Samples"][0]
    assert (samples["MinFreq"], samples["MaxFreq"], samples["NSample"]) == (2.0, 4.0, 101)


def test_metal_volumes_are_holes_in_the_palace_mesh(tmp_path):
    # a PEC post bridging the dipole gap region: meshed PEC interiors make Palace abort
    post = {"op": "box", "name": "post", "origin": ["4", "-1", "-1"], "size": ["1", "2", "2"], "material": "PEC"}
    project = {**PALACE_DIPOLE, "history": PALACE_DIPOLE["history"][:-1] + [post, PALACE_DIPOLE["history"][-1]]}
    r = _build(tmp_path, project)
    assert any(g["name"] == "mat:PEC" for g in r["groups"])          # the main .msh keeps it
    names = Path(r["files"]["palace_msh"]).read_text().split("$PhysicalNames")[1].split("$EndPhysicalNames")[0]
    assert '"mat:PEC"' not in names and '"bc:PEC"' in names and '"mat:air"' in names
    plain = _build(tmp_path / "plain", PALACE_DIPOLE)   # no metal volume: every group must survive
    plain_names = Path(plain["files"]["palace_msh"]).read_text().split("$PhysicalNames")[1]
    assert '"mat:air"' in plain_names and '"port:1"' in plain_names
    pec_id = next(g["id"] for g in r["groups"] if g["name"] == "mat:PEC")
    cfg = P.config(r, tmp_path / "d.msh", tmp_path / "post")
    assert all(pec_id not in m["Attributes"] for m in cfg["Domains"]["Materials"])


def test_read_port_s(tmp_path):
    csv = tmp_path / "port-S.csv"
    csv.write_text("            f (GHz),      |S[1][1]| (dB),    arg(S[1][1]) (deg.),      |S[2][1]| (dB),"
                   "    arg(S[2][1]) (deg.)\n"
                   " +2.000000000e+00, -6.020599913e+00, +9.000000000e+01, -2.000000000e+01, +0.000000000e+00\n"
                   " +3.000000000e+00, -2.000000000e+01, -1.800000000e+02, -3.000000000e+00, +4.500000000e+01\n")
    f, S = P.read_port_s(csv)
    assert f.tolist() == [2e9, 3e9]
    s11 = np.array(S["1,1"][0]) + 1j * np.array(S["1,1"][1])
    assert s11 == pytest.approx([0.5j, -0.1], abs=1e-9)
    assert set(S) == {"1,1", "2,1"}


def test_progress_lines():
    setup = {"palace": {"adaptive_tol": 1e-3}}
    assert P.progress("Greedy iteration 4 (n = 5): ω* = 2.1e+00 GHz", setup)[0] == pytest.approx(17)
    pct, stage = P.progress("It 40/101: ω/2π = 2.780e+00 GHz (total elapsed time = 1.20e+01 s)", setup)
    assert pct == pytest.approx(85 + 14 * 40 / 101) and stage == "frequency 40/101"
    pct, _ = P.progress("It 3/101: ω/2π = 2.0e+00 GHz (total elapsed time = 1.0e+00 s, solve 104/202)",
                        {"palace": {"adaptive_tol": 0}})
    assert pct == pytest.approx(99 * 104 / 202)
    assert P.progress(" Sol. ||E|| = 1.0e+00", setup) == (None, None)


def test_field_run_config_and_parsing(result, tmp_path):
    axes = P.field_grid(result, 10)
    assert max(len(a) for a in axes) == 10
    lo, hi = np.array([-30e-3, -53e-3, -30e-3]), np.array([30e-3, 53e-3, 30e-3])  # the air box
    for a, l, h in zip(axes, lo, hi):
        assert l < a.min() and a.max() < h   # cell-centred: nothing on the outer boundary
    cfg = P.fields_config({**result, "simulation": {**result["simulation"], "fields_at": [3e9]}},
                          tmp_path / "d.msh", tmp_path / "post", axes)
    assert cfg["Solver"]["Driven"] == {"Samples": [{"Type": "Point", "Freq": [3.0]}]}
    probes = cfg["Domains"]["Postprocessing"]["Probe"]
    assert len(probes) == np.prod([len(a) for a in axes]) and probes[0]["Index"] == 1
    assert probes[1]["Center"][2] == pytest.approx(axes[2][1])   # z varies fastest (ij order)

    csv = tmp_path / "probe-E.csv"
    cols = [f"{p}{{E_{c}[{i}]}} (V/m)" for i in (1, 2) for c in "xyz" for p in ("Re", "Im")]
    csv.write_text("f (GHz)," + ",".join(cols) + "\n3.0," + ",".join(str(v) for v in range(12)) + "\n")
    E = P.read_probe_e(csv, (1, 1, 2))
    assert E.shape == (1, 3, 1, 1, 2)
    assert E[0, :, 0, 0, 1].tolist() == [6 + 7j, 8 + 9j, 10 + 11j]   # probe 2: Ex, Ey, Ez

    (tmp_path / "port-V.csv").write_text("f (GHz), V_inc[1] (V), Re{V[1]} (V)\n3.0, 7.0710678, 1.0\n")
    assert P.incident_scale(tmp_path, {"index": 1, "impedance": 50.0}) == pytest.approx([np.sqrt(2)])


def test_recompute_fields_refuses_unusable_results(result, tmp_path):
    with_fields = {**result, "simulation": {**result["simulation"], "fields_at": [3e9]}}
    d = tmp_path / "sim"
    d.mkdir()
    with pytest.raises(P.SimError, match="no Palace results"):
        P.recompute_fields(with_fields, d, 20)
    (d / "results.json").write_text(json.dumps({"solver": "openems", "source_hash": result["source_hash"]}))
    with pytest.raises(P.SimError, match="no Palace results"):
        P.recompute_fields(with_fields, d, 20)
    (d / "results.json").write_text(json.dumps({"solver": "palace", "source_hash": "older"}))
    with pytest.raises(P.SimError, match="older than the geometry"):
        P.recompute_fields(with_fields, d, 20)
    (d / "results.json").write_text(json.dumps({"solver": "palace", "source_hash": result["source_hash"]}))
    with pytest.raises(P.SimError, match="no field frequencies"):
        P.recompute_fields(result, d, 20)
    with pytest.raises(P.SimError, match="8-100"):
        P.recompute_fields(with_fields, d, 4)


@pytest.mark.skipif(not HAVE_PALACE, reason="Palace not installed")
def test_end_to_end_strip_dipole(result, tmp_path):
    with_fields = {**result, "simulation": {**result["simulation"], "fields_at": [3e9],
                                            "palace": {**result["simulation"]["palace"], "field_points": 16}}}
    res = P.run(with_fields, tmp_path / "sim", log=lambda m: None)
    f = np.array(res["freqs"])
    s11 = np.hypot(*np.array(res["S"]["1,1"]))
    f_res = f[np.argmin(s11)]
    # half-wave strip dipole L = 46 mm -> ~3 GHz (same window as the openEMS test)
    assert 2.4e9 < f_res < 3.6e9, f_res
    assert 20 * np.log10(s11.min()) < -6
    assert res["solver"] == "palace" and set(res["Z"]) == {"1"} and res["fields_at"] == [3e9]
    with np.load(tmp_path / "sim" / "fields.npz") as d:
        assert d["re"].shape[:2] == (1, 3) and d["re"].shape[2:] == (len(d["x"]), len(d["y"]), len(d["z"]))

    # denser field plot without a new sweep: only the field entries change
    again = P.recompute_fields(with_fields, tmp_path / "sim", 24)
    assert max(again["field_grid"]) == 24 and again["field_points"] == 24 and again["S"] == res["S"]
    with np.load(tmp_path / "sim" / "fields.npz") as d:
        assert list(d["re"].shape[2:]) == again["field_grid"]

    # normalisation: 1 W incident at 50 ohm = 10 V peak, so |E| across the 1 mm gap ~ 10 V |1 + S11| / 1 mm
    w = tmp_path / "gap"
    P._palace(P.fields_config(with_fields, Path(result["files"]["palace_msh"]).resolve(), w / "post",
                              [np.array([0.0]), np.array([0.0]), np.array([1e-4])]), w, 2, log=lambda m: None)
    gap = abs(P.read_probe_e(w / "post" / "probe-E.csv", (1, 1, 1))[0, 1, 0, 0, 0])
    gap *= P.incident_scale(w / "post", result["ports"][0])[0]
    s = np.array(res["S"]["1,1"])
    s3 = np.interp(3e9, f, s[0]) + 1j * np.interp(3e9, f, s[1])
    assert gap == pytest.approx(10 * abs(1 + s3) / 1e-3, rel=0.15)
