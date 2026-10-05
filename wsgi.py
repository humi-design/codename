"""WSGI entry point for generic Python hosting (gunicorn, mod_wsgi, uWSGI).

Example:
    gunicorn --worker-class gthread --workers 1 --threads 8 wsgi:application
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("FLASK_CONFIG", "production")

from app import app as application  # noqa: E402

if __name__ == "__main__":
    application.run()
