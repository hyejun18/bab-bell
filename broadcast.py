"""Broadcast module for BabBell bot.

Handles sending DM broadcasts to subscribed users.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from buttons import ButtonDefinition
from config import ENABLE_TODAYS_MENU, INCLUDE_ACTOR_IN_PUBLIC_MESSAGE
from db import (
    User,
    create_broadcast_metadata,
    get_subscribed_users,
    insert_send_log,
    update_user_dm_channel,
)
from menu import fetch_menu, menu_to_dict, render_menu_blocks

logger = logging.getLogger(__name__)


@dataclass
class BroadcastResult:
    """Result of a broadcast operation."""

    broadcast_id: str
    action: str
    initiated_by: str
    total_targets: int
    success_count: int
    failure_count: int
    failures: list[tuple[str, str]]  # [(user_id, error), ...]


def _open_dm_channel(client: WebClient, user_id: str) -> str | None:
    """Open a DM channel with a user and return the channel ID."""
    try:
        response = client.conversations_open(users=[user_id])
        if response["ok"]:
            return response["channel"]["id"]
    except SlackApiError as e:
        logger.error("Failed to open DM with %s: %s", user_id, e)
    return None


def _build_broadcast_message(
    button: ButtonDefinition,
    initiated_by: str,
    menu_blocks: list[dict[str, Any]] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Build the broadcast message text and blocks.

    Returns (text, blocks) tuple.
    """
    text = button.template

    # Optionally include actor (default: false)
    if INCLUDE_ACTOR_IN_PUBLIC_MESSAGE:
        text = f"{text}\n(by <@{initiated_by}>)"

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        }
    ]

    # Add menu blocks if applicable
    if menu_blocks:
        blocks.append({"type": "divider"})
        blocks.extend(menu_blocks)

    return text, blocks


def broadcast(
    client: WebClient,
    button: ButtonDefinition,
    initiated_by: str,
) -> BroadcastResult:
    """Send DM broadcast to all subscribed users.

    Args:
        client: Slack WebClient
        button: Button definition that triggered this broadcast
        initiated_by: Slack user ID who initiated the broadcast

    Returns:
        BroadcastResult with success/failure counts
    """
    broadcast_id = str(uuid.uuid4())
    action = button.value

    # Fetch menu if needed
    menu_data = None
    menu_blocks = None
    if button.include_menu and ENABLE_TODAYS_MENU:
        menu = fetch_menu()
        menu_data = menu_to_dict(menu)
        menu_blocks = render_menu_blocks(menu)

    # Create broadcast metadata (for future web aggregation)
    _ = create_broadcast_metadata(
        broadcast_id=broadcast_id,
        action=action,
        initiated_by=initiated_by,
        menu_data=menu_data,
    )

    # Get subscribed users
    users = get_subscribed_users()

    logger.info(
        "Starting broadcast broadcast_id=%s action=%s initiated_by=%s targets=%d",
        broadcast_id,
        action,
        initiated_by,
        len(users),
    )

    # Build message
    text, blocks = _build_broadcast_message(button, initiated_by, menu_blocks)

    success_count = 0
    failure_count = 0
    failures: list[tuple[str, str]] = []

    for user in users:
        dm_channel_id = user.dm_channel_id
        dm_ts = None
        ok = False
        error = None

        try:
            # Open DM channel if not cached
            if not dm_channel_id:
                dm_channel_id = _open_dm_channel(client, user.slack_user_id)
                if dm_channel_id:
                    update_user_dm_channel(user.slack_user_id, dm_channel_id)

            if not dm_channel_id:
                raise SlackApiError("Failed to open DM channel", {"error": "channel_not_found"})

            # Send message
            response = client.chat_postMessage(
                channel=dm_channel_id,
                text=text,
                blocks=blocks,
            )

            if response["ok"]:
                dm_ts = response.get("ts")
                ok = True
                success_count += 1
            else:
                error = response.get("error", "unknown_error")
                failure_count += 1
                failures.append((user.slack_user_id, error))

        except SlackApiError as e:
            error = str(e.response.get("error", str(e)))
            failure_count += 1
            failures.append((user.slack_user_id, error))
            logger.error(
                "Failed to send DM to %s: %s broadcast_id=%s",
                user.slack_user_id,
                error,
                broadcast_id,
            )

        # Log to send_log
        insert_send_log(
            broadcast_id=broadcast_id,
            action=action,
            initiated_by=initiated_by,
            target_user_id=user.slack_user_id,
            dm_channel_id=dm_channel_id,
            dm_ts=dm_ts,
            ok=ok,
            error=error,
        )

    logger.info(
        "Broadcast complete broadcast_id=%s action=%s success=%d failure=%d",
        broadcast_id,
        action,
        success_count,
        failure_count,
    )

    return BroadcastResult(
        broadcast_id=broadcast_id,
        action=action,
        initiated_by=initiated_by,
        total_targets=len(users),
        success_count=success_count,
        failure_count=failure_count,
        failures=failures,
    )


def send_dm(
    client: WebClient,
    user_id: str,
    text: str,
    blocks: list[dict[str, Any]] | None = None,
) -> bool:
    """Send a DM to a single user.

    Args:
        client: Slack WebClient
        user_id: Target Slack user ID
        text: Message text
        blocks: Optional Block Kit blocks

    Returns:
        True if successful, False otherwise
    """
    try:
        dm_channel_id = _open_dm_channel(client, user_id)
        if not dm_channel_id:
            return False

        kwargs: dict[str, Any] = {"channel": dm_channel_id, "text": text}
        if blocks:
            kwargs["blocks"] = blocks

        response = client.chat_postMessage(**kwargs)
        return response["ok"]

    except SlackApiError as e:
        logger.error("Failed to send DM to %s: %s", user_id, e)
        return False
