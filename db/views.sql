-- Derived views over the raw tables. Safe to re-run: every statement is CREATE OR REPLACE.
-- Fresh databases load this automatically after schema.sql (see docker-compose.yml);
-- for an existing database, apply it with:
--   docker exec -i nba-predictor-db psql -U nba -d nba_predictor < db/views.sql

-- Each team's average point margin over its earlier games of the season, as of each game.
-- Computed here rather than in features/build_features.py so it always reflects the
-- current games table, with no stored column to backfill.
CREATE OR REPLACE VIEW team_game_form AS
WITH team_games AS (
    -- One row per team per game, seen from that team's side.
    SELECT game_id, season, game_date, home_team_id AS team_id,
           home_score - away_score AS margin
    FROM games
    UNION ALL
    SELECT game_id, season, game_date, away_team_id AS team_id,
           away_score - home_score AS margin
    FROM games
)
SELECT
    game_id,
    team_id,
    -- The frame ends one row before the current game, so a game's own result never
    -- counts toward its feature (the SQL equivalent of pandas' shift(1)). NULL for a
    -- team's first game of the season.
    AVG(margin) OVER (
        PARTITION BY season, team_id
        ORDER BY game_date, game_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )::float AS season_avg_margin
FROM team_games;
