from datetime import date, datetime

from pydantic import BaseModel


class TeamOut(BaseModel):
    team_id: int
    full_name: str
    abbreviation: str
    conference: str
    division: str


class StandingOut(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str
    conference: str
    division: str
    games_played: int
    wins: int
    losses: int
    win_pct: float


class PredictionOut(BaseModel):
    game_id: int
    game_date: date
    status: str
    home_team: str
    away_team: str
    win_prob_model_version: str | None
    predicted_home_win_prob: float | None
    margin_model_version: str | None
    predicted_margin: float | None


class SimulationOut(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str
    batch_id: str
    run_at: datetime
    num_simulations: int
    avg_wins: float
    playoff_pct: float
    championship_pct: float | None
