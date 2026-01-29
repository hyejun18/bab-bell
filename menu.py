"""Menu fetching and parsing module for BabBell bot.

Fetches today's menu from SNU food menu page and provides:
1. Structured dict representation (for future web aggregation)
2. Slack Block Kit rendering (for DM messages)
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from config import ENABLE_TODAYS_MENU, MENU_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)

MENU_URL = "https://snuco.snu.ac.kr/foodmenu/"

# Target restaurants (order matters for display)
# Maps display name to possible patterns in the HTML
TARGET_RESTAURANTS = {
    "학생회관식당": ["학생회관식당"],
    "3식당": ["3식당"],
    "자하연식당 2층": ["자하연식당 2층"],
    "예술계식당": ["예술계식당"],
    "두레미담": ["두레미담"],
}

# Restaurants that need special parsing (only specific section)
SELF_CORNER_ONLY = {"두레미담"}


@dataclass
class MealInfo:
    """Information for a single meal (breakfast/lunch/dinner)."""

    meal_type: str  # "breakfast", "lunch", "dinner"
    raw_text: str  # Raw menu text
    menus: list[str] = field(default_factory=list)  # Parsed menu items


@dataclass
class RestaurantMenu:
    """Menu for a single restaurant."""

    name: str
    breakfast: MealInfo | None = None
    lunch: MealInfo | None = None
    dinner: MealInfo | None = None
    selected_meal: MealInfo | None = None  # Best meal to display based on time


@dataclass
class TodaysMenu:
    """Structured representation of today's menu."""

    date: str  # YYYY-MM-DD
    restaurants: list[RestaurantMenu] = field(default_factory=list)
    fetch_error: str | None = None


# Cache
_menu_cache: TodaysMenu | None = None
_cache_timestamp: float = 0


def _clean_menu_text(raw: str, self_corner_only: bool = False) -> list[str]:
    """Clean and parse menu text into individual items.

    Args:
        raw: Raw menu text
        self_corner_only: If True, only parse <셀프코너> section
    """
    if not raw or not raw.strip():
        return []

    text = raw

    # For self-corner only restaurants, extract only that section
    if self_corner_only:
        # Find <셀프코너> section and stop at <주문식 메뉴> or end
        match = re.search(r"<셀프코너>[^<]*", text, re.DOTALL)
        if match:
            text = match.group(0)
        else:
            # Try without angle brackets
            match = re.search(r"셀프코너.*?(?=주문식|$)", text, re.DOTALL)
            if match:
                text = match.group(0)

    # Remove operation time info
    text = re.sub(r"※\s*운영시간.*", "", text)
    text = re.sub(r"※\s*혼잡시간.*", "", text)
    text = re.sub(r"※.*", "", text)

    # Split by <br> and clean
    items = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Skip lines that are just prices or notes
        if re.match(r"^[\d,]+원$", line):
            continue
        if "운영시간" in line or "혼잡시간" in line:
            continue
        if line.startswith("<") and line.endswith(">"):
            continue
        # Skip section headers
        if "셀프코너" in line or "주문식" in line:
            continue
        # Clean up common patterns
        line = re.sub(r"\s*:\s*[\d,]+원", "", line)  # Remove price
        line = line.strip()
        if line and len(line) > 1:
            items.append(line)

    return items[:5]  # Limit to 5 items


def _select_best_meal(restaurant: RestaurantMenu, now: datetime) -> MealInfo | None:
    """Select the best meal to display based on current time.

    Priority:
    1. Currently serving meal
    2. Next upcoming meal
    3. Most recent past meal
    """
    hour = now.hour

    # Define meal time ranges (approximate)
    # Breakfast: before 10:00
    # Lunch: 10:00 - 15:00
    # Dinner: after 15:00

    if hour < 10:
        # Morning - show breakfast if available, else lunch
        if restaurant.breakfast and restaurant.breakfast.menus:
            return restaurant.breakfast
        if restaurant.lunch and restaurant.lunch.menus:
            return restaurant.lunch
    elif hour < 15:
        # Midday - show lunch if available
        if restaurant.lunch and restaurant.lunch.menus:
            return restaurant.lunch
        if restaurant.dinner and restaurant.dinner.menus:
            return restaurant.dinner
    else:
        # Afternoon/evening - show dinner if available
        if restaurant.dinner and restaurant.dinner.menus:
            return restaurant.dinner
        if restaurant.lunch and restaurant.lunch.menus:
            return restaurant.lunch

    # Fallback: return any available meal
    for meal in [restaurant.lunch, restaurant.dinner, restaurant.breakfast]:
        if meal and meal.menus:
            return meal

    return None


