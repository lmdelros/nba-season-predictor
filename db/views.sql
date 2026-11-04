-- Derived views over the raw tables. Safe to re-run: every statement is CREATE OR REPLACE.
-- Fresh databases load this automatically after schema.sql (see docker-compose.yml);
-- for an existing database, apply it with:
--   docker exec -i nba-predictor-db psql -U nba -d nba_predictor < db/views.sql

-- Each team's average point margin and number of played games per season.
CREATE OR REPLACE VIEW team_season_margin AS
SELECT season, team_id, AVG(margin)::float AS avg_margin, COUNT(margin) AS games_played
FROM (
    SELECT season, home_team_id AS team_id, home_score - away_score AS margin FROM games
    UNION ALL
    SELECT season, away_team_id, away_score - home_score FROM games
) team_games
GROUP BY season, team_id;

-- Each team's average point margin over its earlier games of the season, as of each game,
-- how many played games that average is based on, and the team's margin in the previous
-- season (the model shrinks margins based on few games toward a share of it). Computed
-- here rather than in features/build_features.py so it always reflects the current games
-- table, with no stored column to backfill.
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
    tg.game_id,
    tg.team_id,
    -- NULL for a team's first game of the season.
    AVG(tg.margin) OVER earlier_games::float AS season_avg_margin,
    -- count() skips NULL margins, so scheduled (unplayed) games are not counted.
    COUNT(tg.margin) OVER earlier_games AS games_played_before,
    -- NULL when the previous season is not in the games table. Added last because
    -- CREATE OR REPLACE VIEW can only add columns at the end.
    prev.avg_margin AS prior_season_margin
FROM team_games tg
-- The previous season's name: '2023-24' becomes '2022-23'.
LEFT JOIN team_season_margin prev
    ON prev.team_id = tg.team_id
    AND prev.season = (left(tg.season, 4)::int - 1)::text || '-' || substr(tg.season, 3, 2)
-- The frame ends one row before the current game, so a game's own result never counts
-- toward its features (the SQL equivalent of pandas' shift(1)).
WINDOW earlier_games AS (
    PARTITION BY tg.season, tg.team_id
    ORDER BY game_date, game_id
    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
);
