from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from api.db import get_db
from api.schemas import TeamOut

router = APIRouter()


@router.get("/teams", response_model=list[TeamOut])
def list_teams(conn=Depends(get_db)):
    sql = """
        SELECT team_id, full_name, abbreviation, conference, division
        FROM teams
        ORDER BY conference, division, full_name
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        return cur.fetchall()
