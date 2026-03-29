import json
import re
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cachetools import TTLCache, cached
from fastapi import HTTPException
from nba_api.live.nba.endpoints import PlayByPlay as LivePlayByPlay
from nba_api.stats.endpoints import commonplayerinfo, scheduleleaguev2
from nba_api.stats.static import players

CURRENT_SEASON = "2025-26"

_player_cache = TTLCache(maxsize=128, ttl=300)  # 5 minutes
_player_cache_lock = threading.Lock()

_next_game_cache = TTLCache(maxsize=32, ttl=120)  # 2 minutes
_next_game_cache_lock = threading.Lock()


def _retry_call(call_fn, max_attempts=3, backoff_base=1.0):
    """Retry a callable on transient errors with exponential backoff."""
    for attempt in range(max_attempts):
        try:
            return call_fn()
        except Exception:
            if attempt == max_attempts - 1:
                raise
            time.sleep(backoff_base * (2 ** attempt))


def clear_caches():
    """Clear all caches. Useful for testing."""
    with _player_cache_lock:
        _player_cache.clear()
    with _next_game_cache_lock:
        _next_game_cache.clear()
# NBA status text uses "1st Qtr", "2nd Qtr", "3rd Qtr", "4th Qtr", "Halftime", "OT1", etc.
LIVE_STATUS_PATTERN = re.compile(r"(\d+(st|nd|rd|th)\s+Qtr|Halftime|OT\d*)", re.IGNORECASE)


def get_active_players() -> list[dict]:
    """
    Returns a list of active NBA players.

    Returns:
        list[dict]: A list of active NBA players.
    """
    return players.get_active_players()


