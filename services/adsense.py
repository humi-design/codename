"""AdSense helper.

Keeps ad configuration and rendering concerns out of the game engine.  Ads are
only ever rendered into reserved, non-game containers defined in the templates.
"""

from services.settings_service import SettingsService


class AdSenseService:
    @staticmethod
    def is_enabled() -> bool:
        config = SettingsService.adsense_config()
        # Enabled requires both the toggle *and* a publisher id.
        return bool(config["enabled"] and config["publisher_id"])

    @staticmethod
    def slot(slot_name: str) -> dict | None:
        """Return ``{"publisher_id", "slot_id"}`` for a slot, or ``None``."""
        config = SettingsService.adsense_config()
        if not (config["enabled"] and config["publisher_id"]):
            return None
        slot_id = config["slots"].get(slot_name)
        if not slot_id:
            return None
        return {"publisher_id": config["publisher_id"], "slot_id": slot_id}

    @staticmethod
    def config() -> dict:
        return SettingsService.adsense_config()
