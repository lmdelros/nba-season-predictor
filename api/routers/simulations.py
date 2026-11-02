from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor

from api.db import get_db
from api.schemas import FinalsMatchupOut, SimulationOut

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


# Finals matchups for the same run /simulations returns by default (the newest batch for
# the season), most likely first. Batches saved before matchups were recorded have none,
# so the newest run decides: if it has no matchups, the result is an empty list.
FINALS_SQL = """
    WITH target_batch AS (
        SELECT batch_id, num_simulations FROM season_simulations
        WHERE season = %(season)s
          AND (%(batch_id)s::text IS NULL OR batch_id = %(batch_id)s)
        ORDER BY run_at DESC
        LIMIT 1
    )
    SELECT sf.batch_id,
           sf.team_a_id, ta.abbreviation AS team_a_abbreviation, ta.full_name AS team_a_name,
           sf.team_b_id, tb.abbreviation AS team_b_abbreviation, tb.full_name AS team_b_name,
           sf.meetings, tgt.num_simulations,
           sf.matchup_pct::float AS matchup_pct,
           sf.team_a_wins::float / sf.meetings AS team_a_win_pct
    FROM simulation_finals sf
    JOIN target_batch tgt ON tgt.batch_id = sf.batch_id
    JOIN teams ta ON ta.team_id = sf.team_a_id
    JOIN teams tb ON tb.team_id = sf.team_b_id
    ORDER BY sf.meetings DESC, sf.team_a_id
    LIMIT %(limit)s
"""


@router.get("/simulations/finals", response_model=list[FinalsMatchupOut])
def get_finals_matchups(
    season: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    batch_id: str | None = Query(None),
    limit: int = Query(5, ge=1, le=50),
    conn=Depends(get_db),
):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(FINALS_SQL, {"season": season, "batch_id": batch_id, "limit": limit})
        return cur.fetchall()