@cached(cache=_player_cache, lock=_player_cache_lock)
def get_player_info(player_id: int) -> dict:
    """
    Returns information about a specific NBA player.

    Returns:
        dict: A dictionary containing information about the player.
    """
    try:
        info = _retry_call(lambda: commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=15))
        frames = info.get_data_frames()
        df = frames[0]
        if df.empty:
            raise HTTPException(status_code=404, detail="Player not found")
        player_row = df.iloc[0]

        stats_row = None
        if len(frames) > 1 and not frames[1].empty:
            stats_row = frames[1].iloc[0]

        def _val(r, key):
            """
            Helper function to get the value of a key from a row.

            Args:
                r (dict): The row to get the value from.
                key (str): The key to get the value from.

            Returns:
                The value of the key from the row.
            """
            v = r.get(key) if hasattr(r, "get") else getattr(r, key, None)
            return None if (v is None or (isinstance(v, float) and v != v)) else v

        return {
            "player_id": int(player_row["PERSON_ID"]),
            "full_name": _val(player_row, "DISPLAY_FIRST_LAST") or "Unknown",
            "birthdate": str(player_row["BIRTHDATE"])[:10] if _val(player_row, "BIRTHDATE") else None,
            "height": _val(player_row, "HEIGHT"),
            "weight": str(_val(player_row, "WEIGHT")) if _val(player_row, "WEIGHT") else None,
            "position": _val(player_row, "POSITION"),
            "jersey": str(_val(player_row, "JERSEY")) if _val(player_row, "JERSEY") else None,
            "team_id": int(player_row["TEAM_ID"]) if _val(player_row, "TEAM_ID") else None,
            "team_name": _val(player_row, "TEAM_NAME"),
            "team_city": _val(player_row, "TEAM_CITY"),
            "team_abbreviation": _val(player_row, "TEAM_ABBREVIATION"),
            "season_experience": int(player_row["SEASON_EXP"]) if _val(player_row, "SEASON_EXP") is not None else None,
            "roster_status": _val(player_row, "ROSTERSTATUS"),
            "draft_year": str(_val(player_row, "DRAFT_YEAR")) if _val(player_row, "DRAFT_YEAR") else None,
            "draft_round": str(_val(player_row, "DRAFT_ROUND")) if _val(player_row, "DRAFT_ROUND") else None,
            "draft_number": str(_val(player_row, "DRAFT_NUMBER")) if _val(player_row, "DRAFT_NUMBER") else None,
            "season_stats": {
                "pts": float(stats_row["PTS"])
                if stats_row is not None and _val(stats_row, "PTS") is not None
                else None,
                "ast": float(stats_row["AST"])
                if stats_row is not None and _val(stats_row, "AST") is not None
                else None,
                "reb": float(stats_row["REB"])
                if stats_row is not None and _val(stats_row, "REB") is not None
                else None,
            }
            if stats_row is not None
            else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {str(e)}")


@cached(cache=_next_game_cache, lock=_next_game_cache_lock)
def get_next_game(team_id: int) -> dict:
    """
    Returns the next game for a given team.

    Args:
        team_id (int): The ID of the team to get the next game for.

    Returns:
        dict: A dictionary containing information about the next game.
    """
    try:
        schedule = _retry_call(lambda: scheduleleaguev2.ScheduleLeagueV2(
            league_id="00",
            season=CURRENT_SEASON,
            timeout=15,
        ))
        df = schedule.get_data_frames()[0]

        team_games = df[(df["homeTeam_teamId"] == team_id) | (df["awayTeam_teamId"] == team_id)].copy()

        if team_games.empty:
            raise HTTPException(status_code=404, detail="No games found for team")

        # NBA schedule dates are in ET; use proper ET timezone for DST handling
        today = datetime.now(ZoneInfo("America/New_York")).date()

        def parse_date(val):
            """
            Helper function to parse a date from a string.

            Args:
                val (str): The string to parse the date from.

            Returns:
                The parsed date.
            """
            try:
                return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
            except Exception:
                return None

        team_games["_parsed_date"] = team_games["gameDateEst"].apply(parse_date)
        upcoming = team_games[team_games["_parsed_date"] >= today].copy()

        if upcoming.empty:
            raise HTTPException(status_code=404, detail="No upcoming games found for team")

        # Prioritize live games
        live_games = upcoming[
            upcoming["gameStatusText"].apply(lambda s: bool(LIVE_STATUS_PATTERN.match(str(s).strip())))
        ]

        if not live_games.empty:
            row = live_games.iloc[0]
        else:
            row = upcoming.sort_values("_parsed_date").iloc[0]

        status_text = str(row["gameStatusText"]).strip()
        is_live = bool(LIVE_STATUS_PATTERN.match(status_text))
        game_date = str(row["_parsed_date"])

        # Attempt to build a UTC start time from date + status time (e.g. "7:00 pm ET")
        start_time_utc = None
        time_match = re.match(r"(\d+:\d+)\s*(am|pm)\s*ET", status_text, re.IGNORECASE)
        if time_match and not is_live:
            try:
                t = datetime.strptime(f"{game_date} {time_match.group(1)} {time_match.group(2)}", "%Y-%m-%d %I:%M %p")
                t_et = t.replace(tzinfo=ZoneInfo("America/New_York"))
                start_time_utc = t_et.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

        has_game_today = row["_parsed_date"] == today
        game_id = str(row["gameId"])

        return {
            "game_id": game_id,
            "has_game_today": has_game_today,
            "start_time_utc": start_time_utc if has_game_today else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {str(e)}")


def get_checkins(game_id: str, player_id: int, last_event_num: int = 0) -> dict:
    try:
        pbp = _retry_call(lambda: LivePlayByPlay(game_id=game_id, timeout=15))
        actions = pbp.get_dict()["game"]["actions"]

        all_event_nums = [int(a["actionNumber"]) for a in actions if "actionNumber" in a]
        max_event_num = max(all_event_nums) if all_event_nums else 0

        new_actions = [a for a in actions if int(a.get("actionNumber", 0)) > last_event_num]

        # Special case: first poll (last_event_num == 0) — check if player is currently on court
        if last_event_num == 0:
            subs = [a for a in actions if a.get("actionType") == "substitution"]
            all_player_subs = sorted(
                [a for a in subs if a.get("personId") == player_id],
                key=lambda x: x["actionNumber"],
            )
            if all_player_subs:
                is_on_court = all_player_subs[-1].get("subType") == "in"
            else:
                # No subs — player may be a starter who hasn't been subbed out yet.
                # Check if they have any game actions (shots, fouls, etc.)
                player_actions = [a for a in actions if a.get("personId") == player_id]
                is_on_court = len(player_actions) > 0
            if is_on_court:
                return {"player_checked_in": True, "last_event_num": max_event_num}

        # Check new events for a SUB IN for the player
        sub_in = any(
            a.get("actionType") == "substitution" and a.get("subType") == "in" and a.get("personId") == player_id
            for a in new_actions
        )

        return {"player_checked_in": sub_in, "last_event_num": max_event_num}
    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise HTTPException(status_code=404, detail="Game data not available (game may not have started)")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {str(e)}")
