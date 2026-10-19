"""Install openEMS for this repo (Windows): download the MSVC build into tools/openEMS and
pip-install its Python packages into the current interpreter (run it with the .venv Python).

    .venv\\Scripts\\python scripts\\install_openems.py

Linux/macOS: build openEMS with Python support instead (see README) and set CSXCAD_INSTALL_PATH.
"""
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.37.0"
URL = (f"https://github.com/thliebig/openEMS-Project/releases/download/v{VERSION}/"
       f"openEMS_x64_v{VERSION}_msvc.zip")
TOOLS = Path(__file__).resolve().parents[1] / "tools"


def main():
    if sys.platform != "win32":
        sys.exit("This installer is Windows-only; see README for Linux/macOS.")
    if sys.version_info[:2] not in ((3, 13), (3, 14)):
        sys.exit(f"openEMS {VERSION} ships wheels for Python 3.13/3.14 only (this is {sys.version.split()[0]}).")
    TOOLS.mkdir(exist_ok=True)
    zpath = TOOLS / URL.rsplit("/", 1)[1]
    if not (TOOLS / "openEMS" / "openEMS.exe").exists():
        if not zpath.exists():
            print(f"Downloading {URL} ...")
            urllib.request.urlretrieve(URL, zpath)
        print("Extracting ...")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(TOOLS)
        zpath.unlink()
    pip = [sys.executable, "-m", "pip", "install", "-q"]
    subprocess.check_call(pip + ["numpy", "h5py"])
    subprocess.check_call(pip + ["--no-index", "--find-links", str(TOOLS / "openEMS" / "python"), "openEMS"])
    check = subprocess.run([sys.executable, "-c", "import openEMS; print(openEMS.__version__)"],
                           env={**os.environ,"CSXCAD_INSTALL_PATH": str(TOOLS / "openEMS")},
                           capture_output=True, text=True)
    if check.returncode:
        sys.exit("openEMS import failed:\n" + check.stderr)
    print(f"openEMS {check.stdout.strip()} installed in {TOOLS / 'openEMS'}")


if __name__ == "__main__":
    main()
