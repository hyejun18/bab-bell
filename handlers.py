"""Slack event and action handlers for BabBell bot."""

import logging
import time
from threading import Lock
from typing import Any

from slack_bolt import Ack, App, Say
from slack_sdk import WebClient

import re

from broadcast import broadcast, send_dm
from buttons import ACTION_ID_PREFIX, build_button_blocks, get_button
from config import COOLDOWN_SECONDS, DEDUP_TTL_SECONDS
from db import unsubscribe_user, upsert_user
from poll import (
    POLL_ACTION_PREFIX,
    broadcast_poll,
    create_poll,
    record_vote,
    render_poll_blocks,
    save_poll_message,
    update_all_poll_messages,
    update_single_poll_message,
    register_client,
)

logger = logging.getLogger(__name__)

# In-memory caches with locks
_dedup_cache: dict[str, float] = {}  # key -> timestamp
_dedup_lock = Lock()

_cooldown_cache: dict[str, float] = {}  # (user_id, action) -> timestamp
_cooldown_lock = Lock()


def _cleanup_expired_cache(cache: dict[str, float], ttl: float) -> None:
    """Remove expired entries from cache."""
    now = time.time()
    expired = [k for k, v in cache.items() if now - v > ttl]
    for k in expired:
        del cache[k]


def _is_duplicate(key: str) -> bool:
    """Check if this action is a duplicate (within TTL)."""
    now = time.time()
    with _dedup_lock:
        _cleanup_expired_cache(_dedup_cache, DEDUP_TTL_SECONDS)
        if key in _dedup_cache:
            return True
        _dedup_cache[key] = now
        return False


def _is_on_cooldown(user_id: str, action: str) -> tuple[bool, int]:
    """Check if user is on cooldown for this action.

    Returns (is_on_cooldown, remaining_seconds).
    """
    now = time.time()
    key = f"{user_id}:{action}"
    with _cooldown_lock:
        _cleanup_expired_cache(_cooldown_cache, COOLDOWN_SECONDS)
        if key in _cooldown_cache:
            elapsed = now - _cooldown_cache[key]
            remaining = int(COOLDOWN_SECONDS - elapsed)
            if remaining > 0:
                return True, remaining
        _cooldown_cache[key] = now
        return False, 0


def _get_user_info(client: WebClient, user_id: str) -> dict[str, Any]:
    """Fetch user info from Slack API."""
    try:
        response = client.users_info(user=user_id)
        if response["ok"]:
            user = response["user"]
            return {
                "slack_name": user.get("name"),
                "display_name": user.get("profile", {}).get("display_name"),
                "real_name": user.get("profile", {}).get("real_name"),
            }
    except Exception as e:
        logger.error("Failed to fetch user info for %s: %s", user_id, e)
    return {}


