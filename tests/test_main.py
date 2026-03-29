from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

MCCAIN_ID = 1642272
OKC_TEAM_ID = 1610612760


# ── GET /players ────────────────────────────────────────────────────


@patch("nba_client.get_active_players")
def test_list_players(mock_get):
    mock_get.return_value = [
        {"id": MCCAIN_ID, "full_name": "Jared McCain", "first_name": "Jared", "last_name": "McCain", "is_active": True},
    ]
    resp = client.get("/players")
    assert resp.status_code == 200
    data = resp.json()
    print(data)
    assert len(data) == 1
    assert data[0]["player_id"] == MCCAIN_ID
    assert data[0]["full_name"] == "Jared McCain"


@patch("nba_client.get_active_players")
def test_list_players_empty(mock_get):
    mock_get.return_value = []
    resp = client.get("/players")
    assert resp.status_code == 200
    assert resp.json() == []


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
        "team_id": 1610612755,
        "team_name": "76ers",
        "team_city": "Philadelphia",
        "team_abbreviation": "PHI",
        "season_experience": 1,
        "roster_status": "Active",
        "draft_year": "2024",
        "draft_round": "1",
        "draft_number": "16",
        "season_stats": {"pts": 15.3, "ast": 3.2, "reb": 2.8},
    }
    resp = client.get(f"/players/{MCCAIN_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["full_name"] == "Jared McCain"
    assert data["season_stats"]["pts"] == 15.3


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
        "team_id": None,
        "team_name": None,
        "team_city": None,
        "team_abbreviation": None,
        "season_experience": None,
        "roster_status": None,
        "draft_year": None,
        "draft_round": None,
        "draft_number": None,
        "season_stats": None,
    }
    resp = client.get(f"/players/{MCCAIN_ID}")
    assert resp.status_code == 200
    assert resp.json()["season_stats"] is None


# ── GET /teams/{team_id}/next-game ──────────────────────────────────


@patch("nba_client.get_next_game")
def test_next_game_today(mock_ng):
    mock_ng.return_value = {"has_game_today": True, "start_time_utc": "2026-03-29T00:00:00Z"}
    resp = client.get(f"/teams/{OKC_TEAM_ID}/next-game")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_game_today"] is True
    assert data["start_time_utc"] is not None


@patch("nba_client.get_next_game")
def test_next_game_not_today(mock_ng):
    mock_ng.return_value = {"has_game_today": False, "start_time_utc": None}
    resp = client.get(f"/teams/{OKC_TEAM_ID}/next-game")
    assert resp.status_code == 200
    assert resp.json()["has_game_today"] is False


# ── GET /games/{game_id}/checkins/{player_id} ───────────────────────


@patch("nba_client.get_checkins")
def test_checkins_valid_game_id(mock_ci):
    mock_ci.return_value = {"player_checked_in": True, "last_event_num": 42}
    resp = client.get(f"/games/0022500001/checkins/{MCCAIN_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_checked_in"] is True
    assert data["last_event_num"] == 42


@patch("nba_client.get_checkins")
def test_checkins_with_last_event_num(mock_ci):
    mock_ci.return_value = {"player_checked_in": False, "last_event_num": 100}
    resp = client.get(f"/games/0022500001/checkins/{MCCAIN_ID}?last_event_num=50")
    assert resp.status_code == 200
    mock_ci.assert_called_once_with("0022500001", MCCAIN_ID, 50)


def test_checkins_invalid_game_id_short():
    resp = client.get(f"/games/12345/checkins/{MCCAIN_ID}")
    assert resp.status_code == 422


def test_checkins_invalid_game_id_alpha():
    resp = client.get(f"/games/abcdefghij/checkins/{MCCAIN_ID}")
    assert resp.status_code == 422


def test_checkins_invalid_game_id_too_long():
    resp = client.get(f"/games/00225000011/checkins/{MCCAIN_ID}")
    assert resp.status_code == 422
