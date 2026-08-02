from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import sub_client

MCCAIN_ID = 1642272


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """Skip retry sleeps for all tests."""
    monkeypatch.setattr("sub_client.time.sleep", lambda _: None)


# ── get_active_players ──────────────────────────────────────────────


@patch("sub_client.players.get_active_players")
def test_get_active_players_returns_list(mock_get):
    mock_get.return_value = [
        {"id": MCCAIN_ID, "full_name": "Jared McCain", "first_name": "Jared",
         "last_name": "McCain", "is_active": True},
    ]
    result = sub_client.get_active_players()
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


@patch("sub_client.requests.get")
def test_get_player_info_success(mock_get):
    mock_get.side_effect = _fake_espn_get()
    result = sub_client.get_player_info("jared mccain")
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


@patch("sub_client.requests.get")
def test_get_player_info_not_found(mock_get):
    empty_search = {"results": [{"type": "player", "contents": []}]}
    mock_get.side_effect = _fake_espn_get(search=empty_search)
    with pytest.raises(HTTPException) as exc_info:
        sub_client.get_player_info("nobody")
    assert exc_info.value.status_code == 404


@patch("sub_client.requests.get")
def test_get_player_info_no_team_defaults_next_game(mock_get):
    """Free agent / no current team — next_game falls back to the default shape."""
    athlete_no_team = {k: v for k, v in ATHLETE_PAYLOAD.items() if k != "team"}
    mock_get.side_effect = _fake_espn_get(athlete=athlete_no_team)
    result = sub_client.get_player_info("jared mccain")
    assert result["next_game"] == {"game_id": "", "has_game_today": False, "start_time_utc": ""}
    assert result["full_name"] == "jared mccain"


@patch("sub_client.requests.get")
def test_get_player_info_team_lookup_fails_falls_back(mock_get):
    """A transient failure resolving next_game shouldn't fail the whole player lookup."""
    mock_get.side_effect = _fake_espn_get(fail_on="site.api.espn.com")
    result = sub_client.get_player_info("jared mccain")
    assert result["next_game"] == {"game_id": "", "has_game_today": False, "start_time_utc": ""}
    assert result["season_stats"] is not None


@patch("sub_client.requests.get")
def test_get_player_info_no_next_event(mock_get):
    mock_get.side_effect = _fake_espn_get(team={"team": {"nextEvent": []}})
    result = sub_client.get_player_info("jared mccain")
    assert result["next_game"] == {"game_id": "", "has_game_today": False, "start_time_utc": ""}


@patch("sub_client.requests.get")
def test_get_player_info_stats_unavailable_season_stats_blank(mock_get):
    mock_get.side_effect = _fake_espn_get(stats_status=404)
    result = sub_client.get_player_info("jared mccain")
    assert result["season_stats"] == {"pts": None, "ast": None, "reb": None}
    assert result["next_game"]["game_id"] == "401898389"


@patch("sub_client.requests.get")
def test_get_player_info_api_failure_503(mock_get):
    mock_get.side_effect = ConnectionError("timeout")
    with pytest.raises(HTTPException) as exc_info:
        sub_client.get_player_info("jared mccain")
    assert exc_info.value.status_code == 503


# ── get_checkins ────────────────────────────────────────────────────


CHECKIN_GAME_ID = "401898389"


def _sub_play(seq, entering_id, leaving_id):
    return {
        "sequenceNumber": str(seq),
        "type": {"id": "584", "text": "Substitution"},
        "participants": [{"athlete": {"id": str(entering_id)}}, {"athlete": {"id": str(leaving_id)}}],
    }


def _action_play(seq, player_id):
    return {
        "sequenceNumber": str(seq),
        "type": {"id": "402", "text": "Two Point Field Goal"},
        "participants": [{"athlete": {"id": str(player_id)}}],
    }


def _summary_resp(plays, status=200):
    return _resp({"plays": plays}, status=status)


@patch("sub_client.requests.get")
def test_checkins_first_poll_sub_in(mock_get):
    """Player's last sub has them as the entering participant — should be on court."""
    plays = [
        _sub_play(1, entering_id=MCCAIN_ID, leaving_id=9999),
        _sub_play(2, entering_id=9999, leaving_id=MCCAIN_ID),
        _sub_play(3, entering_id=MCCAIN_ID, leaving_id=9999),
    ]
    mock_get.return_value = _summary_resp(plays)
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    assert isinstance(result["player_checked_in"], bool)
    assert result["player_checked_in"] is True
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 3


@patch("sub_client.requests.get")
def test_checkins_first_poll_starter_subbed_out(mock_get):
    """Starter whose only sub has them leaving — not on court, no other participation."""
    plays = [
        _action_play(1, MCCAIN_ID),
        _sub_play(2, entering_id=9999, leaving_id=MCCAIN_ID),
    ]
    mock_get.return_value = _summary_resp(plays)
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 2


