"""Configuration module for BabBell bot."""

import json
import os
from dataclasses import dataclass

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


@dataclass
class WorkspaceConfig:
    """Configuration for a single Slack workspace."""
    workspace_id: str
    bot_token: str
    app_token: str
    name: str = ""


def load_workspaces() -> list[WorkspaceConfig]:
    """Load workspace configurations.

    Supports two modes:
    1. Multi-workspace: WORKSPACES env var (JSON array)
       Example: [{"id": "team1", "bot_token": "xoxb-...", "app_token": "xapp-...", "name": "Team 1"}]

    2. Single workspace (legacy): SLACK_BOT_TOKEN + SLACK_APP_TOKEN
       Workspace ID defaults to "default"
    """
    workspaces_json = os.environ.get("WORKSPACES")

    if workspaces_json:
        # Multi-workspace mode
        try:
            workspaces_data = json.loads(workspaces_json)
            workspaces = []
            for ws in workspaces_data:
                workspaces.append(WorkspaceConfig(
                    workspace_id=ws["id"],
                    bot_token=ws["bot_token"],
                    app_token=ws["app_token"],
                    name=ws.get("name", ws["id"]),
                ))
            return workspaces
        except (json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Invalid WORKSPACES JSON format: {e}")
    else:
        # Legacy single workspace mode
        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        app_token = os.environ.get("SLACK_APP_TOKEN")

        if bot_token and app_token:
            return [WorkspaceConfig(
                workspace_id="default",
                bot_token=bot_token,
                app_token=app_token,
                name="Default",
            )]

    return []


def validate_config() -> list[WorkspaceConfig]:
    """Validate configuration and return workspace configs."""
    workspaces = load_workspaces()

    if not workspaces:
        raise ValueError(
            "No workspace configuration found. "
            "Set either WORKSPACES (JSON) or SLACK_BOT_TOKEN + SLACK_APP_TOKEN"
        )

    # Validate each workspace
    for ws in workspaces:
        if not ws.bot_token.startswith("xoxb-"):
            raise ValueError(f"Workspace {ws.workspace_id}: bot_token must start with 'xoxb-'")
        if not ws.app_token.startswith("xapp-"):
            raise ValueError(f"Workspace {ws.workspace_id}: app_token must start with 'xapp-'")

    return workspaces
