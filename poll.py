"""Poll module for restaurant voting.

Handles real-time restaurant polls with live updates across all participants.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from db import get_db, get_subscribed_users, update_user_dm_channel

logger = logging.getLogger(__name__)

# Default restaurants - can be extended via config
DEFAULT_RESTAURANTS = [
    "학생회관식당",
    "3식당",
    "자하연식당 2층",
    "예술계식당",
    "두레미담",
    "75-1동 푸드코트",
]

# Action ID prefix for poll buttons
POLL_ACTION_PREFIX = "poll_"


def get_restaurants() -> list[str]:
    """Get list of restaurant options for voting."""
    return DEFAULT_RESTAURANTS.copy()


def create_poll() -> str:
    """Create a new poll and return its ID."""
    poll_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO polls (poll_id) VALUES (?)",
            (poll_id,),
        )
    logger.info("Created new poll: %s", poll_id)
    return poll_id


def get_poll(poll_id: str) -> dict | None:
    """Get poll info by ID."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT poll_id, created_at, closed_at FROM polls WHERE poll_id = ?",
            (poll_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "poll_id": row["poll_id"],
            "created_at": row["created_at"],
            "closed_at": row["closed_at"],
        }


def is_poll_open(poll_id: str) -> bool:
    """Check if poll is still open for voting."""
    poll = get_poll(poll_id)
    return poll is not None and poll["closed_at"] is None


def record_vote(poll_id: str, user_id: str, restaurant: str) -> tuple[bool, bool]:
    """Toggle a user's vote for a restaurant.

    Returns (success, is_added) - success=False if poll is closed, is_added=True if vote added, False if removed.
    """
    if not is_poll_open(poll_id):
        return False, False

    with get_db() as conn:
        # Check if vote exists
        cursor = conn.execute(
            "SELECT 1 FROM poll_votes WHERE poll_id = ? AND user_id = ? AND restaurant_name = ?",
            (poll_id, user_id, restaurant),
        )
        exists = cursor.fetchone() is not None

        if exists:
            # Remove vote (toggle off)
            conn.execute(
                "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ? AND restaurant_name = ?",
                (poll_id, user_id, restaurant),
            )
            logger.info("Vote removed: poll=%s user=%s restaurant=%s", poll_id, user_id, restaurant)
            return True, False
        else:
            # Add vote (toggle on)
            conn.execute(
                "INSERT INTO poll_votes (poll_id, user_id, restaurant_name) VALUES (?, ?, ?)",
                (poll_id, user_id, restaurant),
            )
            logger.info("Vote added: poll=%s user=%s restaurant=%s", poll_id, user_id, restaurant)
            return True, True


def get_vote_counts(poll_id: str) -> dict[str, int]:
    """Get vote counts per restaurant."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT restaurant_name, COUNT(*) as count
            FROM poll_votes
            WHERE poll_id = ?
            GROUP BY restaurant_name
            """,
            (poll_id,),
        )
        return {row["restaurant_name"]: row["count"] for row in cursor.fetchall()}


def get_total_voters(poll_id: str) -> int:
    """Get total number of unique voters."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT COUNT(DISTINCT user_id) as count FROM poll_votes WHERE poll_id = ?",
            (poll_id,),
        )
        row = cursor.fetchone()
        return row["count"] if row else 0


def get_user_votes(poll_id: str, user_id: str) -> set[str]:
    """Get all restaurants user voted for."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT restaurant_name FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id),
        )
        return {row["restaurant_name"] for row in cursor.fetchall()}


def get_voters_for_restaurant(poll_id: str, restaurant: str) -> list[str]:
    """Get list of user IDs who voted for a restaurant."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT user_id FROM poll_votes WHERE poll_id = ? AND restaurant_name = ?",
            (poll_id, restaurant),
        )
        return [row["user_id"] for row in cursor.fetchall()]


@dataclass
class PollMessage:
    """Info about a sent poll message."""
    poll_id: str
    user_id: str
    channel_id: str
    message_ts: str


def save_poll_message(poll_id: str, user_id: str, channel_id: str, message_ts: str) -> None:
    """Save poll message info for later updates."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO poll_messages (poll_id, user_id, channel_id, message_ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(poll_id, user_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_ts = excluded.message_ts
            """,
            (poll_id, user_id, channel_id, message_ts),
        )


def get_poll_messages(poll_id: str) -> list[PollMessage]:
    """Get all poll messages for a poll."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT poll_id, user_id, channel_id, message_ts FROM poll_messages WHERE poll_id = ?",
            (poll_id,),
        )
        return [
            PollMessage(
                poll_id=row["poll_id"],
                user_id=row["user_id"],
                channel_id=row["channel_id"],
                message_ts=row["message_ts"],
            )
            for row in cursor.fetchall()
        ]


