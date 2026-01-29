"""Button definitions for BabBell bot.

To add a new button:
1. Add a new entry to BUTTON_DEFINITIONS dict
2. Set is_broadcast=True for broadcast actions, False for user-specific actions
3. Set include_menu=True if the action should include today's menu
4. The button will automatically appear in Block Kit and be routed correctly
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ButtonDefinition:
    """Definition of a single button."""

    value: str  # Action value (used in action.value)
    label: str  # Display label on button
    template: str  # Message template for broadcast (empty for non-broadcast)
    is_broadcast: bool  # Whether this action triggers a broadcast
    include_menu: bool  # Whether to include today's menu
    style: str | None = None  # "primary", "danger", or None


# Action ID prefix - each button gets unique action_id like "babbell_NOW", "babbell_IN_5"
ACTION_ID_PREFIX = "babbell_"


def get_action_id(value: str) -> str:
    """Get the action_id for a button value."""
    return f"{ACTION_ID_PREFIX}{value}"

# Button definitions - add new buttons here
BUTTON_DEFINITIONS: dict[str, ButtonDefinition] = {
    "NOW": ButtonDefinition(
        value="NOW",
        label="지금 밥",
        template=":fork_and_knife: 밥 봉화대 – 지금 바로 밥 출발합니다. :ryan_008:",
        is_broadcast=True,
        include_menu=True,
        style="primary",
    ),
    "IN_5": ButtonDefinition(
        value="IN_5",
        label="5분 뒤 밥",
        template=":fork_and_knife: 밥 봉화대 – 5분 뒤 밥 출발합니다.",
        is_broadcast=True,
        include_menu=True,
    ),
    "CANCEL": ButtonDefinition(
        value="CANCEL",
        label="취소",
        template=":fork_and_knife: 밥 봉화대 – 방금 밥 취소입니다. ㅋㅋ",
        is_broadcast=True,
        include_menu=False,
    ),
    "SNACK": ButtonDefinition(
        value="SNACK",
        label="간식",
        template=":fork_and_knife: 밥 봉화대 – 휴게실로 간식 드시러 오세요. :pizza::poultry_leg:",
        is_broadcast=True,
        include_menu=False,
    ),
    "OPT_OUT": ButtonDefinition(
        value="OPT_OUT",
        label="수신 거부",
        template="",
        is_broadcast=False,
        include_menu=False,
        style="danger",
    ),
}

# Broadcast buttons (ordered for display)
BROADCAST_BUTTON_VALUES = ["NOW", "IN_5", "CANCEL", "SNACK"]


def get_button(value: str) -> ButtonDefinition | None:
    """Get button definition by value."""
    return BUTTON_DEFINITIONS.get(value)


def build_button_blocks() -> list[dict[str, Any]]:
    """Build Block Kit blocks for all buttons.

    Returns a list of Block Kit blocks ready for chat.postMessage.
    """
    # Broadcast action buttons
    broadcast_elements = []
    for btn_value in BROADCAST_BUTTON_VALUES:
        btn = BUTTON_DEFINITIONS[btn_value]
        element: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": btn.label, "emoji": True},
            "action_id": get_action_id(btn.value),
            "value": btn.value,
        }
        if btn.style:
            element["style"] = btn.style
        broadcast_elements.append(element)

    # OPT_OUT button (separate section)
    opt_out_btn = BUTTON_DEFINITIONS["OPT_OUT"]
    opt_out_element: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": opt_out_btn.label, "emoji": True},
        "action_id": get_action_id(opt_out_btn.value),
        "value": opt_out_btn.value,
    }
    if opt_out_btn.style:
        opt_out_element["style"] = opt_out_btn.style

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":bell: *밥벨* - 버튼을 눌러 알림을 보내세요.",
            },
        },
        {"type": "actions", "elements": broadcast_elements},
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "더 이상 알림을 받고 싶지 않으면 아래 버튼을 누르세요.",
                }
            ],
        },
        {"type": "actions", "elements": [opt_out_element]},
    ]

    return blocks
