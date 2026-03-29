from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi import HTTPException

import nba_client

MCCAIN_ID = 1642272
OKC_TEAM_ID = 1610612760


# ── get_active_players ──────────────────────────────────────────────


@patch("nba_client.players.get_active_players")
def test_get_active_players_returns_list(mock_get):
    mock_get.return_value = [
        {"id": MCCAIN_ID, "full_name": "Jared McCain", "first_name": "Jared",
         "last_name": "McCain", "is_active": True},
    ]
    result = nba_client.get_active_players()
    assert len(result) == 1
    assert result[0]["full_name"] == "Jared McCain"


# ── get_player_info ─────────────────────────────────────────────────


def _mock_player_frames(include_stats=True, missing_name=False):
    """Build the 3-frame list that CommonPlayerInfo returns."""
    player_data = {
        "PERSON_ID": [MCCAIN_ID],
        "DISPLAY_FIRST_LAST": [None if missing_name else "Jared McCain"],
        "BIRTHDATE": ["2004-08-27T00:00:00"],
        "HEIGHT": ["6-3"],
        "WEIGHT": [185.0],
        "POSITION": ["Guard"],
        "JERSEY": ["0"],
        "TEAM_ID": [1610612755],
        "TEAM_NAME": ["76ers"],
        "TEAM_CITY": ["Philadelphia"],
        "TEAM_ABBREVIATION": ["PHI"],
        "SEASON_EXP": [1],
        "ROSTERSTATUS": ["Active"],
        "DRAFT_YEAR": ["2024"],
        "DRAFT_ROUND": ["1"],
        "DRAFT_NUMBER": ["16"],
    }
    df_player = pd.DataFrame(player_data)

    if include_stats:
        df_stats = pd.DataFrame({"PTS": [15.3], "AST": [3.2], "REB": [2.8]})
    else:
        df_stats = pd.DataFrame()

    return [df_player, df_stats]


@patch("nba_client.commonplayerinfo.CommonPlayerInfo")
def test_get_player_info_success(mock_cls):
    mock_cls.return_value.get_data_frames.return_value = _mock_player_frames()
    result = nba_client.get_player_info(MCCAIN_ID)
    assert isinstance(result["player_id"], int)
    assert isinstance(result["full_name"], str)
    assert isinstance(result["birthdate"], str)
    assert isinstance(result["height"], str)
    assert isinstance(result["weight"], str)
    assert isinstance(result["position"], str)
    assert isinstance(result["jersey"], str)
    assert isinstance(result["team_id"], int)
    assert isinstance(result["team_name"], str)
    assert isinstance(result["team_city"], str)
    assert isinstance(result["team_abbreviation"], str)
    assert isinstance(result["season_experience"], int)
    assert isinstance(result["roster_status"], str)
    assert isinstance(result["draft_year"], str)
    assert isinstance(result["draft_round"], str)
    assert isinstance(result["draft_number"], str)
    assert isinstance(result["season_stats"], dict)
    assert isinstance(result["season_stats"]["pts"], float)
    assert isinstance(result["season_stats"]["ast"], float)
    assert isinstance(result["season_stats"]["reb"], float)


@patch("nba_client.commonplayerinfo.CommonPlayerInfo")
def test_get_player_info_no_stats(mock_cls):
    mock_cls.return_value.get_data_frames.return_value = _mock_player_frames(include_stats=False)
    result = nba_client.get_player_info(MCCAIN_ID)
    assert result["season_stats"] is None


@patch("nba_client.commonplayerinfo.CommonPlayerInfo")
def test_get_player_info_missing_name_fallback(mock_cls):
    mock_cls.return_value.get_data_frames.return_value = _mock_player_frames(missing_name=True)
    result = nba_client.get_player_info(MCCAIN_ID)
    assert result["full_name"] == "Unknown"


@patch("nba_client.commonplayerinfo.CommonPlayerInfo")
def test_get_player_info_empty_df_404(mock_cls):
    mock_cls.return_value.get_data_frames.return_value = [pd.DataFrame(), pd.DataFrame()]
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_player_info(MCCAIN_ID)
    assert exc_info.value.status_code == 404


@patch("nba_client.commonplayerinfo.CommonPlayerInfo")
def test_get_player_info_api_failure_503(mock_cls):
    mock_cls.side_effect = ConnectionError("timeout")
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_player_info(MCCAIN_ID)
    assert exc_info.value.status_code == 503


# ── get_next_game ───────────────────────────────────────────────────


def _make_schedule_df(rows):
    """Build a schedule DataFrame from a list of row dicts."""
    return pd.DataFrame(rows)


