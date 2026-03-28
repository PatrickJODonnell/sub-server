# Sub-Server

A FastAPI backend that powers the NBA Check-In Tracker. It exposes endpoints for player lookup, team schedules, and live game substitution detection — telling you when a specific player checks into a game.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)

## Setup

```bash
uv sync
```

## Running Locally

```bash
uv run uvicorn main:app --reload --port 8000
```

Interactive API docs are available at `http://localhost:8000/docs` once the server is running.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/players` | List all active NBA players |
| GET | `/players/{player_id}` | Get player details and current season stats |
| GET | `/teams/{team_id}/next-game` | Check if a team plays today and get start time |
| GET | `/games/{game_id}/checkins/{player_id}` | Poll for player check-in events during a live game |

### Notable IDs

| Entity | ID |
|--------|----|
| Jared McCain | `1642272` |
| OKC Thunder | `1610612760` |

### Check-In Polling

The `/games/{game_id}/checkins/{player_id}` endpoint is designed for polling during a live game.

- `game_id` must be a 10-digit string (e.g. `0022500001`)
- Pass `last_event_num=0` on the first request — the server returns whether the player is currently on court
- On subsequent requests, pass back the `last_event_num` from the previous response — the server returns whether a new sub-in occurred since then

**Example response:**
```json
{
  "player_checked_in": true,
  "last_event_num": 142
}
```

## Architecture

Three-layer structure with clear separation of concerns:

```
main.py         — FastAPI app, route definitions, request validation
nba_client.py   — All business logic; wraps nba_api calls, returns plain dicts
models.py       — Pydantic v2 response schemas, no logic
```

All `nba_api` calls use a 10-second timeout. stats.nba.com is unreliable, so every call is wrapped in try/except and returns a `503` on failure.

## Testing

Tests use `pytest` and mock all external `nba_api` calls — no network access required.

```bash
uv run pytest tests/ -v
```

Test files:

- `tests/test_main.py` — Route-level tests via FastAPI `TestClient` (11 tests)
- `tests/test_nba_client.py` — Business logic unit tests (19 tests)

## Deployment

Deployments to [FastAPI Cloud](https://fastapi.tiangolo.com/fastapi-cloud/) are triggered automatically on every push to `main` via GitHub Actions.

To deploy manually:

```bash
uv run fastapi deploy
```

The workflow requires two GitHub Actions secrets:

| Secret | Description |
|--------|-------------|
| `FASTAPI_CLOUD_TOKEN` | FastAPI Cloud authentication token |
| `FASTAPI_CLOUD_APP_ID` | Target application ID |

## Key Constants

Defined in `nba_client.py` — update these each season:

```python
CURRENT_SEASON = "2025-26"
```
