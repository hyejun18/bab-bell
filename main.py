"""BabBell - Slack DM broadcast bot for meal notifications.

A production-ready Slack bot using Bolt + Socket Mode.
"""

import logging
import sys

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import SLACK_APP_TOKEN, SLACK_BOT_TOKEN, validate_config
from db import init_db
from handlers import register_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Main entry point for the BabBell bot."""
    logger.info("Starting BabBell bot...")

    # Validate configuration
    try:
        validate_config()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    # Initialize database
    logger.info("Initializing database...")
    init_db()

    # Create Slack app
    app = App(token=SLACK_BOT_TOKEN)

    # Register handlers
    register_handlers(app)

    # Start Socket Mode handler
    logger.info("Connecting to Slack via Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)

    try:
        handler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down BabBell bot...")
        handler.close()


if __name__ == "__main__":
    main()
