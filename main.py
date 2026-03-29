import re

from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware

import nba_client
from models import CheckInResponse, NextGame, PlayerDetail, PlayerSummary, SeasonStats

app = FastAPI(title="NBA Check-In Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GAME_ID_PATTERN = re.compile(r"^\d{10}$")


@app.get("/players", response_model=list[PlayerSummary])
def list_players():
    all_players = nba_client.get_active_players()
    return [
        PlayerSummary(
            player_id=p["id"],
            full_name=p["full_name"],
            first_name=p["first_name"],
            last_name=p["last_name"],
            is_active=p["is_active"],
        )
        for p in all_players
    ]


@app.get("/players/{player_id}", response_model=PlayerDetail)
def get_player(player_id: int):
    data = nba_client.get_player_info(player_id)
    season_stats = None
    if data.get("season_stats"):
        season_stats = SeasonStats(**data["season_stats"])
    return PlayerDetail(**{**data, "season_stats": season_stats})


@app.get("/teams/{team_id}/next-game", response_model=NextGame)
def get_next_game(team_id: int):
    data = nba_client.get_next_game(team_id)
    return NextGame(**data)


@app.get("/games/{game_id}/checkins/{player_id}", response_model=CheckInResponse)
def get_checkins(
    game_id: str = Path(..., description="10-digit NBA game ID"),
    player_id: int = Path(..., description="NBA player ID"),
    last_event_num: int = 0,
):
    if not GAME_ID_PATTERN.match(game_id):
        raise HTTPException(status_code=422, detail="game_id must be a 10-digit string")
    data = nba_client.get_checkins(game_id, player_id, last_event_num)
    return CheckInResponse(**data)
