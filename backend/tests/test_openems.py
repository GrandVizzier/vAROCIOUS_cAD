import importlib.util
import json

import numpy as np
import pytest

from backend import openems_sim as S
from backend.engine import build

HAVE_OPENEMS = importlib.util.find_spec("openEMS") is not None

# 3 GHz printed-strip dipole (two PEC strips + gap port) in a small air box
DIPOLE = {
    "name": "strip_dipole", "units": "mm",
    "variables": {"f0": "3e9", "L": "46", "w": "2", "gap": "1", "pad": "30"},
    "history": [
        {"op": "rectangle", "name": "arm1", "origin": ["-w/2", "gap/2", "0"], "size": ["w", "L/2-gap/2"], "material": "PEC"},
        {"op": "rectangle", "name": "arm2", "origin": ["-w/2", "-L/2", "0"], "size": ["w", "L/2-gap/2"], "material": "PEC"},
        {"op": "rectangle", "name": "feed", "origin": ["-w/2", "-gap/2", "0"], "size": ["w", "gap"], "material": "port"},
        {"op": "box", "name": "air", "origin": ["-pad", "-L/2-pad", "-pad"], "size": ["2*pad", "L+2*pad", "2*pad"], "material": "air"},
    ],
    "boundaries": [{"type": "radiation", "target": "air"}],
    "ports": [{"target": "feed", "direction": "+y"}],
    "simulation": {"sweep": {"start": "2e9", "stop": "4e9", "points": 101}, "fields_at": ["f0"],
                   "mesh": {"cells_per_wavelength": 15}, "absorber": "MUR", "end_criteria_db": -30},
}


@pytest.fixture
def result(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(DIPOLE))
    return build(p, tmp_path, mesh=True)


def test_preflight_ok_and_failures(result):
    assert S.preflight(result) == []
    bad = {**result, "ports": [{**result["ports"][0], "ok": False, "problems": ["start edge floats"]}]}
    assert "port 1 ('feed'): start edge floats" in S.preflight(bad)[0]
    per = {**result, "groups": result["groups"] + [{"name": "bc:master1"}]}
    assert any("Floquet" in p for p in S.preflight(per))
    assert S.preflight({**result, "simulation": None}) == ['no "simulation" block in the project']
    both = S.preflight({**per, "simulation": None})   # every problem is reported, not just the first
    assert len(both) == 2 and any("Floquet" in p for p in both)
    unknown = {**result, "materials": {**result["materials"], "Unobtainium": None}}
    assert any("Unobtainium" in p for p in S.preflight(unknown))


def test_grid_has_cad_features_and_min_cells(result):
    lines = S.grid_lines(result)
    x = lines["x"]
    for c in (-1e-3, 1e-3, -30e-3, 30e-3):          # strip edges and domain bounds
        assert np.min(np.abs(x - c)) < 1e-9
    strip = x[(x >= -1e-3 - 1e-9) & (x <= 1e-3 + 1e-9)]
    assert len(strip) >= S.MIN_CELLS + 1             # >= 3 cells across the 2 mm strip
    assert S.max_cell(result) == pytest.approx(299792458 / 4e9 / 15)


@pytest.mark.skipif(not HAVE_OPENEMS, reason="openEMS not installed")
def test_model_construction(result):
    fdtd, csx, ports, ncells = S.build_model(result, 1)
    assert set(ports) == {1} and 1000 < ncells < 2_000_000


@pytest.mark.skipif(not HAVE_OPENEMS, reason="openEMS not installed")
def test_end_to_end_strip_dipole(result, tmp_path):
    res = S.run(result, tmp_path / "sim", log=lambda m: None)
    f = np.array(res["freqs"])
    s11 = np.hypot(*np.array(res["S"]["1,1"]))
    f_res = f[np.argmin(s11)]
    # half-wave strip dipole L = 46 mm -> ~3 GHz; FDTD staircasing allows a generous window
    assert 2.4e9 < f_res < 3.6e9, f_res
    assert 20 * np.log10(s11.min()) < -6
    with np.load(tmp_path / "sim" / "fields.npz") as d:
        assert d["re"].shape[:2] == (1, 3) and len(d["x"]) == d["re"].shape[2]
