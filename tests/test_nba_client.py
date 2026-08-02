from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi import HTTPException

import nba_client

MCCAIN_ID = 1642272


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """Skip retry sleeps for all tests."""
    monkeypatch.setattr("nba_client.time.sleep", lambda _: None)


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


def _resp(payload, status=200):
    """Build a fake requests.Response with the given JSON payload and status."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


SEARCH_PAYLOAD = {
    "results": [
        {
            "type": "player",
            "contents": [
                {"uid": "s:40~l:46~a:4683778", "subtitle": "Oklahoma City Thunder"},
            ],
        },
    ],
}

ATHLETE_PAYLOAD = {
    "dateOfBirth": "2004-02-20T08:00Z",
    "displayHeight": "6' 3\"",
    "weight": 195.0,
    "position": {"name": "Guard"},
    "jersey": "3",
    "experience": {"years": 2},
    "status": {"name": "Active"},
    "draft": {"year": 2024, "round": 1, "selection": 16},
    "team": {
        "$ref": "http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2026/teams/25?lang=en&region=us",
    },
}

STATS_PAYLOAD = {
    "splits": {
        "categories": [
            {"name": "offensive", "stats": [
                {"name": "avgPoints", "value": 8.3},
                {"name": "avgAssists", "value": 1.3},
            ]},
            {"name": "general", "stats": [
                {"name": "avgRebounds", "value": 2.0},
            ]},
        ],
    },
}

TEAM_PAYLOAD = {
    "team": {
        "nextEvent": [
            {"id": "401898389", "date": "2026-10-07T00:00Z"},
        ],
    },
}


def _fake_espn_get(search=None, athlete=None, stats=None, team=None, stats_status=200, fail_on=None):
    """Build a requests.get replacement dispatching on URL substring.

    `fail_on` (a URL substring) raises ConnectionError for that one step, letting
    retry/failure tests target a single step in get_player_info's call chain.
    """
    search = SEARCH_PAYLOAD if search is None else search
    athlete = ATHLETE_PAYLOAD if athlete is None else athlete
    stats = STATS_PAYLOAD if stats is None else stats
    team = TEAM_PAYLOAD if team is None else team

    def _get(url, *args, **kwargs):
        if fail_on and fail_on in url:
            raise ConnectionError("timeout")
        if "apis/search/v2" in url:
            return _resp(search)
        if "/statistics/0" in url:
            return _resp(stats, status=stats_status)
        if "site.api.espn.com" in url:
            return _resp(team)
        return _resp(athlete)

    return _get


def _fake_espn_get_with_retry(fail_url_substring, fail_times, fail_exc=None, **payloads):
    """Like _fake_espn_get, but the step matching fail_url_substring fails
    `fail_times` times (raising `fail_exc`, default ConnectionError) before succeeding."""
    call_counts = {"target": 0}
    base_get = _fake_espn_get(**payloads)
    exc = fail_exc or ConnectionError("timeout")

    def _get(url, *args, **kwargs):
        if fail_url_substring in url:
            call_counts["target"] += 1
            if call_counts["target"] <= fail_times:
                raise exc
        return base_get(url, *args, **kwargs)

    _get.call_counts = call_counts
    return _get


@patch("nba_client.requests.get")
def test_get_player_info_success(mock_get):
    mock_get.side_effect = _fake_espn_get()
    result = nba_client.get_player_info("jared mccain")
    assert result["player_id"] == "4683778"
    assert result["full_name"] == "jared mccain"
    assert result["birthdate"] == "2004-02-20"
    assert result["height"] == "6' 3\""
    assert result["weight"] == "195"
    assert result["position"] == "Guard"
    assert result["jersey"] == "3"
    assert result["team_name"] == "Oklahoma City Thunder"
    assert result["season_experience"] == 2
    assert result["roster_status"] == "Active"
    assert result["draft_year"] == "2024"
    assert result["draft_round"] == "1"
    assert result["draft_number"] == "16"
    assert result["season_stats"] == {"pts": 8.3, "ast": 1.3, "reb": 2.0}
    assert result["next_game"]["game_id"] == "401898389"
    assert result["next_game"]["has_game_today"] is False
    assert result["next_game"]["start_time_utc"] == "2026-10-07T00:00:00Z"


@patch("nba_client.requests.get")
def test_get_player_info_not_found(mock_get):
    empty_search = {"results": [{"type": "player", "contents": []}]}
    mock_get.side_effect = _fake_espn_get(search=empty_search)
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_player_info("nobody")
    assert exc_info.value.status_code == 404


@patch("nba_client.requests.get")
def test_get_player_info_no_team_defaults_next_game(mock_get):
    """Free agent / no current team — next_game falls back to the default shape."""
    athlete_no_team = {k: v for k, v in ATHLETE_PAYLOAD.items() if k != "team"}
    mock_get.side_effect = _fake_espn_get(athlete=athlete_no_team)
    result = nba_client.get_player_info("jared mccain")
    assert result["next_game"] == {"game_id": "", "has_game_today": False, "start_time_utc": ""}
    assert result["full_name"] == "jared mccain"


@patch("nba_client.requests.get")
def test_get_player_info_team_lookup_fails_falls_back(mock_get):
    """A transient failure resolving next_game shouldn't fail the whole player lookup."""
    mock_get.side_effect = _fake_espn_get(fail_on="site.api.espn.com")
    result = nba_client.get_player_info("jared mccain")
    assert result["next_game"] == {"game_id": "", "has_game_today": False, "start_time_utc": ""}
    assert result["season_stats"] is not None


