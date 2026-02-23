from __future__ import annotations

import sys
import time
import webbrowser
import subprocess
from pathlib import Path


def run():
    root = Path(__file__).resolve().parent
    ui_file = root / "modules" / "ui.py"
    port = "8501"
    url = f"http://localhost:{port}"

    # Start Streamlit using the SAME venv python
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(ui_file),
            "--server.port", port,
            "--server.headless", "true",
        ],
        cwd=str(root),  # critical so `modules` is importable
    )

    # Give the server a moment to start, then open browser
    time.sleep(1.0)
    webbrowser.open(url)

    # Keep main.py alive while Streamlit runs
    proc.wait()


if __name__ == "__main__":
    run()


