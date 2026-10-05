"""Create all database tables and seed default settings.

Usage:
    python scripts/init_db.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402


def main() -> int:
    app = create_app(os.environ.get("FLASK_CONFIG", "development"))
    with app.app_context():
        import models  # noqa: F401  (ensures models are registered)

        print("Creating tables ...")
        db.create_all()

        from services.settings_service import SettingsService

        SettingsService.ensure_defaults()

        from services.admin_auth import AdminAuth

        AdminAuth.ensure_bootstrap_user()

        print("Tables created:")
        for table in sorted(db.metadata.tables):
            print(f"  - {table}")
        print("Database initialised successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