@patch("nba_client.requests.get")
def test_get_player_info_no_next_event(mock_get):
    mock_get.side_effect = _fake_espn_get(team={"team": {"nextEvent": []}})
    result = nba_client.get_player_info("jared mccain")
    assert result["next_game"] == {"game_id": "", "has_game_today": False, "start_time_utc": ""}


@patch("nba_client.requests.get")
def test_get_player_info_stats_unavailable_season_stats_blank(mock_get):
    mock_get.side_effect = _fake_espn_get(stats_status=404)
    result = nba_client.get_player_info("jared mccain")
    assert result["season_stats"] == {"pts": None, "ast": None, "reb": None}
    assert result["next_game"]["game_id"] == "401898389"


@patch("nba_client.requests.get")
def test_get_player_info_api_failure_503(mock_get):
    mock_get.side_effect = ConnectionError("timeout")
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_player_info("jared mccain")
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


# ── Caching tests ──────────────────────────────────────────────────


@patch("nba_client.requests.get")
def test_get_player_info_not_cached(mock_get):
    """get_player_info is not cached — each call hits the network."""
    mock_get.side_effect = _fake_espn_get()
    nba_client.get_player_info("jared mccain")
    nba_client.get_player_info("jared mccain")
    assert mock_get.call_count == 8  # 4 calls per lookup, twice, no caching


@patch("nba_client.LivePlayByPlay")
def test_checkins_not_cached(mock_pbp_cls):
    """get_checkins is not cached — each call hits the API."""
    mock_pbp_cls.return_value = _make_pbp_actions([
        {"actionNumber": 1, "actionType": "2pt", "personId": MCCAIN_ID},
    ])
    nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert mock_pbp_cls.call_count == 2


# ── Retry tests ────────────────────────────────────────────────────


@patch("nba_client.requests.get")
def test_get_player_info_retry_success(mock_get):
    """First attempt at the search step fails, second succeeds."""
    fake_get = _fake_espn_get_with_retry("apis/search/v2", fail_times=1)
    mock_get.side_effect = fake_get
    result = nba_client.get_player_info("jared mccain")
    assert result["full_name"] == "jared mccain"
    assert fake_get.call_counts["target"] == 2


@patch("nba_client.requests.get")
def test_get_player_info_retry_exhaustion(mock_get):
    """All 3 attempts at the search step fail — raises 503."""
    fake_get = _fake_espn_get_with_retry("apis/search/v2", fail_times=3)
    mock_get.side_effect = fake_get
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_player_info("jared mccain")
    assert exc_info.value.status_code == 503
    assert fake_get.call_counts["target"] == 3


@patch("nba_client.requests.get")
def test_get_player_info_no_retry_on_http_exception(mock_get):
    """HTTPException (e.g. 404) is not retried."""
    empty_search = {"results": [{"type": "player", "contents": []}]}
    mock_get.side_effect = _fake_espn_get(search=empty_search)
    with pytest.raises(HTTPException) as exc_info:
        nba_client.get_player_info("nobody")
    assert exc_info.value.status_code == 404
    assert mock_get.call_count == 1


@patch("nba_client.LivePlayByPlay")
def test_get_checkins_retry_success(mock_pbp_cls):
    """First attempt fails, second succeeds for checkins."""
    mock_pbp_cls.side_effect = [
        ConnectionError("timeout"),
        _make_pbp_actions([
            {"actionNumber": 1, "actionType": "2pt", "personId": MCCAIN_ID},
        ]),
    ]
    result = nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is True
    assert mock_pbp_cls.call_count == 2


# ── stats HTTP session reset (nba_api #633) ─────────────────────────


@patch("nba_client._reset_nba_stats_http_session")
@patch("nba_client.requests.get")
def test_get_player_info_success_does_not_call_stats_session_reset(mock_get, mock_reset):
    """get_player_info is fully ESPN-based (plain requests) — it never touches
    nba_api's shared HTTP session, so it has nothing to reset."""
    mock_get.side_effect = _fake_espn_get()
    nba_client.get_player_info("jared mccain")
    assert mock_reset.call_count == 0


@patch("nba_client._reset_nba_stats_http_session")
@patch("nba_client.requests.get")
def test_get_player_info_retry_readtimeout_resets_before_backoff(mock_get, mock_reset):
    """_retry_call's own reset-before-backoff still fires on ReadTimeout,
    even though get_player_info no longer has its own session-reset wrapper."""
    fake_get = _fake_espn_get_with_retry(
        "apis/search/v2", fail_times=1, fail_exc=requests.exceptions.ReadTimeout("read timed out"),
    )
    mock_get.side_effect = fake_get
    result = nba_client.get_player_info("jared mccain")
    assert result["full_name"] == "jared mccain"
    assert fake_get.call_counts["target"] == 2
    assert mock_reset.call_count == 1


@patch("nba_client._reset_nba_stats_http_session")
@patch("nba_client.LivePlayByPlay")
def test_get_checkins_success_does_not_call_stats_session_reset(mock_pbp_cls, mock_reset):
    mock_pbp_cls.return_value = _make_pbp_actions([
        {"actionNumber": 1, "actionType": "2pt", "personId": MCCAIN_ID},
    ])
    nba_client.get_checkins("0022500001", MCCAIN_ID, last_event_num=0)
    assert mock_reset.call_count == 0
