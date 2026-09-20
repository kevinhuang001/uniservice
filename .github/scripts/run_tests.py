"""Run pytest and mirror the tail of its output into a check annotation.

GitHub does not attach test failures to the check run by itself, and job logs are
not readable without repository admin rights.  Emitting the tail of the pytest
output as an ``::error`` workflow command puts the failing tests into the
check-run annotations, where they are visible through the API and in the UI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.parse

MAX_ANNOTATION_LINES = 60


def main(argv: list[str]) -> int:
    """Run pytest with *argv* and return its exit status."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )

    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)

    if completed.returncode != 0:
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        excerpt = "%0A".join(urllib.parse.quote(line, safe="") for line in lines[-MAX_ANNOTATION_LINES:])
        print(f"::error title=pytest output (last {MAX_ANNOTATION_LINES} lines)::{excerpt}")

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
