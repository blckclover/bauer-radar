"""Local dev server entrypoint.

Windows note: `python -m uvicorn app.main:app --reload` often fails in the
reloader subprocess with "Could not import module app.main".
Use this script instead (sets PYTHONPATH for child processes):

    cd api
    python run.py

Or without hot-reload (always works):

    python -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parent
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

# Reload subprocess (spawn) must inherit api/ on PYTHONPATH
_existing = os.environ.get("PYTHONPATH", "")
_root = str(_API_ROOT)
if _root not in _existing.split(os.pathsep):
    os.environ["PYTHONPATH"] = _root + (os.pathsep + _existing if _existing else "")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(_API_ROOT / "app")],
        log_level="info",
    )
