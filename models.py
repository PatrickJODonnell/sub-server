from pydantic import BaseModel
from typing import Optional


class PlayerSummary(BaseModel):
    player_id: int
    full_name: str
    first_name: str
    last_name: str
    is_active: bool


class SeasonStats(BaseModel):
    pts: Optional[float]
    ast: Optional[float]
    reb: Optional[float]


class PlayerDetail(BaseModel):
    player_id: int
    full_name: str
    birthdate: Optional[str]
    height: Optional[str]
    weight: Optional[str]
    position: Optional[str]
    jersey: Optional[str]
    team_id: Optional[int]
    team_name: Optional[str]
    team_city: Optional[str]
    team_abbreviation: Optional[str]
    season_experience: Optional[int]
    roster_status: Optional[str]
    draft_year: Optional[str]
    draft_round: Optional[str]
    draft_number: Optional[str]
    season_stats: Optional[SeasonStats]


class NextGame(BaseModel):
    game_id: Optional[str] = None
    has_game_today: bool
    start_time_utc: Optional[str] = None


class CheckInResponse(BaseModel):
    player_checked_in: bool
    last_event_num: int
