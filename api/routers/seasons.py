from fastapi import APIRouter, Depends

from api.db import get_db

router = APIRouter()


@router.get("/seasons", response_model=list[str])
def list_seasons(conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT season FROM games ORDER BY season DESC")
        return [row[0] for row in cur.fetchall()]
