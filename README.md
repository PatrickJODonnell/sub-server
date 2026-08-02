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
| GET | `/players/{player_name}` | Get player details, current season stats, and the player's current team's next game |
| GET | `/games/{game_id}/checkins/{player_id}` | Poll for player check-in events during a live game |

### Notable IDs

`/players` returns nba_api's numeric `personId`. `/players/{player_name}` (and everything derived from it — `next_game.game_id`, and the `player_id` you should pass to `/checkins`) uses ESPN's own numeric ids instead. These are two different id spaces:

| Entity | nba_api `personId` | ESPN id |
|--------|---------------------|---------|
| Jared McCain | `1642272` | `4683778` |
| OKC Thunder | `1610612760` | — |

### Check-In Polling

The `/games/{game_id}/checkins/{player_id}` endpoint is designed for polling during a live game. Both ids are ESPN's: `game_id` is an ESPN event id (the same one returned as `next_game.game_id` from `/players/{player_name}`), and `player_id` is an ESPN athlete id (the same one returned as `player_id` from `/players/{player_name}`).

- `game_id` must be a numeric string (e.g. `401898389`)
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
sub_client.py   — All business logic; wraps ESPN's public API, returns plain dicts
models.py       — Pydantic v2 response schemas, no logic
```

All ESPN calls use a **15-second** timeout, with up to **3 retries** and exponential backoff on transient failures. Every call is wrapped in try/except and returns a `503` on failure.

### Why ESPN instead of nba_api

`stats.nba.com` and `cdn.nba.com` are IP-blocked from the deployed cloud host. Both `/players/{player_name}` (search, core athlete document, season statistics, team next-event) and `/games/{game_id}/checkins/{player_id}` (play-by-play via ESPN's `summary` endpoint) are backed entirely by ESPN's public APIs instead. The only remaining `nba_api` usage is `/players`' active-player list, via `nba_api.stats.static.players` — a local static lookup with no network call.

## Testing

Tests use `pytest` and mock all external API calls — no network access required.

```bash
uv run pytest tests/ -v
```

Test files:

- `tests/test_main.py` — Route-level tests via FastAPI `TestClient`
- `tests/test_sub_client.py` — Business logic unit tests

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

`sub_client.py`'s `_get_current_season()` derives the current season string (`"YYYY-YY"`) from today's date — update its month cutoffs if the league schedule shifts.
