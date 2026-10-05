"""Shared Flask extension instances.

Kept in their own module so models, routes and sockets can all import the
same objects without creating circular imports.
"""

from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

# ``cors_allowed_origins`` defaults to same-origin which is what we want on a
# single domain deployment.  ``async_mode`` is resolved from config at init.
socketio = SocketIO(cors_allowed_origins=None, manage_session=False)
