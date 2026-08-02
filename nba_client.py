import json
import re
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from cachetools import TTLCache, cached
from fastapi import HTTPException
from nba_api.library.http import NBAHTTP
from nba_api.live.nba.endpoints import PlayByPlay as LivePlayByPlay
from nba_api.stats.library.http import NBAStatsHTTP
from nba_api.stats.static import players

CURRENT_SEASON = "2025-26"

_player_cache = TTLCache(maxsize=128, ttl=300)  # 5 minutes
_player_cache_lock = threading.Lock()


def _reset_nba_stats_http_session() -> None:
    """Close and discard nba_api's cached Session (NBAStatsHTTP / NBAHTTP).

    Reusing one keep-alive connection across multiple stats.nba.com calls can hang
    subsequent requests in the same process (see nba_api issue #633).
    """
    sess = NBAHTTP._session
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
    NBAHTTP._session = None
    if "_session" in NBAStatsHTTP.__dict__:
        del NBAStatsHTTP._session


def _retry_call(call_fn, max_attempts=3, backoff_base=1.0):
    """Retry a callable on transient errors with exponential backoff."""
    for attempt in range(max_attempts):
        try:
            return call_fn()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            if isinstance(e, (requests.exceptions.Timeout, ConnectionError)):
                _reset_nba_stats_http_session()
            time.sleep(backoff_base * (2 ** attempt))


def clear_caches():
    """Clear all caches. Useful for testing."""
    with _player_cache_lock:
        _player_cache.clear()


def _find_espn_stat(categories: list[dict], stat_name: str):
    """Look up a named stat (e.g. 'avgPoints') across ESPN statistics categories."""
    for category in categories:
        for stat in category.get("stats", []):
            if stat.get("name") == stat_name:
                return stat.get("value")
    return None


def get_active_players() -> list[dict]:
    """
    Returns a list of active NBA players.

    Returns:
        list[dict]: A list of active NBA players.
    """
    return players.get_active_players()


@cached(cache=_player_cache, lock=_player_cache_lock)
def get_player_info(player_name: str) -> dict:
    """
    Returns information about a specific NBA player.

    Returns:
        dict: A dictionary containing information about the player.
    """
    try:
        try:
            # Gathering the chosen player from the larger espn api
            info = _retry_call(lambda: requests.get(f'https://site.web.api.espn.com/apis/search/v2?query={player_name}&limit=10', timeout=15))
            search_data = info.json()

            player_result = next(
                (r for r in search_data.get("results", []) if r.get("type") == "player"),
                None,
            )
            contents = player_result.get("contents") if player_result else None
            if not contents:
                raise HTTPException(status_code=404, detail="Player not found")

            athlete = contents[0]
            espn_id = next(
                part.split(":", 1)[1] for part in athlete["uid"].split("~") if part.startswith("a:")
            )

            # Pulling this specifc player's profile from the athelete api
            athlete_info = _retry_call(lambda: requests.get(f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/athletes/{espn_id}'))
            athlete_detail = athlete_info.json()

            position = athlete_detail.get("position") or {}
            draft = athlete_detail.get("draft") or {}
            status = athlete_detail.get("status") or {}
            experience = athlete_detail.get("experience") or {}

            # Regular-season per-game averages for the current season (types/2 = regular season)
            espn_season = int(CURRENT_SEASON.split("-")[0]) + 1
            season_stats = None
            try:
                stats_response = _retry_call(lambda: requests.get(
                    f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{espn_season}/types/2/athletes/{espn_id}/statistics/0?lang=en&region=us',
                    timeout=15,
                ))
                if stats_response.status_code == 200:
                    categories = stats_response.json().get("splits", {}).get("categories", [])
                    season_stats = {
                        "pts": _find_espn_stat(categories, "avgPoints"),
                        "ast": _find_espn_stat(categories, "avgAssists"),
                        "reb": _find_espn_stat(categories, "avgRebounds"),
                    }
            except Exception:
                season_stats = None

            # Resolve the player's current team's next game via ESPN's site API.
            # Note: this is ESPN's own game id, not NBA's — /checkins wiring is future work.
            next_game = {"game_id": None, "has_game_today": False, "start_time_utc": None}
            try:
                team_ref = (athlete_detail.get("team") or {}).get("$ref", "")
                team_id_match = re.search(r"/teams/(\d+)", team_ref)
                if team_id_match:
                    espn_team_id = team_id_match.group(1)
                    team_response = _retry_call(lambda: requests.get(
                        f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{espn_team_id}',
                        timeout=15,
                    ))
                    next_events = (team_response.json().get("team") or {}).get("nextEvent") or []
                    if next_events:
                        event = next_events[0]
                        event_dt_utc = datetime.strptime(event["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
                        event_date_et = event_dt_utc.astimezone(ZoneInfo("America/New_York")).date()
                        today_et = datetime.now(ZoneInfo("America/New_York")).date()
                        next_game = {
                            "game_id": event.get("id"),
                            "has_game_today": event_date_et == today_et,
                            "start_time_utc": event_dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        }
            except Exception:
                next_game = {"game_id": None, "has_game_today": False, "start_time_utc": None}

            return {
                "player_id": espn_id,
                "full_name": player_name,
                "birthdate": athlete_detail["dateOfBirth"][:10] if athlete_detail.get("dateOfBirth") else None,
                "height": athlete_detail.get("displayHeight"),
                "weight": str(int(athlete_detail["weight"])) if athlete_detail.get("weight") is not None else None,
                "position": position.get("name"),
                "jersey": athlete_detail.get("jersey"),
                "team_id": None,
                "team_name": athlete.get("subtitle"),
                "team_city": None,
                "team_abbreviation": None,
                "season_experience": experience.get("years"),
                "roster_status": status.get("name"),
                "draft_year": str(draft["year"]) if draft.get("year") is not None else None,
                "draft_round": str(draft["round"]) if draft.get("round") is not None else None,
                "draft_number": str(draft["selection"]) if draft.get("selection") is not None else None,
                "season_stats": season_stats,
                "next_game": next_game,
            }
        finally:
            _reset_nba_stats_http_session()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {e!s}")


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


if __name__ == "__main__":
    get_player_info("Jared McCain")