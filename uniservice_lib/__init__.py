"""uniservice - a small cross-platform service manager.

``uniservice`` never implements supervision itself.  Instead it translates a
portable vocabulary (``add``, ``list``, ``start``, ...) into the native
mechanism of the host operating system:

======================  ==========================================
Platform                Native mechanism
======================  ==========================================
Linux                   systemd units (user or system scope)
macOS                   launchd jobs (LaunchAgents/LaunchDaemons)
Windows                 Scheduled Tasks (``schtasks.exe``)
======================  ==========================================

The package is intentionally dependency-free and only uses the Python
standard library so that the install scripts can drop it next to the
``uniservice`` launcher.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.2.0"
