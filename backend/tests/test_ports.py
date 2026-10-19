import json

import pytest

from backend.engine import BuildError, build

# microstrip-like stack: ground sheet at z=0, substrate, strip at z=h, edge port sheet in XZ
H = [
    {"op": "box", "name": "sub", "origin": ["-10", "-10", "0"], "size": ["20", "20", "h"], "material": "FR4"},
    {"op": "rectangle", "name": "gnd", "origin": ["-10", "-10", "0"], "size": ["20", "20"], "material": "PEC"},
    {"op": "rectangle", "name": "strip", "origin": ["-1.5", "-10", "h"], "size": ["3", "15"], "material": "PEC"},
]


def run(tmp_path, port_sheet, port, **extra):
    data = {"name": "p", "variables": {"h": "1.6"}, "history": H + [port_sheet], "ports": [port], **extra}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(data))
    return build(p, tmp_path, mesh=False)


EDGE = {"op": "rectangle", "name": "port1", "origin": ["-1.5", "-10", "0"], "size": ["3", "h"],
        "plane": "XZ", "material": "port"}


def test_valid_edge_port(tmp_path):
    r = run(tmp_path, EDGE, {"target": "port1", "direction": "+z", "impedance": "25*2"})
    (p,) = r["ports"]
    assert p["ok"], p["problems"]
    assert p["impedance"] == 50
    assert p["start"][2] == pytest.approx(0, abs=1e-9) and p["stop"][2] == pytest.approx(1.6e-3)
    assert not any("port" in w for w in r["warnings"])
    assert {"port:1", "bc:PEC", "mat:FR4"} <= {g["name"] for g in r["groups"]}
    assert all(isinstance(g["id"], int) for g in r["groups"])


def test_port_not_touching_metal(tmp_path):
    floating = {**EDGE, "origin": ["5", "-10", "0"]}  # beside the strip: top edge hits bare substrate
    r = run(tmp_path, floating, {"target": "port1", "direction": "+z"})
    (p,) = r["ports"]
    assert not p["ok"]
    assert any("end edge at z" in m and "does not touch metal" in m for m in p["problems"])
    assert any("port 1 ('port1')" in w for w in r["warnings"])


def test_port_direction_normal_to_sheet(tmp_path):
    r = run(tmp_path, EDGE, {"target": "port1", "direction": "+y"})
    assert "normal to the port sheet" in r["ports"][0]["problems"][0]


def test_simulation_block_evaluated(tmp_path):
    r = run(tmp_path, EDGE, {"target": "port1"},
            simulation={"sweep": {"start": "1e9", "stop": "2*f", "points": 11}, "fields_at": ["1.5e9"]},
            variables={"h": "1.6", "f": "1.5e9"})
    s = r["simulation"]
    assert s["sweep"] == {"start": 1e9, "stop": 3e9, "points": 11}
    assert s["fields_at"] == [1.5e9] and s["absorber"] == "PML_8"
    assert r["materials"]["FR4"] == {"metal": False, "epsr": 4.4, "tand": 0.02}
    assert r["materials"]["PEC"] == {"metal": True}


def test_simulation_bad_sweep(tmp_path):
    with pytest.raises(BuildError, match="start < stop"):
        run(tmp_path, EDGE, {"target": "port1"}, simulation={"sweep": {"start": "3e9", "stop": "1e9"}})