def fetch_menu() -> TodaysMenu:
    """Fetch and parse today's menu from the website.

    Returns a structured TodaysMenu object.
    """
    global _menu_cache, _cache_timestamp

    # Check cache
    if _menu_cache and (time.time() - _cache_timestamp) < MENU_CACHE_TTL_SECONDS:
        return _menu_cache

    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    result = TodaysMenu(date=today_str)

    if not ENABLE_TODAYS_MENU:
        return result

    try:
        response = requests.get(MENU_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Find the menu table
        table = soup.find("div", id="celeb-mealtable")
        if not table:
            raise ValueError("Menu table not found")

        # Process each row
        rows = table.find_all("tr")
        found_restaurants: dict[str, RestaurantMenu] = {}

        for row in rows:
            title_td = row.find("td", class_="title")
            if not title_td:
                continue

            restaurant_name = title_td.get_text(strip=True)

            # Match against target restaurants
            matched_name = None
            for display_name, patterns in TARGET_RESTAURANTS.items():
                for pattern in patterns:
                    if pattern in restaurant_name:
                        matched_name = display_name
                        break
                if matched_name:
                    break

            if not matched_name:
                continue

            # Skip if already processed (take first occurrence)
            if matched_name in found_restaurants:
                continue

            # Parse meals
            breakfast_td = row.find("td", class_="breakfast")
            lunch_td = row.find("td", class_="lunch")
            dinner_td = row.find("td", class_="dinner")

            restaurant = RestaurantMenu(name=matched_name)
            is_self_corner = matched_name in SELF_CORNER_ONLY

            if breakfast_td:
                raw = breakfast_td.get_text("\n", strip=True)
                menus = _clean_menu_text(raw, self_corner_only=is_self_corner)
                if menus:
                    restaurant.breakfast = MealInfo(
                        meal_type="breakfast", raw_text=raw, menus=menus
                    )

            if lunch_td:
                raw = lunch_td.get_text("\n", strip=True)
                menus = _clean_menu_text(raw, self_corner_only=is_self_corner)
                if menus:
                    restaurant.lunch = MealInfo(
                        meal_type="lunch", raw_text=raw, menus=menus
                    )

            if dinner_td:
                raw = dinner_td.get_text("\n", strip=True)
                menus = _clean_menu_text(raw, self_corner_only=is_self_corner)
                if menus:
                    restaurant.dinner = MealInfo(
                        meal_type="dinner", raw_text=raw, menus=menus
                    )

            # Select best meal for current time
            restaurant.selected_meal = _select_best_meal(restaurant, today)
            found_restaurants[matched_name] = restaurant

        # Sort by TARGET_RESTAURANTS order
        for name in TARGET_RESTAURANTS.keys():
            if name in found_restaurants:
                result.restaurants.append(found_restaurants[name])

        # Update cache
        _menu_cache = result
        _cache_timestamp = time.time()

        logger.info("Menu fetched successfully for %s, %d restaurants", today_str, len(result.restaurants))

    except requests.RequestException as e:
        logger.error("Failed to fetch menu: %s", e)
        result.fetch_error = str(e)
    except Exception as e:
        logger.error("Failed to parse menu: %s", e)
        result.fetch_error = str(e)

    return result


def menu_to_dict(menu: TodaysMenu) -> dict[str, Any]:
    """Convert TodaysMenu to a plain dict (for future JSON serialization/web API)."""
    return {
        "date": menu.date,
        "fetch_error": menu.fetch_error,
        "restaurants": [
            {
                "name": r.name,
                "breakfast": (
                    {"menus": r.breakfast.menus} if r.breakfast else None
                ),
                "lunch": (
                    {"menus": r.lunch.menus} if r.lunch else None
                ),
                "dinner": (
                    {"menus": r.dinner.menus} if r.dinner else None
                ),
                "selected_meal": (
                    {
                        "meal_type": r.selected_meal.meal_type,
                        "menus": r.selected_meal.menus,
                    }
                    if r.selected_meal
                    else None
                ),
            }
            for r in menu.restaurants
        ],
    }


def render_menu_blocks(menu: TodaysMenu) -> list[dict[str, Any]]:
    """Render menu as Slack Block Kit blocks.

    Each restaurant is rendered as one line without operating hours.
    """
    if menu.fetch_error or not menu.restaurants:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*오늘의 메뉴:* 조회 실패"},
            }
        ]

    lines = ["*오늘의 메뉴*"]

    for restaurant in menu.restaurants:
        meal = restaurant.selected_meal
        if meal and meal.menus:
            menu_str = ", ".join(meal.menus)
            lines.append(f"• *{restaurant.name}*: {menu_str}")
        else:
            lines.append(f"• *{restaurant.name}*: 오늘 운영 종료")

    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        }
    ]


def render_menu_text(menu: TodaysMenu) -> str:
    """Render menu as plain text (fallback)."""
    if menu.fetch_error or not menu.restaurants:
        return "오늘의 메뉴: 조회 실패"

    lines = ["오늘의 메뉴"]

    for restaurant in menu.restaurants:
        meal = restaurant.selected_meal
        if meal and meal.menus:
            menu_str = ", ".join(meal.menus)
            lines.append(f"• {restaurant.name}: {menu_str}")
        else:
            lines.append(f"• {restaurant.name}: 오늘 운영 종료")

    return "\n".join(lines)
