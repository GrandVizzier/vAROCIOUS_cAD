import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=120)


def test_cli_success_writes_outputs(tmp_path):
    r = cli(ROOT / "projects/examples/box_in_air.json", "--out", tmp_path, "--render")
    assert r.returncode == 0, r.stderr
    assert "bc:radiation" in r.stdout and "Warnings: none" in r.stdout
    for f in ["box_in_air.msh", "box_in_air.step", "box_in_air.result.json", "box_in_air_iso.png"]:
        assert (tmp_path / f).exists(), f


def test_cli_failure_is_one_clear_line(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "bad", "history": [
        {"op": "sphere", "name": "s", "center": ["0", "0", "0"], "radius": "r"}]}))
    r = cli(bad, "--out", tmp_path)
    assert r.returncode == 1
    assert r.stderr.strip() == "ERROR: history[0] sphere 's': unknown variable 'r' in 'r'"
