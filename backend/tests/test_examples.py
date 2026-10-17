from pathlib import Path

import pytest

from backend.engine import build

EX = Path(__file__).resolve().parents[2] / "projects" / "examples"


def run(name, tmp_path):
    r = build(EX / f"{name}.json", tmp_path)
    assert Path(r["files"]["msh"]).stat().st_size > 0
    assert Path(r["files"]["step"]).stat().st_size > 0
    r["obj"] = {o["name"]: o for o in r["objects"]}
    r["grp"] = {g["name"]: g for g in r["groups"]}
    return r


def test_box_in_air(tmp_path):
    r = run("box_in_air", tmp_path)
    assert r["stats"]["volumes"] == 2
    shared = set(r["obj"]["block"]["faces"]) & set(r["obj"]["airbox"]["faces"])
    assert len(shared) == 6                        # all cube faces are conformal interfaces
    assert r["grp"]["bc:radiation"]["count"] == 6   # outer faces only, not the interface
    assert set(r["grp"]["bc:radiation"]["tags"]).isdisjoint(shared)


def test_patch_on_fr4(tmp_path):
    r = run("patch_on_fr4", tmp_path)
    patch = r["obj"]["patch"]["faces"]
    assert len(patch) == 1
    assert patch[0] in r["obj"]["substrate"]["faces"]   # conformal with substrate top
    assert patch[0] in r["obj"]["airbox"]["faces"]
    for g in ("mat:FR4", "mat:air", "bc:radiation", "bc:PEC"):
        assert g in r["grp"], g
    assert r["warnings"] == []


def test_coax_section(tmp_path):
    r = run("coax_section", tmp_path)
    assert r["stats"]["volumes"] == 1
    assert r["stats"]["surfaces"] == 4                  # outer wall, bore, two annular caps
    assert list(r["obj"]) == ["dielectric"]
    assert r["grp"]["mat:PTFE"]["count"] == 1


def test_dipole(tmp_path):
    r = run("dipole_halfwave", tmp_path)
    assert r["stats"]["volumes"] == 3
    assert r["grp"]["mat:PEC"]["count"] == 2
    assert r["grp"]["mat:air"]["count"] == 1
    assert r["grp"]["bc:radiation"]["count"] == 1        # the sphere surface
    assert r["warnings"] == []
    top = r["values"]
    assert top["L"] == pytest.approx(0.48 * 299.792458, rel=1e-6)
