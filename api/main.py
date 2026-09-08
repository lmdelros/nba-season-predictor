import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db import get_db
from api.routers import predictions, simulations, standings, teams

app = FastAPI(title="nba-season-predictor API")

origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(teams.router)
app.include_router(standings.router)
app.include_router(predictions.router)
app.include_router(simulations.router)


@app.get("/health")
def health(conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
    return {"status": "ok"}
