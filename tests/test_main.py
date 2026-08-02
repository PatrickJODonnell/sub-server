from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

MCCAIN_ID = 1642272


# ── GET /players ────────────────────────────────────────────────────


@patch("nba_client.get_active_players")
def test_list_players(mock_get):
    mock_get.return_value = [
        {"id": MCCAIN_ID, "full_name": "Jared McCain", "first_name": "Jared", "last_name": "McCain", "is_active": True},
    ]
    resp = client.get("/players")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["player_id"] == MCCAIN_ID
    assert data[0]["full_name"] == "Jared McCain"
    assert data[0]["first_name"] == "Jared"
    assert data[0]["last_name"] == "McCain"
    assert data[0]["is_active"] is True


@patch("nba_client.get_active_players")
def test_list_players_empty(mock_get):
    mock_get.return_value = []
    resp = client.get("/players")
    assert resp.status_code == 200
    assert resp.json() == []


@patch("nba_client.get_active_players")
def test_list_players_multiple(mock_get):
    mock_get.return_value = [
        {"id": MCCAIN_ID, "full_name": "Jared McCain", "first_name": "Jared", "last_name": "McCain", "is_active": True},
        {"id": 203999, "full_name": "Nikola Jokic", "first_name": "Nikola", "last_name": "Jokic", "is_active": True},
    ]
    resp = client.get("/players")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["player_id"] == MCCAIN_ID
    assert data[1]["player_id"] == 203999
    assert data[1]["full_name"] == "Nikola Jokic"


# ── GET /players/{player_id} ───────────────────────────────────────


@patch("nba_client.get_player_info")
def test_get_player_with_stats(mock_info):
    mock_info.return_value = {
        "player_id": MCCAIN_ID,
        "full_name": "Jared McCain",
        "birthdate": "2004-08-27",
        "height": "6-3",
        "weight": "185",
        "position": "Guard",
        "jersey": "0",
        "team_name": "Oklahoma City Thunder",
        "season_experience": 1,
        "roster_status": "Active",
        "draft_year": "2024",
        "draft_round": "1",
        "draft_number": "16",
        "season_stats": {"pts": 15.3, "ast": 3.2, "reb": 2.8},
        "next_game": {"game_id": "401898389", "has_game_today": True, "start_time_utc": "2026-10-07T00:00:00Z"},
    }
    resp = client.get("/players/jared-mccain", params={"player_name": "Jared McCain"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["player_id"], int)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["birthdate"], str)
    assert isinstance(data["height"], str)
    assert isinstance(data["weight"], str)
    assert isinstance(data["position"], str)
    assert isinstance(data["jersey"], str)
    assert isinstance(data["team_name"], str)
    assert isinstance(data["season_experience"], int)
    assert isinstance(data["roster_status"], str)
    assert isinstance(data["draft_year"], str)
    assert isinstance(data["draft_round"], str)
    assert isinstance(data["draft_number"], str)
    assert isinstance(data["season_stats"], dict)
    assert isinstance(data["season_stats"]["pts"], float)
    assert isinstance(data["season_stats"]["ast"], float)
    assert isinstance(data["season_stats"]["reb"], float)
    assert isinstance(data["next_game"], dict)
    assert data["next_game"]["game_id"] == "401898389"
    assert data["next_game"]["has_game_today"] is True
    assert isinstance(data["next_game"]["start_time_utc"], str)


@patch("nba_client.get_player_info")
def test_get_player_without_stats(mock_info):
    mock_info.return_value = {
        "player_id": MCCAIN_ID,
        "full_name": "Jared McCain",
        "birthdate": None,
        "height": None,
        "weight": None,
        "position": None,
        "jersey": None,
        "team_name": None,
        "season_experience": None,
        "roster_status": None,
        "draft_year": None,
        "draft_round": None,
        "draft_number": None,
        "season_stats": None,
        "next_game": {"game_id": None, "has_game_today": False, "start_time_utc": None},
    }
    resp = client.get("/players/jared-mccain", params={"player_name": "Jared McCain"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["player_id"], int)
    assert isinstance(data["full_name"], str)
    assert data["season_stats"] is None
    for field in ["birthdate", "height", "weight", "position", "jersey",
                  "team_name", "season_experience", "roster_status",
                  "draft_year", "draft_round", "draft_number"]:
        assert data[field] is None
    assert data["next_game"]["game_id"] is None
    assert data["next_game"]["has_game_today"] is False
    assert data["next_game"]["start_time_utc"] is None


@patch("nba_client.get_player_info")
def test_get_player_not_found(mock_info):
    mock_info.side_effect = HTTPException(status_code=404, detail="Player not found")
    resp = client.get("/players/jared-mccain", params={"player_name": "Jared McCain"})
    assert resp.status_code == 404


@patch("nba_client.get_player_info")
def test_get_player_api_failure(mock_info):
    mock_info.side_effect = HTTPException(status_code=503, detail="NBA API request failed")
    resp = client.get("/players/jared-mccain", params={"player_name": "Jared McCain"})
    assert resp.status_code == 503


# ── GET /games/{game_id}/checkins/{player_id} ───────────────────────


@patch("nba_client.get_checkins")
def test_checkins_valid_game_id(mock_ci):
    mock_ci.return_value = {"player_checked_in": True, "last_event_num": 42}
    resp = client.get(f"/games/0022500001/checkins/{MCCAIN_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["player_checked_in"], bool)
    assert data["player_checked_in"] is True
    assert isinstance(data["last_event_num"], int)
    assert data["last_event_num"] == 42


@patch("nba_client.get_checkins")
def test_checkins_with_last_event_num(mock_ci):
    mock_ci.return_value = {"player_checked_in": False, "last_event_num": 100}
    resp = client.get(f"/games/0022500001/checkins/{MCCAIN_ID}?last_event_num=50")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["player_checked_in"], bool)
    assert isinstance(data["last_event_num"], int)
    mock_ci.assert_called_once_with("0022500001", MCCAIN_ID, 50)


@patch("nba_client.get_checkins")
def test_checkins_game_not_started(mock_ci):
    mock_ci.side_effect = HTTPException(status_code=404, detail="Game data not available")
    resp = client.get(f"/games/0022500001/checkins/{MCCAIN_ID}")
    assert resp.status_code == 404


@patch("nba_client.get_checkins")
def test_checkins_api_failure(mock_ci):
    mock_ci.side_effect = HTTPException(status_code=503, detail="NBA API request failed")
    resp = client.get(f"/games/0022500001/checkins/{MCCAIN_ID}")
    assert resp.status_code == 503


def test_checkins_invalid_game_id_short():
    resp = client.get(f"/games/12345/checkins/{MCCAIN_ID}")
    assert resp.status_code == 422


def test_checkins_invalid_game_id_alpha():
    resp = client.get(f"/games/abcdefghij/checkins/{MCCAIN_ID}")
    assert resp.status_code == 422


def test_checkins_invalid_game_id_too_long():
    resp = client.get(f"/games/00225000011/checkins/{MCCAIN_ID}")
    assert resp.status_code == 422