@patch("sub_client.requests.get")
def test_checkins_first_poll_starter_no_subs(mock_get):
    """Starter with game actions but no subs — should be detected as on court."""
    plays = [
        _action_play(1, MCCAIN_ID),
        _action_play(2, MCCAIN_ID),
    ]
    mock_get.return_value = _summary_resp(plays)
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is True
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 2


@patch("sub_client.requests.get")
def test_checkins_first_poll_no_participation(mock_get):
    """Player has no participation at all — not on court."""
    plays = [
        _action_play(1, 9999),
    ]
    mock_get.return_value = _summary_resp(plays)
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 1


@patch("sub_client.requests.get")
def test_checkins_subsequent_poll_sub_in(mock_get):
    """Subsequent poll finds a new sub-in (entering participant) for the player."""
    plays = [
        _action_play(10, 9999),
        _sub_play(15, entering_id=MCCAIN_ID, leaving_id=9999),
    ]
    mock_get.return_value = _summary_resp(plays)
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=10)
    assert isinstance(result["player_checked_in"], bool)
    assert result["player_checked_in"] is True
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 15


@patch("sub_client.requests.get")
def test_checkins_subsequent_poll_no_sub_in(mock_get):
    """Subsequent poll where the player only appears as the leaving participant."""
    plays = [
        _action_play(10, 9999),
        _sub_play(15, entering_id=9999, leaving_id=MCCAIN_ID),
    ]
    mock_get.return_value = _summary_resp(plays)
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=10)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 15


@patch("sub_client.requests.get")
def test_checkins_empty_plays(mock_get):
    """No plays at all yet in the summary."""
    mock_get.return_value = _summary_resp([])
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    assert isinstance(result["player_checked_in"], bool)
    assert result["player_checked_in"] is False
    assert isinstance(result["last_event_num"], int)
    assert result["last_event_num"] == 0


@patch("sub_client.requests.get")
def test_checkins_game_not_started(mock_get):
    """Game not started — ESPN's summary omits the 'plays' key entirely."""
    mock_get.return_value = _resp({"header": {}})
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID)
    assert result == {"player_checked_in": False, "last_event_num": 0}


@patch("sub_client.requests.get")
def test_checkins_api_failure_503(mock_get):
    mock_get.side_effect = ConnectionError("timeout")
    with pytest.raises(HTTPException) as exc_info:
        sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID)
    assert exc_info.value.status_code == 503


# ── Caching tests ──────────────────────────────────────────────────


@patch("sub_client.requests.get")
def test_get_player_info_not_cached(mock_get):
    """get_player_info is not cached — each call hits the network."""
    mock_get.side_effect = _fake_espn_get()
    sub_client.get_player_info("jared mccain")
    sub_client.get_player_info("jared mccain")
    assert mock_get.call_count == 8  # 4 calls per lookup, twice, no caching


@patch("sub_client.requests.get")
def test_checkins_not_cached(mock_get):
    """get_checkins is not cached — each call hits the API."""
    mock_get.return_value = _summary_resp([_action_play(1, MCCAIN_ID)])
    sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    assert mock_get.call_count == 2


# ── Retry tests ────────────────────────────────────────────────────


@patch("sub_client.requests.get")
def test_get_player_info_retry_success(mock_get):
    """First attempt at the search step fails, second succeeds."""
    fake_get = _fake_espn_get_with_retry("apis/search/v2", fail_times=1)
    mock_get.side_effect = fake_get
    result = sub_client.get_player_info("jared mccain")
    assert result["full_name"] == "jared mccain"
    assert fake_get.call_counts["target"] == 2


@patch("sub_client.requests.get")
def test_get_player_info_retry_exhaustion(mock_get):
    """All 3 attempts at the search step fail — raises 503."""
    fake_get = _fake_espn_get_with_retry("apis/search/v2", fail_times=3)
    mock_get.side_effect = fake_get
    with pytest.raises(HTTPException) as exc_info:
        sub_client.get_player_info("jared mccain")
    assert exc_info.value.status_code == 503
    assert fake_get.call_counts["target"] == 3


@patch("sub_client.requests.get")
def test_get_player_info_no_retry_on_http_exception(mock_get):
    """HTTPException (e.g. 404) is not retried."""
    empty_search = {"results": [{"type": "player", "contents": []}]}
    mock_get.side_effect = _fake_espn_get(search=empty_search)
    with pytest.raises(HTTPException) as exc_info:
        sub_client.get_player_info("nobody")
    assert exc_info.value.status_code == 404
    assert mock_get.call_count == 1


@patch("sub_client.requests.get")
def test_get_checkins_retry_success(mock_get):
    """First attempt fails, second succeeds for checkins."""
    mock_get.side_effect = [
        ConnectionError("timeout"),
        _summary_resp([_action_play(1, MCCAIN_ID)]),
    ]
    result = sub_client.get_checkins(CHECKIN_GAME_ID, MCCAIN_ID, last_event_num=0)
    assert result["player_checked_in"] is True
    assert mock_get.call_count == 2


