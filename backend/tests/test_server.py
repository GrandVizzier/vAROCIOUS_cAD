import json
import shutil
import time

from fastapi.testclient import TestClient

from backend import server


def test_server_build_writeback_download(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    shutil.copy(server.ROOT / "projects/examples/box_in_air.json", projects / "box.json")
    monkeypatch.setattr(server, "PROJECTS", projects)
    monkeypatch.setattr(server, "OUT", tmp_path / "out")
    server.state.clear()
    server.locks.clear()

    with TestClient(server.app) as c:
        assert [p["id"] for p in c.get("/projects").json()] == ["box"]
        b = c.get("/build/box").json()
        assert b["status"] == "ok" and b["result"]["stats"]["volumes"] == 2
        assert c.get("/download/box.msh").status_code == 200
        assert c.get("/download/box.exe").status_code == 404
        assert c.get("/build/..%2F..%2Fpyproject").status_code in (400, 404)
        assert c.put("/projects/examples/box_in_air/variables", json={"a": "5"}).status_code in (403, 404)

        with c.websocket_connect("/ws") as ws:
            assert c.put("/projects/box/variables", json={"a": "12"}).status_code == 200
            assert json.loads((projects / "box.json").read_text())["variables"]["a"] == "12"
            deadline = time.time() + 30
            while time.time() < deadline:   # watcher -> rebuild -> push
                msg = ws.receive_json()
                if msg["status"] == "ok":
                    break
        assert c.get("/build/box").json()["result"]["values"]["a"] == 12

        (projects / "box.json").write_text("{broken")
        time.sleep(2)
        b = c.get("/build/box").json()
        assert b["status"] == "error" and "invalid JSON" in b["error"]
        assert b["result"]["values"]["a"] == 12     # last good geometry kept
