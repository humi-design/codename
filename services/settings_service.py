"""Application settings service backed by the ``app_settings`` table."""

from __future__ import annotations

from extensions import db
from models.app_setting import AppSetting

# key -> (default value, is_boolean)
DEFAULTS: dict[str, tuple[str, bool]] = {
    "adsense_enabled": ("0", True),
    "adsense_publisher_id": ("", False),
    "adsense_slot_home": ("", False),
    "adsense_slot_join": ("", False),
    "adsense_slot_player_top": ("", False),
    "adsense_slot_player_bottom": ("", False),
    "adsense_slot_session_summary": ("", False),
    "default_board_size": ("5", False),
    "default_timer_duration": ("180", False),
    "default_word_mode": ("NORMAL", False),
    "feature_spectator_mode": ("0", True),
    "feature_custom_word_list": ("1", True),
    "app_maintenance": ("0", True),
}


class SettingsService:
    # -------------------------------------------------------------- reads
    @staticmethod
    def get(key: str, default: str | None = None) -> str | None:
        setting = AppSetting.query.filter_by(setting_key=key).first()
        if setting is None:
            if key in DEFAULTS:
                return DEFAULTS[key][0]
            return default
        return setting.setting_value

    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool:
        raw = SettingsService.get(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def get_int(key: str, default: int = 0) -> int:
        try:
            return int(SettingsService.get(key))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def all() -> dict[str, str]:
        stored = {s.setting_key: s.setting_value for s in AppSetting.query.all()}
        result = {k: v[0] for k, v in DEFAULTS.items()}
        result.update(stored)
        return result

    # ------------------------------------------------------------- writes
    @staticmethod
    def set(key: str, value) -> None:
        setting = AppSetting.query.filter_by(setting_key=key).first()
        if setting is None:
            setting = AppSetting(setting_key=key, setting_value=str(value))
            db.session.add(setting)
        else:
            setting.setting_value = str(value)

    @staticmethod
    def set_many(values: dict) -> None:
        for key, value in values.items():
            SettingsService.set(key, value)

    @staticmethod
    def ensure_defaults() -> None:
        """Create any missing default rows (called at app start-up).

        Fails soft: if the tables do not exist yet (before ``init_db``) the app
        still boots and the operator sees a clear log message.
        """
        try:
            existing = {s.setting_key for s in AppSetting.query.all()}
        except Exception as exc:  # pragma: no cover - depends on DB state
            db.session.rollback()
            import logging

            logging.getLogger(__name__).warning(
                "app_settings not ready (%s). Run scripts/init_db.py", exc
            )
            return
        created = False
        for key, (value, _is_bool) in DEFAULTS.items():
            if key not in existing:
                db.session.add(AppSetting(setting_key=key, setting_value=value))
                created = True
        if created:
            db.session.commit()

    # ------------------------------------------------------------ adsense
    @staticmethod
    def adsense_config() -> dict:
        return {
            "enabled": SettingsService.get_bool("adsense_enabled", False),
            "publisher_id": SettingsService.get("adsense_publisher_id", "") or "",
            "slots": {
                "home": SettingsService.get("adsense_slot_home", "") or "",
                "join": SettingsService.get("adsense_slot_join", "") or "",
                "player_top": SettingsService.get("adsense_slot_player_top", "") or "",
                "player_bottom": SettingsService.get("adsense_slot_player_bottom", "") or "",
                "session_summary": SettingsService.get("adsense_slot_session_summary", "") or "",
            },
        }
