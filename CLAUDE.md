# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
uv sync                    # Install dependencies
uv run python main.py      # Run the bot
```

## Architecture

BabBell is a Slack bot that broadcasts SNU cafeteria menus via DM. It uses Slack Bolt framework with Socket Mode (WebSocket connection, no HTTP server needed).

### Module Structure

```
main.py          # Entry point: init logging, config, db, register handlers, start socket
├─ config.py     # Environment variables and validation
├─ db.py         # SQLite layer (WAL mode, thread-local connections)
├─ handlers.py   # Event/action dispatcher with dedup & cooldown caches
├─ broadcast.py  # Message delivery engine
├─ buttons.py    # Button definitions (frozen dataclasses)
└─ menu.py       # SNU cafeteria menu scraping & rendering
```

### Data Flow

1. User sends DM → `handle_dm_message()` → auto-subscribes user
2. User clicks button → `handle_button_action()` → dedup check → cooldown check → route to handler
3. Broadcast button → `broadcast()` → fetch menu → get subscribers → send DMs → log results

### Key Patterns

- **Opt-in subscription**: Users subscribe by sending any DM, unsubscribe via button
- **Deduplication cache**: 5-minute TTL to prevent Slack retry duplicates
- **Cooldown cache**: 60-second per-action-per-user rate limit
- **DM channel caching**: Channel IDs stored in `users.dm_channel_id` to avoid repeated API lookups
- **Menu caching**: 10-minute TTL for scraped menu data

### Database Tables

- `users`: Subscriber tracking (slack_user_id, name, dm_channel_id, is_subscribed)
- `send_log`: Broadcast audit trail (broadcast_id, targets, success/failure counts)

### Adding New Buttons

1. Define button in `buttons.py` using `ButtonDefinition` dataclass
2. Add to `BUTTON_DEFINITIONS` dict
3. If it triggers broadcast, add action_id to `BROADCAST_BUTTON_VALUES` set in `handlers.py`

## Environment Variables

Required:
- `SLACK_BOT_TOKEN`: Bot User OAuth Token (xoxb-...)
- `SLACK_APP_TOKEN`: App-Level Token with connections:write scope (xapp-...)

Optional:
- `SQLITE_PATH`: Database file path (default: babbell.db)
- `MENU_URL`: Custom menu source URL
- `MENU_DISABLED`: Set to "1" to disable menu fetching
- `COOLDOWN_SECONDS`: Button cooldown period (default: 60)
