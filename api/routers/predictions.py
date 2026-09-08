from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor

from api.db import get_db
from api.schemas import PredictionOut

router = APIRouter()

# game_predictions has one row per (game_id, model_version), and win-probability
# vs. margin predictions live in separate rows (model_type). latest_predictions
# picks the most recent row per game per model_type — unless model_version is
# given, in which case it's already a single row and DISTINCT ON is a no-op.
PREDICTIONS_SQL = """
    WITH latest_predictions AS (
        SELECT DISTINCT ON (gp.game_id, gp.model_type)
            gp.game_id, gp.model_type, gp.model_version,
            gp.predicted_home_win_prob, gp.predicted_margin, gp.predicted_at
        FROM game_predictions gp
        WHERE %(model_version)s::text IS NULL OR gp.model_version = %(model_version)s
        ORDER BY gp.game_id, gp.model_type, gp.predicted_at DESC
    )
    SELECT
        g.game_id,
        g.game_date,
        g.status,
        ht.abbreviation AS home_team,
        at.abbreviation AS away_team,
        wp.model_version AS win_prob_model_version,
        wp.predicted_home_win_prob::float AS predicted_home_win_prob,
        mg.model_version AS margin_model_version,
        mg.predicted_margin::float AS predicted_margin
    FROM games g
    JOIN teams ht ON ht.team_id = g.home_team_id
    JOIN teams at ON at.team_id = g.away_team_id
    LEFT JOIN latest_predictions wp
        ON wp.game_id = g.game_id AND wp.model_type = 'win_probability'
    LEFT JOIN latest_predictions mg
        ON mg.game_id = g.game_id AND mg.model_type = 'margin'
    WHERE g.season = %(season)s
        AND (%(game_id)s::int IS NULL OR g.game_id = %(game_id)s)
    ORDER BY g.game_date, g.game_id
"""


@router.get("/predictions", response_model=list[PredictionOut])
def get_predictions(
    season: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    game_id: int | None = Query(None),
    model_version: str | None = Query(None),
    conn=Depends(get_db),
):
    params = {"season": season, "game_id": game_id, "model_version": model_version}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(PREDICTIONS_SQL, params)
        return cur.fetchall()
