# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Server

```bash
uv run uvicorn main:app --reload --port 8000
```

Add dependencies with `uv add <package>`. The `pyproject.toml` and `uv.lock` files are the source of truth for dependencies.

Interactive API docs: `http://localhost:8000/docs`

## Architecture

3-layer structure with clear separation of concerns:

- **`main.py`** — FastAPI app, route definitions, CORS middleware, request validation (e.g. game_id regex `^\d{10}$`)
- **`nba_client.py`** — Pure functions wrapping `nba_api` calls. All business logic lives here: DataFrame parsing, date/time math, check-in event logic. Returns dicts (models are built in main.py).
- **`models.py`** — Pydantic v2 response schemas, no logic.

## API Endpoints

| Method | Path | Returns |
|--------|------|---------|
| GET | `/players` | `list[PlayerSummary]` |
| GET | `/players/{player_id}` | `PlayerDetail` |
| GET | `/teams/{team_id}/next-game` | `NextGame` |
| GET | `/games/{game_id}/checkins/{player_id}` | `CheckInResponse` |

## Key Constants (hardcoded in `nba_client.py`)

- `CURRENT_SEASON = "2025-26"` — update each season
- All `nba_api` calls use `timeout=30`
- Jared McCain player ID: `1642272`, OKC Thunder team ID: `1610612760`

## nba_api Usage Notes

- Use the `static` module for player/team lookups (no network call), `stats` module for live game data
- All `nba_api` calls must be wrapped in try/except — stats.nba.com is unreliable
- DataFrames returned from nba_api require `.get_data_frames()[0]` and row access via `.iloc[0]`
- Season strings must be in `"YYYY-YY"` format (e.g. `"2025-26"`)
