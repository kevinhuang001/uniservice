"""A pytest plugin that pretends the host derives the *system* scope.

Windows always derives ``system`` (see :meth:`Scope.from_env`), and CI runs the
suite on Windows only once per push.  Loading this plugin on Linux makes the
same code paths run locally and in the fast Linux jobs::

    python -m pytest -p tests.system_scope_plugin

It caught two tests that hardcoded ``user scope`` and passed everywhere except
the Windows runners.
"""

from __future__ import annotations

from uniservice_lib import scope

# ``Scope.from_env`` calls this through the module-level name.
scope.is_root_unix = lambda: True
