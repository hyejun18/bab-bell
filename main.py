"""BabBell - Slack DM broadcast bot for meal notifications.

A production-ready Slack bot using Bolt + Socket Mode.
Supports multiple Slack workspaces simultaneously.
"""

import logging
import sys
import threading
from typing import Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import WorkspaceConfig, validate_config
from db import init_db, migrate_db
from handlers import register_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


class WorkspaceRunner:
    """Manages a single workspace's Slack app and Socket Mode handler."""

    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.app = App(token=config.bot_token)
        self.handler = SocketModeHandler(self.app, config.app_token)

        # Register handlers for this workspace
        register_handlers(self.app, config.workspace_id)

    def start(self) -> None:
        """Start the Socket Mode handler (blocking)."""
        logger.info(
            "Workspace %s (%s) connecting to Slack...",
            self.config.workspace_id,
            self.config.name,
        )
        self.handler.start()

    def start_async(self) -> None:
        """Start the Socket Mode handler (non-blocking)."""
        logger.info(
            "Workspace %s (%s) connecting to Slack...",
            self.config.workspace_id,
            self.config.name,
        )
        self.handler.connect()

    def close(self) -> None:
        """Close the Socket Mode handler."""
        logger.info("Closing workspace %s...", self.config.workspace_id)
        self.handler.close()


def main() -> None:
    """Main entry point for the BabBell bot."""
    logger.info("Starting BabBell bot...")

    # Validate configuration and get workspace configs
    try:
        workspaces = validate_config()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    logger.info("Loaded %d workspace(s)", len(workspaces))
    for ws in workspaces:
        logger.info("  - %s (%s)", ws.workspace_id, ws.name)

    # Initialize database
    logger.info("Initializing database...")
    init_db()

    # Migrate existing database if needed
    logger.info("Checking for database migrations...")
    migrate_db()

    # Create runners for each workspace
    runners: list[WorkspaceRunner] = []
    for ws_config in workspaces:
        runner = WorkspaceRunner(ws_config)
        runners.append(runner)

    if len(runners) == 1:
        # Single workspace - run in main thread (blocking)
        try:
            runners[0].start()
        except KeyboardInterrupt:
            logger.info("Shutting down BabBell bot...")
            runners[0].close()
    else:
        # Multiple workspaces - run each in its own thread
        threads: list[threading.Thread] = []

        # Start all handlers asynchronously (non-blocking connect)
        for runner in runners:
            runner.start_async()

        logger.info("All workspaces connected. Press Ctrl+C to stop.")

        try:
            # Keep main thread alive
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            logger.info("Shutting down BabBell bot...")
            for runner in runners:
                runner.close()


if __name__ == "__main__":
    main()
