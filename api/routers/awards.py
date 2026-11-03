from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor

from api.db import get_db
from api.schemas import AwardOut

router = APIRouter()

# Display order and names. MIP is flagged because its model's top pick won only 1 of 10
# evaluated seasons (see docs/award_models.md).
AWARD_NAMES = {
    "mvp": "Most Valuable Player",
    "dpoy": "Defensive Player of the Year",
    "roy": "Rookie of the Year",
    "mip": "Most Improved Player",
}
LOW_CONFIDENCE = {"mip"}
# Matches MODEL_VERSION in models/predict_awards.py, which is not in the API image: each
# season's picks come from a model trained only on earlier seasons.
MODEL_VERSION_SUFFIX = "_forward_v1"
PICKS_SHOWN = 3

# Player, team and per-game stats for the season (player_season_stats holds season
# totals); LEFT JOINs so a player is never dropped for missing stats.
PLAYER_COLUMNS = """
    p.player_id, p.full_name, s.team_id,
    t.abbreviation AS team_abbreviation, t.full_name AS team_name, s.games_played,
    round(s.points / NULLIF(s.games_played, 0), 1)::float AS points_per_game,
    round(s.rebounds / NULLIF(s.games_played, 0), 1)::float AS rebounds_per_game,
    round(s.assists / NULLIF(s.games_played, 0), 1)::float AS assists_per_game,
    round(s.steals / NULLIF(s.games_played, 0), 1)::float AS steals_per_game,
    round(s.blocks / NULLIF(s.games_played, 0), 1)::float AS blocks_per_game
"""
PLAYER_JOINS = """
    JOIN players p ON p.player_id = x.player_id
    LEFT JOIN player_season_stats s ON s.player_id = x.player_id AND s.season = %(season)s
    LEFT JOIN teams t ON t.team_id = s.team_id
"""

PICKS_SQL = f"""
    WITH x AS (
        SELECT award_type, player_id,
               ROW_NUMBER() OVER (PARTITION BY award_type
                                  ORDER BY predicted_prob DESC, player_id) AS rank
        FROM award_predictions
        WHERE season = %(season)s AND model_version = award_type || %(suffix)s
    )
    SELECT x.award_type, x.rank, {PLAYER_COLUMNS}
    FROM x {PLAYER_JOINS}
    WHERE x.rank <= %(shown)s
    ORDER BY x.award_type, x.rank
"""

WINNERS_SQL = f"""
    SELECT x.award_type, {PLAYER_COLUMNS}
    FROM player_awards x {PLAYER_JOINS}
    WHERE x.season = %(season)s
"""


@router.get("/awards", response_model=list[AwardOut])
def get_awards(
    season: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    conn=Depends(get_db),
):
    """Each award with a winner or model picks this season: the winner, and the model's
    top picks in order with whether each won (null until the award is given)."""
    params = {"season": season, "suffix": MODEL_VERSION_SUFFIX, "shown": PICKS_SHOWN}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(PICKS_SQL, params)
        picks = cur.fetchall()
        cur.execute(WINNERS_SQL, params)
        winners = {row.pop("award_type"): row for row in cur.fetchall()}

    awards = []
    for award_type, award_name in AWARD_NAMES.items():
        winner = winners.get(award_type)
        award_picks = [
            {**pick, "won": None if winner is None else pick["player_id"] == winner["player_id"]}
            for pick in picks if pick["award_type"] == award_type
        ]
        if winner is None and not award_picks:
            continue
        awards.append({
            "award_type": award_type, "award_name": award_name,
            "low_confidence": award_type in LOW_CONFIDENCE,
            "winner": winner, "picks": award_picks,
        })
    return awards
