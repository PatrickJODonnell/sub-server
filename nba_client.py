# ruff: noqa: BLE001
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from fastapi import HTTPException
from nba_api.stats.static import players


def _get_current_season() -> str:
    """Generating the current season string based on the time of year.
    
    If we are between seasons, use the previous year's season. If not, 
    use the current season.
    """
    current_month: int = datetime.now(ZoneInfo("America/New_York")).month
    current_year: int = datetime.now(ZoneInfo("America/New_York")).year
    if current_month >= 6 and current_month <= 10:
        # We are in the offseason. Use last year's stats
        return f'{current_year-1}-{str(current_year)[2:4]}'
    else:
        # In the season. Using this year's stats
        return f'{current_year}-{str(current_year + 1)[2:4]}'



def _retry_call(call_fn, max_attempts=3, backoff_base=1.0):
    """Retry a callable on transient errors with exponential backoff."""
    for attempt in range(max_attempts):
        try:
            return call_fn()
        except Exception:
            if attempt == max_attempts - 1:
                raise
            time.sleep(backoff_base * (2 ** attempt))



_NO_NEXT_GAME = {"game_id": "", "has_game_today": False, "start_time_utc": ""}


def _find_espn_stat(categories: list[dict], stat_name: str):
    """Look up a named stat (e.g. 'avgPoints') across ESPN statistics categories."""
    for category in categories:
        for stat in category.get("stats", []):
            if stat.get("name") == stat_name:
                return stat.get("value")
    return None


def _participant_athlete_id(play: dict, index: int) -> int | None:
    """Return the athlete id at `participants[index]` in an ESPN play, or None."""
    participants = play.get("participants") or []
    if len(participants) <= index:
        return None
    athlete_id = ((participants[index].get("athlete") or {}).get("id"))
    return int(athlete_id) if athlete_id is not None else None


def _play_has_player(play: dict, player_id: int) -> bool:
    """Whether player_id appears as any participant (entering, leaving, or otherwise) in an ESPN play."""
    return any(
        ((p.get("athlete") or {}).get("id")) is not None and int(p["athlete"]["id"]) == player_id
        for p in (play.get("participants") or [])
    )


def get_active_players() -> list[dict]:
    """
    Returns a list of active NBA players.

    Returns:
        list[dict]: A list of active NBA players.
    """
    return players.get_active_players()


def get_player_info(player_name: str) -> dict:
    """
    Returns information about a specific NBA player.

    Returns:
        dict: A dictionary containing information about the player.
    """
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
        current_season: str = _get_current_season()
        espn_season = int(current_season.split("-")[0]) + 1
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
        if season_stats is None:
            season_stats = {"pts": None, "ast": None, "reb": None}

        # Resolve the player's current team's next game via ESPN's site API.
        next_game = dict(_NO_NEXT_GAME)
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
            next_game = dict(_NO_NEXT_GAME)
        return {
            "player_id": espn_id,
            "full_name": player_name,
            "birthdate": athlete_detail["dateOfBirth"][:10] if athlete_detail.get("dateOfBirth") else None,
            "height": athlete_detail.get("displayHeight"),
            "weight": str(int(athlete_detail["weight"])) if athlete_detail.get("weight") is not None else None,
            "position": position.get("name"),
            "jersey": athlete_detail.get("jersey"),
            "team_name": athlete.get("subtitle"),
            "season_experience": experience.get("years"),
            "roster_status": status.get("name"),
            "draft_year": str(draft["year"]) if draft.get("year") is not None else None,
            "draft_round": str(draft["round"]) if draft.get("round") is not None else None,
            "draft_number": str(draft["selection"]) if draft.get("selection") is not None else None,
            "season_stats": season_stats,
            "next_game": next_game,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"get_player_info request failed: {e!s}")


def get_checkins(game_id: str, player_id: int, last_event_num: int = 0) -> dict:
    try:
        response = _retry_call(lambda: requests.get(
            f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={game_id}',
            timeout=15,
        ))
        data = response.json()
        if response.status_code != 200 or "plays" not in data:
            raise HTTPException(status_code=404, detail="Game data not available (game may not have started)")
        plays = data["plays"]

        def _seq(play: dict) -> int:
            return int(play.get("sequenceNumber", 0))

        max_event_num = max((_seq(p) for p in plays), default=0)
        new_plays = [p for p in plays if _seq(p) > last_event_num]

        def _is_sub(play: dict) -> bool:
            return (play.get("type") or {}).get("text") == "Substitution"

        # Special case: first poll (last_event_num == 0) — check if player is currently on court
        if last_event_num == 0:
            player_subs = sorted(
                (p for p in plays if _is_sub(p) and _play_has_player(p, player_id)),
                key=_seq,
            )
            if player_subs:
                is_on_court = _participant_athlete_id(player_subs[-1], 0) == player_id
            else:
                # No subs — player may be a starter who hasn't been subbed out yet.
                # Check if they show up as a participant in any play (shots, fouls, etc.)
                is_on_court = any(_play_has_player(p, player_id) for p in plays)
            if is_on_court:
                return {"player_checked_in": True, "last_event_num": max_event_num}

        # Check new plays for a SUB IN (entering participant) for the player
        sub_in = any(
            _is_sub(p) and _participant_athlete_id(p, 0) == player_id
            for p in new_plays
        )

        return {"player_checked_in": sub_in, "last_event_num": max_event_num}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {e!s}")


if __name__ == "__main__":
    get_player_info("Jared McCain")