import re
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from nba_api.stats.static import players
from nba_api.stats.endpoints import commonplayerinfo, scheduleleaguev2
from nba_api.live.nba.endpoints import PlayByPlay as LivePlayByPlay

CURRENT_SEASON = "2025-26"
# NBA status text uses "1st Qtr", "2nd Qtr", "3rd Qtr", "4th Qtr", "Halftime", "OT1", etc.
LIVE_STATUS_PATTERN = re.compile(r"(\d+(st|nd|rd|th)\s+Qtr|Halftime|OT\d*)", re.IGNORECASE)


def get_active_players() -> list[dict]:
    return players.get_active_players()


def get_player_info(player_id: int) -> dict:
    try:
        info = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=10)
        frames = info.get_data_frames()
        df = frames[0]
        if df.empty:
            raise HTTPException(status_code=404, detail="Player not found")
        row = df.iloc[0]

        stats_row = None
        if len(frames) > 2 and not frames[2].empty:
            stats_row = frames[2].iloc[0]

        def _val(r, key):
            v = r.get(key) if hasattr(r, "get") else getattr(r, key, None)
            return None if (v is None or (isinstance(v, float) and v != v)) else v

        return {
            "player_id": int(row["PERSON_ID"]),
            "full_name": _val(row, "DISPLAY_FIRST_LAST"),
            "birthdate": str(row["BIRTHDATE"])[:10] if _val(row, "BIRTHDATE") else None,
            "height": _val(row, "HEIGHT"),
            "weight": str(_val(row, "WEIGHT")) if _val(row, "WEIGHT") else None,
            "position": _val(row, "POSITION"),
            "jersey": str(_val(row, "JERSEY")) if _val(row, "JERSEY") else None,
            "team_id": int(row["TEAM_ID"]) if _val(row, "TEAM_ID") else None,
            "team_name": _val(row, "TEAM_NAME"),
            "team_city": _val(row, "TEAM_CITY"),
            "team_abbreviation": _val(row, "TEAM_ABBREVIATION"),
            "season_experience": int(row["SEASON_EXP"]) if _val(row, "SEASON_EXP") is not None else None,
            "roster_status": _val(row, "ROSTERSTATUS"),
            "draft_year": str(_val(row, "DRAFT_YEAR")) if _val(row, "DRAFT_YEAR") else None,
            "draft_round": str(_val(row, "DRAFT_ROUND")) if _val(row, "DRAFT_ROUND") else None,
            "draft_number": str(_val(row, "DRAFT_NUMBER")) if _val(row, "DRAFT_NUMBER") else None,
            "season_stats": {
                "pts": float(stats_row["PTS"]) if stats_row is not None and _val(stats_row, "PTS") is not None else None,
                "ast": float(stats_row["AST"]) if stats_row is not None and _val(stats_row, "AST") is not None else None,
                "reb": float(stats_row["REB"]) if stats_row is not None and _val(stats_row, "REB") is not None else None,
            } if stats_row is not None else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {str(e)}")


def get_next_game(team_id: int) -> dict:
    try:
        schedule = scheduleleaguev2.ScheduleLeagueV2(
            league_id="00",
            season=CURRENT_SEASON,
            timeout=10,
        )
        df = schedule.get_data_frames()[0]

        team_games = df[
            (df["homeTeam_teamId"] == team_id) | (df["awayTeam_teamId"] == team_id)
        ].copy()

        if team_games.empty:
            raise HTTPException(status_code=404, detail="No games found for team")

        # NBA schedule dates are in ET; use ET date (UTC-5) to match gameDateEst
        today = (datetime.now(timezone.utc) - timedelta(hours=5)).date()

        def parse_date(val):
            try:
                return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
            except Exception:
                return None

        team_games["_parsed_date"] = team_games["gameDateEst"].apply(parse_date)
        upcoming = team_games[team_games["_parsed_date"] >= today].copy()

        if upcoming.empty:
            raise HTTPException(status_code=404, detail="No upcoming games found for team")

        # Prioritize live games
        live_games = upcoming[upcoming["gameStatusText"].apply(
            lambda s: bool(LIVE_STATUS_PATTERN.match(str(s).strip()))
        )]

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
                # ET is UTC-5 (EST) or UTC-4 (EDT); approximate with UTC-5
                start_time_utc = (t + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

        has_game_today = (row["_parsed_date"] == today)

        return {
            "has_game_today": has_game_today,
            "start_time_utc": start_time_utc if has_game_today else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {str(e)}")


def get_checkins(game_id: str, player_id: int, last_event_num: int = 0) -> dict:
    try:
        pbp = LivePlayByPlay(game_id=game_id)
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
            is_on_court = bool(all_player_subs and all_player_subs[-1].get("subType") == "in")
            if is_on_court:
                return {"player_checked_in": True, "last_event_num": max_event_num}

        # Check new events for a SUB IN for the player
        sub_in = any(
            a.get("actionType") == "substitution"
            and a.get("subType") == "in"
            and a.get("personId") == player_id
            for a in new_actions
        )

        return {"player_checked_in": sub_in, "last_event_num": max_event_num}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API request failed: {str(e)}")
