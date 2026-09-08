from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor

from api.db import get_db
from api.schemas import StandingOut

router = APIRouter()

# Wins/losses aren't stored anywhere — they're derived from final games, counting
# each team once whether it played home or away, hence the union.
STANDINGS_SQL = """
    WITH results AS (
        SELECT home_team_id AS team_id,
               CASE WHEN home_score > away_score THEN 1 ELSE 0 END AS win
        FROM games WHERE season = %(season)s AND status = 'final'
        UNION ALL
        SELECT away_team_id AS team_id,
               CASE WHEN away_score > home_score THEN 1 ELSE 0 END AS win
        FROM games WHERE season = %(season)s AND status = 'final'
    )
    SELECT t.team_id, t.abbreviation, t.full_name, t.conference, t.division,
           COUNT(*) AS games_played,
           SUM(r.win) AS wins,
           COUNT(*) - SUM(r.win) AS losses,
           ROUND(SUM(r.win)::numeric / COUNT(*), 3)::float AS win_pct
    FROM results r
    JOIN teams t ON t.team_id = r.team_id
    GROUP BY t.team_id, t.abbreviation, t.full_name, t.conference, t.division
    ORDER BY win_pct DESC, wins DESC
"""


@router.get("/standings", response_model=list[StandingOut])
def get_standings(season: str = Query(..., pattern=r"^\d{4}-\d{2}$"), conn=Depends(get_db)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(STANDINGS_SQL, {"season": season})
        return cur.fetchall()
