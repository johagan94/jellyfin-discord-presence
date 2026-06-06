"""Configuration loaded from environment variables (see .env.example)."""
import os


def _csv(name):
    raw = (os.getenv(name) or "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()]


def _bool(name, default=False):
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self):
        # --- Jellyfin ---
        self.jellyfin_url = os.environ["JELLYFIN_URL"].rstrip("/")
        # Public, Discord-reachable base used only to build poster-art URLs.
        # Leave blank if Jellyfin is LAN-only -> a static logo is used instead.
        self.jellyfin_public_url = (os.getenv("JELLYFIN_PUBLIC_URL") or "").rstrip("/")
        self.jellyfin_api_key = os.environ["JELLYFIN_API_KEY"]
        self.jellyfin_username = (os.getenv("JELLYFIN_USERNAME") or "").strip()
        self.jellyfin_user_id = (os.getenv("JELLYFIN_USER_ID") or "").strip()

        # --- Discord ---
        self.discord_token = os.environ["DISCORD_USER_TOKEN"]
        self.discord_app_id = os.environ["DISCORD_APP_ID"]
        self.activity_name = os.getenv("ACTIVITY_NAME", "Jellyfin")

        # --- Exclusions ---
        self.exclude_libraries = [s.lower() for s in _csv("EXCLUDE_LIBRARIES")]
        self.exclude_media_types = _csv("EXCLUDE_MEDIA_TYPES")

        # --- Behaviour ---
        self.poll_interval = int(os.getenv("POLL_INTERVAL", "15"))
        self.show_paused = _bool("SHOW_PAUSED", True)

        # --- Images (asset keys uploaded to your Discord app, or left blank) ---
        self.static_large_image = os.getenv("STATIC_LARGE_IMAGE", "jellyfin")
        self.small_image_playing = os.getenv("SMALL_IMAGE_PLAYING", "")
        self.small_image_paused = os.getenv("SMALL_IMAGE_PAUSED", "")

        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        if not self.jellyfin_username and not self.jellyfin_user_id:
            raise SystemExit("Set JELLYFIN_USERNAME or JELLYFIN_USER_ID")