@patch("nba_client.datetime")
@patch("nba_client.scheduleleaguev2.ScheduleLeagueV2")
def test_get_next_game_has_game_today(mock_sched_cls, mock_dt):
    today = date(2026, 3, 28)
    mock_now = MagicMock()
    mock_now.date.return_value = today
    mock_dt.now.return_value = mock_now
    mock_dt.strptime.side_effect = datetime.strptime

    df = _make_schedule_df([{
        "gameId": "0022500001",
        "homeTeam_teamId": OKC_TEAM_ID,
        "awayTeam_teamId": 1610612755,
        "gameDateEst": "2026-03-28",
        "gameStatusText": "7:00 pm ET",
    }])
    mock_sched_cls.return_value.get_data_frames.return_value = [df]

    result = nba_client.get_next_game(OKC_TEAM_ID)
    assert result["has_game_today"] is True
    assert isinstance(result["game_id"], str)
    assert isinstance(result["start_time_utc"], str)
    assert result["start_time_utc"].endswith("Z")


@patch("nba_client.datetime")
@patch("nba_client.scheduleleaguev2.ScheduleLeagueV2")
def test_get_next_game_no_game_today(mock_sched_cls, mock_dt):
    today = date(2026, 3, 28)
    mock_now = MagicMock()
    mock_now.date.return_value = today
    mock_dt.now.return_value = mock_now
    mock_dt.strptime.side_effect = datetime.strptime

    df = _make_schedule_df([{
        "gameId": "0022500002",
        "homeTeam_teamId": OKC_TEAM_ID,
        "awayTeam_teamId": 1610612755,
        "gameDateEst": "2026-03-30",
        "gameStatusText": "8:00 pm ET",
    }])
    mock_sched_cls.return_value.get_data_frames.return_value = [df]

    result = nba_client.get_next_game(OKC_TEAM_ID)
    assert result["has_game_today"] is False
    assert isinstance(result["game_id"], str)
    assert result["start_time_utc"] is None


@patch("nba_client.datetime")
@patch("nba_client.scheduleleaguev2.ScheduleLeagueV2")
def test_get_next_game_live_game_prioritized(mock_sched_cls, mock_dt):
    today = date(2026, 3, 28)
    mock_now = MagicMock()
    mock_now.date.return_value = today
    mock_dt.now.return_value = mock_now
    mock_dt.strptime.side_effect = datetime.strptime

    df = _make_schedule_df([
        {
            "gameId": "0022500003",
            "homeTeam_teamId": OKC_TEAM_ID,
            "awayTeam_teamId": 1610612755,
            "gameDateEst": "2026-03-28",
            "gameStatusText": "7:00 pm ET",
        },
        {
            "gameId": "0022500004",
            "homeTeam_teamId": OKC_TEAM_ID,
            "awayTeam_teamId": 1610612744,
            "gameDateEst": "2026-03-28",
            "gameStatusText": "3rd Qtr",
        },
    ])
    mock_sched_cls.return_value.get_data_frames.return_value = [df]

    result = nba_client.get_next_game(OKC_TEAM_ID)
    assert result["has_game_today"] is True
    assert result["game_id"] == "0022500004"
    assert result["start_time_utc"] is None


@patch("nba_client.datetime")
@patch("nba_client.scheduleleaguev2.ScheduleLeagueV2")
def test_get_next_game_all_past_games_404(mock_sched_cls, mock_dt):
    today = date(2026, 3, 28)
    mock_now = MagicMock()
    mock_now.date.return_value = today
    mock_dt.now.return_value = mock_now
    mock_dt.strptime.side_effect = datetime.strptime

    df = _make_schedule_df([{
        "gameId": "0022500005",
        "homeTeam_teamId": OKC_TEAM_ID,
        "awayTeam_teamId": 1610612755,
        "gameDateEst": "2026-03-27",
        "gameStatusText": "Final",
    }])
    mock_sched_cls.return_value.get_data_frames.return_value = [df]

    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_next_game(OKC_TEAM_ID)
    assert exc_info.value.status_code == 404


@patch("nba_client.datetime")
@patch("nba_client.scheduleleaguev2.ScheduleLeagueV2")
def test_get_next_game_away_team(mock_sched_cls, mock_dt):
    today = date(2026, 3, 28)
    mock_now = MagicMock()
    mock_now.date.return_value = today
    mock_dt.now.return_value = mock_now
    mock_dt.strptime.side_effect = datetime.strptime

    df = _make_schedule_df([{
        "gameId": "0022500006",
        "homeTeam_teamId": 1610612755,
        "awayTeam_teamId": OKC_TEAM_ID,
        "gameDateEst": "2026-03-28",
        "gameStatusText": "7:00 pm ET",
    }])
    mock_sched_cls.return_value.get_data_frames.return_value = [df]

    result = nba_client.get_next_game(OKC_TEAM_ID)
    assert result["has_game_today"] is True
    assert isinstance(result["game_id"], str)
    assert isinstance(result["start_time_utc"], str)


