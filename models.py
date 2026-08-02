from pydantic import BaseModel


class PlayerSummary(BaseModel):
    player_id: int
    full_name: str
    first_name: str
    last_name: str
    is_active: bool


class SeasonStats(BaseModel):
    pts: float | None
    ast: float | None
    reb: float | None


class NextGame(BaseModel):
    game_id: str
    has_game_today: bool
    start_time_utc: str


class PlayerDetail(BaseModel):
    player_id: int
    full_name: str
    birthdate: str | None
    height: str | None
    weight: str | None
    position: str | None
    jersey: str | None
    team_name: str | None
    season_experience: int | None
    roster_status: str | None
    draft_year: str | None
    draft_round: str | None
    draft_number: str | None
    season_stats: SeasonStats
    next_game: NextGame


class CheckInResponse(BaseModel):
    player_checked_in: bool
    last_event_num: int
