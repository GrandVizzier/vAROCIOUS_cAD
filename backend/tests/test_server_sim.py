import json
import shutil
import sys
import textwrap
import time

import numpy as np
from fastapi.testclient import TestClient

from backend import server

FAKE = textwrap.dedent("""
    import json, sys, time, pathlib, numpy as np
    out = pathlib.Path(sys.argv[1]) / "sims" / "patch_inset_2p4ghz"
    out.mkdir(parents=True, exist_ok=True)
    print("[sim] exciting port 1: 1,000 cells", flush=True)
    for db in (-5, -20, -35):
        print(f"[@ 1s] Timestep: 10 || Speed: 1 MC/s || Energy: ~1e-9 ({db}.00dB)", flush=True)
        time.sleep(0.05)
    f = np.linspace(2e9, 2.8e9, 5)
    (out / "results.json").write_text(json.dumps({"name": "patch_inset_2p4ghz", "freqs": f.tolist(),
        "S": {"1,1": [[0.1] * 5, [0.0] * 5]}, "Z": {"1": [[50] * 5, [0] * 5]}, "finished_at": time.time() + 60}))
    x = y = z = np.linspace(0, 1, 4)
    np.savez(out / "fields.npz", freqs=np.array([2.4e9]), x=x, y=y, z=z,
             re=np.ones((1, 3, 4, 4, 4), np.float32), im=np.zeros((1, 3, 4, 4, 4), np.float32))
""")


def test_simulation_endpoints(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    shutil.copy(server.ROOT / "projects/patch_inset_2p4ghz.json", projects / "patch.json")
    fake = tmp_path / "fake_sim.py"
    fake.write_text(FAKE)
    out = tmp_path / "out"
    monkeypatch.setattr(server, "PROJECTS", projects)
    monkeypatch.setattr(server, "OUT", out)
    monkeypatch.setattr(server, "sim_command", lambda path: [sys.executable, str(fake), str(out)])
    server.state.clear()
    server.locks.clear()
    server.sim.update(pid=None, status="idle", progress=0.0)

    with TestClient(server.app) as c:
        assert c.get("/build/patch").json()["status"] == "ok"
        assert c.get("/sim/patch").json()["problems"] == []

        # setup write-back is validated
        assert c.put("/projects/patch/simulation", json={"sweep": {"start": "1e9"}}).status_code == 422
        new = {"sweep": {"start": "2.1e9", "stop": "2.7e9", "points": 201}, "fields_at": ["f0"]}
        assert c.put("/projects/patch/simulation", json=new).status_code == 200
        assert json.loads((projects / "patch.json").read_text())["simulation"] == new

        assert c.post("/simulate/patch").status_code == 200
        assert c.post("/simulate/patch").status_code == 409          # one run at a time
        deadline = time.time() + 20
        while c.get("/sim/patch").json()["status"] == "running" and time.time() < deadline:
            time.sleep(0.1)
        s = c.get("/sim/patch").json()
        assert s["status"] == "done" and s["progress"] == 100
        assert s["stage"].startswith("exciting port 1")
        assert s["results"]["S"]["1,1"][0][0] == 0.1 and s["stale"] is False

        fp = c.get("/sim/patch/field", params={"f": 2.4e9, "plane": "z", "pos": 0.5}).json()
        assert fp["u_axis"] == "x" and fp["v_axis"] == "y"
        assert np.array(fp["re"]).shape == (3, 4, 4) and fp["freq"] == 2.4e9


def test_preflight_blocks_bad_projects(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    shutil.copy(server.ROOT / "projects/me_dipole_dp_cell.json", projects / "cell.json")
    monkeypatch.setattr(server, "PROJECTS", projects)
    monkeypatch.setattr(server, "OUT", tmp_path / "out")
    server.state.clear()
    server.locks.clear()
    with TestClient(server.app) as c:
        c.get("/build/cell")
        r = c.post("/simulate/cell")
        assert r.status_code == 400 and "simulation" in r.json()["detail"]
