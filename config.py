"""Configuration module for BabBell bot."""

import os

# Required environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")

# Optional environment variables with defaults
SQLITE_PATH = os.environ.get("SQLITE_PATH", "./babbell.db")
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "60"))
INCLUDE_ACTOR_IN_PUBLIC_MESSAGE = os.environ.get(
    "INCLUDE_ACTOR_IN_PUBLIC_MESSAGE", "false"
).lower() in ("true", "1", "yes")
ENABLE_TODAYS_MENU = os.environ.get("ENABLE_TODAYS_MENU", "false").lower() in (
    "true",
    "1",
    "yes",
)
MENU_CACHE_TTL_SECONDS = int(os.environ.get("MENU_CACHE_TTL_SECONDS", "600"))

# Deduplication TTL (in-memory cache)
DEDUP_TTL_SECONDS = 300  # 5 minutes


def validate_config() -> None:
    """Validate required configuration values."""
    missing = []
    if not SLACK_BOT_TOKEN:
        missing.append("SLACK_BOT_TOKEN")
    if not SLACK_APP_TOKEN:
        missing.append("SLACK_APP_TOKEN")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
