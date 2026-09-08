from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor

from api.db import get_db
from api.schemas import SimulationOut

router = APIRouter()

# season_simulations groups rows by batch_id (one Monte Carlo run). Default to
# the most recent run for the season unless a specific batch_id is requested.
SIMULATIONS_SQL = """
    WITH target_batch AS (
        SELECT batch_id FROM season_simulations
        WHERE season = %(season)s
          AND (%(batch_id)s::text IS NULL OR batch_id = %(batch_id)s)
        ORDER BY run_at DESC
        LIMIT 1
    )
    SELECT ss.team_id, t.abbreviation, t.full_name, ss.batch_id, ss.run_at, ss.num_simulations,
           ss.avg_wins::float AS avg_wins,
           ss.playoff_pct::float AS playoff_pct,
           ss.championship_pct::float AS championship_pct
    FROM season_simulations ss
    JOIN teams t ON t.team_id = ss.team_id
    WHERE ss.season = %(season)s
      AND ss.batch_id = (SELECT batch_id FROM target_batch)
    ORDER BY ss.playoff_pct DESC
"""


@router.get("/simulations", response_model=list[SimulationOut])
def get_simulations(
    season: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    batch_id: str | None = Query(None),
    conn=Depends(get_db),
):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SIMULATIONS_SQL, {"season": season, "batch_id": batch_id})
        return cur.fetchall()