def register_handlers(app: App, workspace_id: str) -> None:
    """Register all event and action handlers with the app.

    Args:
        app: Slack Bolt App instance
        workspace_id: Workspace ID for this app instance
    """
    # Register client for cross-workspace operations (e.g., poll updates)
    register_client(workspace_id, app.client)

    @app.event("message")
    def handle_dm_message(event: dict, client: WebClient, say: Say) -> None:
        """Handle direct messages to the bot (opt-in subscription)."""
        # Only process DM messages (im channel type)
        channel_type = event.get("channel_type")
        if channel_type != "im":
            return

        # Ignore bot messages
        if event.get("bot_id") or event.get("subtype"):
            return

        user_id = event.get("user")
        if not user_id:
            return

        # Check if already subscribed
        from db import get_user
        existing_user = get_user(workspace_id, user_id)
        was_subscribed = existing_user and existing_user.is_subscribed

        logger.info("Received DM from user %s in workspace %s, was_subscribed=%s", user_id, workspace_id, was_subscribed)

        # Fetch user info
        user_info = _get_user_info(client, user_id)

        # Get DM channel ID from event
        dm_channel_id = event.get("channel")

        # Upsert user with is_subscribed=1
        upsert_user(
            workspace_id=workspace_id,
            slack_user_id=user_id,
            slack_name=user_info.get("slack_name"),
            display_name=user_info.get("display_name"),
            real_name=user_info.get("real_name"),
            dm_channel_id=dm_channel_id,
            is_subscribed=True,
        )

        # Send response with button blocks
        blocks = build_button_blocks()
        if was_subscribed:
            # Already subscribed - just show buttons
            say(
                text="밥벨 버튼",
                blocks=blocks,
            )
        else:
            # New or re-subscription
            say(
                text="구독 처리 완료! 이제 밥벨을 받습니다.",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": ":white_check_mark: *구독 처리 완료!* 이제 밥벨을 받습니다."},
                    },
                    {"type": "divider"},
                ]
                + blocks,
            )

    # Pattern match all babbell_* action IDs
    @app.action(re.compile(f"^{ACTION_ID_PREFIX}"))
    def handle_button_action(ack: Ack, body: dict, client: WebClient) -> None:
        """Handle all button actions (pattern matched action_id)."""
        ack()

        user_id = body["user"]["id"]
        action = body["actions"][0]
        action_value = action.get("value", "")
        action_ts = action.get("action_ts", "")
        action_id = action.get("action_id", "")
        message_ts = body.get("container", {}).get("message_ts", "")

        # Build dedup key
        dedup_key = f"{message_ts}:{user_id}:{action_id}:{action_value}:{action_ts}"

        # Check for duplicate
        if _is_duplicate(dedup_key):
            logger.info("Duplicate action detected, ignoring: %s", dedup_key)
            send_dm(client, user_id, "이미 처리된 요청입니다.")
            return

        # Get button definition
        button = get_button(action_value)
        if not button:
            logger.warning("Unknown action value: %s", action_value)
            send_dm(client, user_id, "알 수 없는 버튼입니다.")
            return

        logger.info("Action received: user=%s action=%s", user_id, action_value)

        # Handle OPT_OUT
        if action_value == "OPT_OUT":
            _handle_opt_out(client, user_id)
            return

        # Handle START_POLL
        if action_value == "START_POLL":
            _handle_start_poll(client, user_id)
            return

        # Handle broadcast actions
        if button.is_broadcast:
            _handle_broadcast_action(client, user_id, button)
            return

    def _handle_opt_out(client: WebClient, user_id: str) -> None:
        """Handle opt-out (unsubscribe) action."""
        unsubscribe_user(workspace_id, user_id)
        logger.info("User %s in workspace %s opted out", user_id, workspace_id)
        send_dm(
            client,
            user_id,
            "수신 거부 처리 완료. 다시 받으려면 봇에게 아무 메시지나 보내세요.",
        )

    def _handle_broadcast_action(
        client: WebClient, user_id: str, button: Any
    ) -> None:
        """Handle broadcast button action."""
        # Check cooldown
        on_cooldown, remaining = _is_on_cooldown(user_id, button.value)
        if on_cooldown:
            logger.info(
                "User %s on cooldown for %s, %d seconds remaining",
                user_id,
                button.value,
                remaining,
            )
            send_dm(
                client,
                user_id,
                f"쿨다운 중입니다. {remaining}초 후에 다시 시도해주세요.",
            )
            return

        # Execute broadcast to this workspace only
        result = broadcast(client, workspace_id, button, user_id)

        # Send summary DM to initiator
        if result.failure_count == 0:
            summary = (
                f":white_check_mark: 브로드캐스트 완료!\n"
                f"• 액션: {button.label}\n"
                f"• 성공: {result.success_count}명"
            )
        else:
            summary = (
                f":warning: 브로드캐스트 완료 (일부 실패)\n"
                f"• 액션: {button.label}\n"
                f"• 성공: {result.success_count}명\n"
                f"• 실패: {result.failure_count}명"
            )

        send_dm(client, user_id, summary)

    def _handle_start_poll(client: WebClient, user_id: str) -> None:
        """Handle start poll action."""
        # Check cooldown (use longer cooldown for poll start)
        on_cooldown, remaining = _is_on_cooldown(user_id, "START_POLL")
        if on_cooldown:
            logger.info("User %s on cooldown for START_POLL, %d seconds remaining", user_id, remaining)
            send_dm(client, user_id, f"쿨다운 중입니다. {remaining}초 후에 다시 시도해주세요.")
            return

        # Create poll and broadcast to ALL workspaces
        poll_id = create_poll()
        success, failure = broadcast_poll(poll_id, user_id)

        summary = (
            f":ballot_box: 투표 시작!\n"
            f"• 성공: {success}명\n"
            f"• 실패: {failure}명"
        )
        send_dm(client, user_id, summary)

    # Poll vote handler
    @app.action(re.compile(f"^{POLL_ACTION_PREFIX}vote_"))
    def handle_poll_vote(ack: Ack, body: dict, client: WebClient) -> None:
        """Handle poll vote button clicks."""
        ack()

        user_id = body["user"]["id"]
        action = body["actions"][0]
        action_id = action.get("action_id", "")
        restaurant = action.get("value", "")

        # Extract poll_id from action_id: poll_vote_{poll_id}
        poll_id = action_id.replace(f"{POLL_ACTION_PREFIX}vote_", "")

        if not poll_id or not restaurant:
            logger.warning("Invalid poll vote: action_id=%s value=%s", action_id, restaurant)
            return

        logger.info("Poll vote: workspace=%s user=%s poll=%s restaurant=%s", workspace_id, user_id, poll_id, restaurant)

        # Record vote with workspace_id
        success, _ = record_vote(poll_id, workspace_id, user_id, restaurant)
        if not success:
            send_dm(client, user_id, "이 투표는 이미 종료되었습니다.")
            return

        # Update all poll messages across all workspaces (real-time sync)
        update_all_poll_messages(poll_id)

    # Poll refresh handler
    @app.action(re.compile(f"^{POLL_ACTION_PREFIX}refresh_"))
    def handle_poll_refresh(ack: Ack, body: dict, client: WebClient) -> None:
        """Handle poll refresh button clicks."""
        ack()

        user_id = body["user"]["id"]
        action = body["actions"][0]
        action_id = action.get("action_id", "")

        # Extract poll_id from action_id: poll_refresh_{poll_id}
        poll_id = action_id.replace(f"{POLL_ACTION_PREFIX}refresh_", "")

        if not poll_id:
            logger.warning("Invalid poll refresh: action_id=%s", action_id)
            return

        # Get message info from body
        channel_id = body.get("container", {}).get("channel_id")
        message_ts = body.get("container", {}).get("message_ts")

        if channel_id and message_ts:
            # Update just this user's message
            update_single_poll_message(client, poll_id, workspace_id, user_id, channel_id, message_ts)
            # Also save/update the message reference
            save_poll_message(poll_id, workspace_id, user_id, channel_id, message_ts)
