"""Entry point for the PyInstaller-built standalone binaries.

PyInstaller needs a script to analyse.  This one exists only for that purpose so
that the ``uniservice`` launcher (which adds its own directory to ``sys.path`` for
the source checkout) stays untouched.
"""

from __future__ import annotations

from uniservice_lib.cli import entrypoint

entrypoint()
