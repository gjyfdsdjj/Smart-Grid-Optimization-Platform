from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("script_code", "success_marker"),
    [
        (
            "import runpy; runpy.run_path('app.py', run_name='__main__'); print('app-run-ok')",
            "app-run-ok",
        ),
        (
            "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')",
            "monitoring-page-run-ok",
        ),
        (
            "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')",
            "simulation-page-run-ok",
        ),
        (
            "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')",
            "prediction-page-run-ok",
        ),
    ],
)
def test_streamlit_entrypoint_bare_run_import_safe(script_code: str, success_marker: str):
    env = os.environ.copy()
    env.setdefault("PYTHONPYCACHEPREFIX", "/tmp/sgop_pycache")

    completed = subprocess.run(
        [sys.executable, "-c", script_code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert success_marker in completed.stdout
