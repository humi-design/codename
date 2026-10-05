"""Passenger entry point for cPanel / shared hosting.

cPanel's Python application (Setup Python App) looks for ``passenger_wsgi.py``
in the application root and calls ``application``.  Everything is created
through the application factory in ``app.py``.

Notes for shared hosting:
  * ``SOCKETIO_ASYNC_MODE=threading`` is used so no eventlet/gevent worker is
    required.  Socket.IO falls back to long-polling automatically when
    websockets are unavailable; the frontend also polls the REST state
    endpoint, so the game stays playable either way.
  * Set ``PROXY_FIX=1`` so Flask trusts the cPanel reverse proxy headers.
"""

import os
import sys

# Make sure the project root is importable regardless of the current directory.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("FLASK_CONFIG", "production")

from app import app as application  # noqa: E402
