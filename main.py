import re

from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware

import sub_client
from models import CheckInResponse, NextGame, PlayerDetail, PlayerSummary, SeasonStats

app = FastAPI(title="NBA Check-In Tracker")

# TODO -> Tighten this up later on
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GAME_ID_PATTERN = re.compile(r"^\d+$")


@app.get("/players", response_model=list[PlayerSummary])
def list_players():
    all_players = sub_client.get_active_players()
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


@app.get("/players/{player_name}", response_model=PlayerDetail)
def get_player(player_name: str):
    data = sub_client.get_player_info(player_name)
    season_stats = SeasonStats(**data["season_stats"])
    next_game = NextGame(**data["next_game"])
    return PlayerDetail(**{**data, "season_stats": season_stats, "next_game": next_game})


@app.get("/games/{game_id}/checkins/{player_id}", response_model=CheckInResponse)
def get_checkins(
    game_id: str = Path(..., description="ESPN NBA event ID"),
    player_id: int = Path(..., description="ESPN athlete ID (matches PlayerDetail.player_id)"),
    last_event_num: int = 0,
):
    if not GAME_ID_PATTERN.match(game_id):
        raise HTTPException(status_code=422, detail="game_id must be a numeric string")
    data = sub_client.get_checkins(game_id, player_id, last_event_num)
    return CheckInResponse(**data)