@patch("nba_client.scheduleleaguev2.ScheduleLeagueV2")
def test_get_next_game_no_games_404(mock_sched_cls):
    df = _make_schedule_df([{
        "gameId": "0022500007",
        "homeTeam_teamId": 9999,
        "awayTeam_teamId": 8888,
        "gameDateEst": "2026-03-28",
        "gameStatusText": "7:00 pm ET",
    }])
    mock_sched_cls.return_value.get_data_frames.return_value = [df]

    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_next_game(OKC_TEAM_ID)
    assert exc_info.value.status_code == 404


@patch("nba_client.scheduleleaguev2.ScheduleLeagueV2")
def test_get_next_game_api_failure_503(mock_sched_cls):
    mock_sched_cls.side_effect = ConnectionError("timeout")
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_next_game(OKC_TEAM_ID)
    assert exc_info.value.status_code == 503


# ── get_checkins ────────────────────────────────────────────────────


def _make_pbp_actions(actions):
    mock_pbp = MagicMock()
    mock_pbp.get_dict.return_value = {"game": {"actions": actions}}
    return mock_pbp


@patch("nba_client.LivePlayByPlay")
def test_checkins_first_poll_sub_in(mock_pbp_cls):
    """Player's last sub is 'in' — should be on court."""
    actions = [
        {"actionNumber": 1, "actionType": "substitution", "subType": "in", "personId": MCCAIN_ID},
        {"actionNumber": 2, "actionType": "substitution", "subType": "out", "personId": MCCAIN_ID},
        {"actionNumber": 3, "actionType": "substitution", "subType": "in", "personId": MCCAIN_ID},
    ]
    mock_pbp_cls.return_value = _make_pbp_actions(actions)
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert isinstance(result["player_checked_in"], bool)
    assert result["player_checked_in"] is True
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 3


@patch("nba_client.LivePlayByPlay")
def test_checkins_first_poll_starter_subbed_out(mock_pbp_cls):
    """Starter whose only sub is 'out' — not on court, no sub-in in actions."""
    actions = [
        {"actionNumber": 1, "actionType": "2pt", "personId": MCCAIN_ID},
        {"actionNumber": 2, "actionType": "substitution", "subType": "out", "personId": MCCAIN_ID},
    ]
    mock_pbp_cls.return_value = _make_pbp_actions(actions)
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 2


@patch("nba_client.LivePlayByPlay")
def test_checkins_first_poll_starter_no_subs(mock_pbp_cls):
    """Starter with game actions but no subs — should be detected as on court."""
    actions = [
        {"actionNumber": 1, "actionType": "2pt", "personId": MCCAIN_ID},
        {"actionNumber": 2, "actionType": "rebound", "personId": MCCAIN_ID},
    ]
    mock_pbp_cls.return_value = _make_pbp_actions(actions)
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is True
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 2


@patch("nba_client.LivePlayByPlay")
def test_checkins_first_poll_no_actions(mock_pbp_cls):
    """Player has no actions at all — not on court."""
    actions = [
        {"actionNumber": 1, "actionType": "2pt", "personId": 9999},
    ]
    mock_pbp_cls.return_value = _make_pbp_actions(actions)
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 1


@patch("nba_client.LivePlayByPlay")
def test_checkins_subsequent_poll_sub_in(mock_pbp_cls):
    """Subsequent poll finds a new sub-in for the player."""
    actions = [
        {"actionNumber": 10, "actionType": "2pt", "personId": 9999},
        {"actionNumber": 15, "actionType": "substitution", "subType": "in", "personId": MCCAIN_ID},
    ]
    mock_pbp_cls.return_value = _make_pbp_actions(actions)
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=10)
    assert isinstance(result["player_checked_in"], bool)
    assert result["player_checked_in"] is True
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 15


@patch("nba_client.LivePlayByPlay")
def test_checkins_subsequent_poll_no_sub_in(mock_pbp_cls):
    """Subsequent poll with no new sub-in for the player."""
    actions = [
        {"actionNumber": 10, "actionType": "2pt", "personId": 9999},
        {"actionNumber": 15, "actionType": "substitution", "subType": "out", "personId": MCCAIN_ID},
    ]
    mock_pbp_cls.return_value = _make_pbp_actions(actions)
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=10)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 15


@patch("nba_client.LivePlayByPlay")
def test_checkins_empty_actions(mock_pbp_cls):
    """No actions at all in the play-by-play."""
    mock_pbp_cls.return_value = _make_pbp_actions([])
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert isinstance(result["player_checked_in"], bool)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 0


@patch("nba_client.LivePlayByPlay")
def test_checkins_game_not_started_404(mock_pbp_cls):
    """Game not started — LivePlayByPlay returns empty JSON."""
    import json
    mock_pbp_cls.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_checkins("0022500001", MCCAIN_ID)
    assert exc_info.value.status_code == 404


@patch("nba_client.LivePlayByPlay")
def test_checkins_api_failure_503(mock_pbp_cls):
    mock_pbp_cls.side_effect = ConnectionError("timeout")
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_checkins("0022500001", MCCAIN_ID)
    assert exc_info.value.status_code == 503
