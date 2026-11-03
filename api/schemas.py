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
    cutoff_date: date | None
    avg_wins: float
    playoff_pct: float
    championship_pct: float | None


class AwardPlayerOut(BaseModel):
    player_id: int
    full_name: str
    team_id: int | None
    team_abbreviation: str | None
    team_name: str | None
    games_played: int | None
    points_per_game: float | None
    rebounds_per_game: float | None
    assists_per_game: float | None
    steals_per_game: float | None
    blocks_per_game: float | None


class AwardPickOut(AwardPlayerOut):
    rank: int
    won: bool | None


class AwardOut(BaseModel):
    award_type: str
    award_name: str
    low_confidence: bool
    winner: AwardPlayerOut | None
    picks: list[AwardPickOut]


class FinalsMatchupOut(BaseModel):
    batch_id: str
    team_a_id: int
    team_a_abbreviation: str
    team_a_name: str
    team_b_id: int
    team_b_abbreviation: str
    team_b_name: str
    meetings: int
    num_simulations: int
    cutoff_date: date | None
    matchup_pct: float
    team_a_win_pct: float
