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

- **`main.py`** — FastAPI app, route definitions, CORS middleware, request validation (e.g. game_id regex `^\d+$`)
- **`nba_client.py`** — Pure functions wrapping ESPN's public API. All business logic lives here: JSON parsing, date/time math, check-in event logic. Returns dicts (models are built in main.py).
- **`models.py`** — Pydantic v2 response schemas, no logic.

## API Endpoints

| Method | Path | Returns |
|--------|------|---------|
| GET | `/players` | `list[PlayerSummary]` |
| GET | `/players/{player_name}` | `PlayerDetail` (includes a nested `next_game: NextGame`) |
| GET | `/games/{game_id}/checkins/{player_id}` | `CheckInResponse` |

There is no standalone next-game endpoint — `get_player_info()` resolves the player's current ESPN team and pulls its next scheduled/live game (via `site.api.espn.com`'s `team.nextEvent`) as part of the same lookup, nested under `next_game` in `PlayerDetail`. `next_game.game_id` is ESPN's own event id, and it's directly usable as the `game_id` path segment for `/games/{game_id}/checkins/{player_id}` — `get_checkins` is ESPN-backed too, so both endpoints share the same id space.

## Key Constants (hardcoded in `nba_client.py`)

- `_get_current_season()` derives the current season string (`"YYYY-YY"`) from today's date — update its month cutoffs if the league schedule shifts
- All ESPN calls use `timeout=15`, with retry (3 attempts, exponential backoff)
- Jared McCain: nba_api `personId` `1642272` (used by `/players`, backed by `nba_api.stats.static.players`), ESPN athlete id `4683778` (used by `/players/{player_name}` and `/games/{game_id}/checkins/{player_id}`) — these are two different id spaces, see below

## Caching & Retry

- Nothing is cached — `get_player_info` and `get_checkins` both hit the network on every call (real-time data)
- All ESPN calls retry up to 3 times with exponential backoff on transient errors (`_retry_call`)

## nba_api / ESPN Usage Notes

- `nba_api.stats.static.players` is the only remaining nba_api usage (`get_active_players`) — it's a local static lookup, no network call, no stats.nba.com/cdn.nba.com dependency
- `get_player_info` and `get_checkins` are both fully ESPN-based (plain `requests` calls against `site.web.api.espn.com` / `sports.core.api.espn.com` / `site.api.espn.com`), since stats.nba.com/cdn.nba.com are IP-blocked from the deployed cloud host
- All ESPN calls must be wrapped in try/except — these are undocumented public endpoints
- **Two id spaces**: `/players` (nba_api static list) returns nba_api's numeric `personId`. `/players/{player_name}`, `next_game.game_id`, and `/games/{game_id}/checkins/{player_id}` all use ESPN's own numeric ids (athlete id / event id) — a client should source `player_id` from `/players/{player_name}`'s response when it intends to call `/checkins`, not from the `/players` list
- Season strings must be in `"YYYY-YY"` format (e.g. `"2025-26"`)