def render_poll_blocks(poll_id: str, viewer_user_id: str | None = None) -> list[dict[str, Any]]:
    """Render poll message blocks with current vote counts.

    Args:
        poll_id: The poll ID
        viewer_user_id: If provided, highlight this user's vote
    """
    restaurants = get_restaurants()
    vote_counts = get_vote_counts(poll_id)
    total_voters = get_total_voters(poll_id)
    user_votes = get_user_votes(poll_id, viewer_user_id) if viewer_user_id else set()
    is_open = is_poll_open(poll_id)

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "━━━━━━━━━━━━━━━━━━\n:ballot_box: *오늘 어디 가실래요?* (중복투표 가능)",
            },
        },
    ]

    for restaurant in restaurants:
        count = vote_counts.get(restaurant, 0)
        is_my_vote = restaurant in user_votes
        voters = get_voters_for_restaurant(poll_id, restaurant)

        # Restaurant line with vote count
        vote_indicator = " :white_check_mark:" if is_my_vote else ""
        restaurant_text = f"📍 *{restaurant}* ({count}표){vote_indicator}"

        # Add voter names
        if voters:
            voter_mentions = ", ".join(f"<@{uid}>" for uid in voters)
            restaurant_text += f"\n      └ {voter_mentions}"

        if is_open:
            # Build button based on whether user voted for this restaurant
            if is_my_vote:
                button = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✓ 취소", "emoji": True},
                    "action_id": f"{POLL_ACTION_PREFIX}vote_{poll_id}",
                    "value": restaurant,
                    "style": "danger",
                }
            else:
                button = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "투표하기", "emoji": True},
                    "action_id": f"{POLL_ACTION_PREFIX}vote_{poll_id}",
                    "value": restaurant,
                }

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": restaurant_text},
                "accessory": button,
            })
        else:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": restaurant_text},
            })

    # Total voters
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"총 투표자: {total_voters}명"},
        ],
    })

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "━━━━━━━━━━━━━━━━━━"},
    })

    # Refresh button
    if is_open:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 결과 새로고침", "emoji": True},
                    "action_id": f"{POLL_ACTION_PREFIX}refresh_{poll_id}",
                    "value": poll_id,
                },
            ],
        })
    else:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "🔒 투표가 종료되었습니다."},
            ],
        })

    return blocks


def _open_dm_channel(client: WebClient, user_id: str) -> str | None:
    """Open a DM channel with a user and return the channel ID."""
    try:
        response = client.conversations_open(users=[user_id])
        if response["ok"]:
            return response["channel"]["id"]
    except SlackApiError as e:
        logger.error("Failed to open DM with %s: %s", user_id, e)
    return None


def broadcast_poll(client: WebClient, poll_id: str, initiated_by: str) -> tuple[int, int]:
    """Broadcast poll to all subscribed users.

    Returns (success_count, failure_count).
    """
    users = get_subscribed_users()
    success_count = 0
    failure_count = 0

    logger.info("Broadcasting poll %s to %d users", poll_id, len(users))

    for user in users:
        try:
            dm_channel_id = user.dm_channel_id

            # Open DM channel if not cached
            if not dm_channel_id:
                dm_channel_id = _open_dm_channel(client, user.slack_user_id)
                if dm_channel_id:
                    update_user_dm_channel(user.slack_user_id, dm_channel_id)

            if not dm_channel_id:
                failure_count += 1
                continue

            # Render blocks for this specific user
            blocks = render_poll_blocks(poll_id, user.slack_user_id)

            response = client.chat_postMessage(
                channel=dm_channel_id,
                text="🗳️ 오늘 어디 가실래요? 투표해주세요!",
                blocks=blocks,
            )

            if response["ok"]:
                message_ts = response.get("ts")
                if message_ts:
                    save_poll_message(poll_id, user.slack_user_id, dm_channel_id, message_ts)
                success_count += 1
            else:
                failure_count += 1

        except SlackApiError as e:
            logger.error("Failed to send poll to %s: %s", user.slack_user_id, e)
            failure_count += 1

    logger.info("Poll broadcast complete: poll=%s success=%d failure=%d", poll_id, success_count, failure_count)
    return success_count, failure_count


def update_all_poll_messages(client: WebClient, poll_id: str) -> tuple[int, int]:
    """Update all poll messages with current vote counts.

    Returns (success_count, failure_count).
    """
    messages = get_poll_messages(poll_id)
    success_count = 0
    failure_count = 0

    logger.info("Updating %d poll messages for poll %s", len(messages), poll_id)

    for msg in messages:
        try:
            # Render blocks for this specific user
            blocks = render_poll_blocks(poll_id, msg.user_id)

            client.chat_update(
                channel=msg.channel_id,
                ts=msg.message_ts,
                text="🗳️ 오늘 어디 가실래요? 투표해주세요!",
                blocks=blocks,
            )
            success_count += 1

        except SlackApiError as e:
            logger.error("Failed to update poll message for %s: %s", msg.user_id, e)
            failure_count += 1

    logger.info("Poll update complete: poll=%s success=%d failure=%d", poll_id, success_count, failure_count)
    return success_count, failure_count


def update_single_poll_message(client: WebClient, poll_id: str, user_id: str, channel_id: str, message_ts: str) -> bool:
    """Update a single poll message."""
    try:
        blocks = render_poll_blocks(poll_id, user_id)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="🗳️ 오늘 어디 가실래요? 투표해주세요!",
            blocks=blocks,
        )
        return True
    except SlackApiError as e:
        logger.error("Failed to update poll message: %s", e)
        return False
