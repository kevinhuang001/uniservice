"""Process exit codes.

The numbering follows the common Unix convention so that shell scripts can tell
"you asked for something impossible" apart from "the thing failed":

``0``
    The command did what it said.
``1``
    The command was understood but failed: a native tool returned non-zero, the
    service does not exist, the privileges were insufficient, ...
``2``
    The command line itself was wrong (unknown command, missing argument,
    invalid value).  This is also what :mod:`argparse` would have used.
``130``
    Interrupted with ``Ctrl-C``.
"""

from __future__ import annotations

OK = 0
FAILURE = 1
USAGE = 2
INTERRUPTED = 130

__all__ = ["FAILURE", "INTERRUPTED", "OK", "USAGE"]
