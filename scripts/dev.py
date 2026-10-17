"""Start backend (uvicorn :8000) and frontend (vite :5173) together. Ctrl+C stops both."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

procs = [
    subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.server:app", "--port", "8000"], cwd=ROOT),
    subprocess.Popen("npm run dev", cwd=ROOT / "frontend", shell=True),
]
try:
    procs[0].wait()
except KeyboardInterrupt:
    pass
finally:
    for p in procs:
        p.terminate()
