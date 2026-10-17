import json

import pytest

from backend.engine import BuildError, build, load_project

BOX = {"op": "box", "name": "b", "origin": ["0", "0", "0"], "size": ["1", "1", "1"]}


def write(tmp_path, data):
    p = tmp_path / "p.json"
    p.write_text(json.dumps(data) if isinstance(data, dict) else data)
    return p


def project(**kw):
    return {"name": "t", "history": [BOX], **kw}


def test_minimal_project_loads(tmp_path):
    assert load_project(write(tmp_path, project())).units == "mm"


@pytest.mark.parametrize("data, msg", [
    ("{not json", "invalid JSON"),
    ({"name": "t", "history": []}, "history"),
    (project(history=[{**BOX, "op": "cone"}]), "history.0"),
    (project(history=[{**BOX, "size": ["1", "1"]}]), "history.0.box.size"),
    (project(history=[{**BOX, "colour": "red"}]), "colour"),
    (project(history=[BOX, BOX]), "duplicate object name 'b'"),
    (project(units="inch"), "units"),
])
def test_schema_failures(tmp_path, data, msg):
    with pytest.raises(BuildError, match=msg):
        load_project(write(tmp_path, data))


def test_build_errors_point_at_history_step(tmp_path):
    bad = project(history=[BOX, {**BOX, "name": "c", "size": ["hh", "1", "1"]}])
    with pytest.raises(BuildError, match=r"history\[1\] box 'c': unknown variable 'hh'"):
        build(write(tmp_path, bad), tmp_path)
    missing = project(history=[BOX, {"op": "subtract", "object": "b", "tools": ["nope"]}])
    with pytest.raises(BuildError, match=r"history\[1\] subtract 'b': unknown object 'nope'"):
        build(write(tmp_path, missing), tmp_path)
    cyc = project(variables={"a": "b", "b": "a"})
    with pytest.raises(BuildError, match="variable cycle"):
        build(write(tmp_path, cyc), tmp_path)


def test_fully_consumed_warning(tmp_path):
    small = {**BOX, "name": "s", "origin": ["0.2", "0.2", "0.2"], "size": ["0.5", "0.5", "0.5"]}
    data = project(history=[small, BOX, {"op": "intersect", "object": "s", "tools": ["b"],
                                         "name": "gone"},
                            {**BOX, "name": "far", "origin": ["5", "5", "5"]},
                            {"op": "intersect", "object": "gone", "tools": ["far"]}])
    r = build(write(tmp_path, data), tmp_path, mesh=False)
    assert any("fully consumed" in w for w in r["warnings"])
