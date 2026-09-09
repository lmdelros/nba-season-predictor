-- nba-season-predictor schema
-- IDs for teams/players/games reuse the integer IDs nba_api returns from NBA.com,
-- so ingestion can upsert directly without a separate ID-mapping step.

CREATE TABLE teams (
    team_id       INTEGER PRIMARY KEY,
    full_name     TEXT NOT NULL,
    abbreviation  TEXT NOT NULL,
    conference    TEXT NOT NULL,
    division      TEXT NOT NULL
);

CREATE TABLE players (
    player_id   INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    position    TEXT,
    height_in   INTEGER,
    weight_lb   INTEGER,
    birth_date  DATE
);

-- One row per player per season on a team's roster. Sourced from nba_api's
-- roster endpoint and re-upserted each ingestion run, so the latest `season`
-- row per player is the "current roster" and older rows double as roster
-- history (handles trades/signings without needing effective-dated ranges).
CREATE TABLE team_rosters (
    id             BIGSERIAL PRIMARY KEY,
    player_id      INTEGER NOT NULL REFERENCES players(player_id),
    team_id        INTEGER NOT NULL REFERENCES teams(team_id),
    season         TEXT NOT NULL,
    jersey_number  TEXT,
    position       TEXT,
    UNIQUE (player_id, season)
);

CREATE INDEX idx_team_rosters_team_season ON team_rosters(team_id, season);

CREATE TABLE games (
    game_id       INTEGER PRIMARY KEY,
    season        TEXT NOT NULL,          -- e.g. '2025-26'
    season_type   TEXT NOT NULL,          -- 'regular' | 'playoffs'
    game_date     DATE NOT NULL,
    home_team_id  INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id  INTEGER NOT NULL REFERENCES teams(team_id),
    home_score    INTEGER,                -- NULL until played
    away_score    INTEGER,                -- NULL until played
    status        TEXT NOT NULL DEFAULT 'scheduled'  -- 'scheduled' | 'final'
);

CREATE INDEX idx_games_season ON games(season);
CREATE INDEX idx_games_date ON games(game_date);
CREATE INDEX idx_games_home_team ON games(home_team_id);
CREATE INDEX idx_games_away_team ON games(away_team_id);

CREATE TABLE player_game_stats (
    id              BIGSERIAL PRIMARY KEY,
    game_id         INTEGER NOT NULL REFERENCES games(game_id),
    player_id       INTEGER NOT NULL REFERENCES players(player_id),
    team_id         INTEGER NOT NULL REFERENCES teams(team_id),  -- team played for in this game
    minutes         NUMERIC(5,2),
    points          INTEGER,
    rebounds        INTEGER,
    offensive_rebounds INTEGER,
    defensive_rebounds INTEGER,
    assists         INTEGER,
    steals          INTEGER,
    blocks          INTEGER,
    turnovers       INTEGER,
    fg_made         INTEGER,
    fg_attempted    INTEGER,
    fg3_made        INTEGER,
    fg3_attempted   INTEGER,
    ft_made         INTEGER,
    ft_attempted    INTEGER,
    plus_minus      INTEGER,
    UNIQUE (game_id, player_id)
);

CREATE INDEX idx_pgs_player ON player_game_stats(player_id);
CREATE INDEX idx_pgs_game ON player_game_stats(game_id);

-- Derived/engineered features, kept separate from raw `games` so re-running
-- feature engineering never mutates ingested source data.
CREATE TABLE team_game_features (
    id                      BIGSERIAL PRIMARY KEY,
    game_id                 INTEGER NOT NULL REFERENCES games(game_id),
    team_id                 INTEGER NOT NULL REFERENCES teams(team_id),
    rolling_win_pct_l10     NUMERIC(5,4),
    rest_days               INTEGER,
    is_back_to_back         BOOLEAN,
    rolling_off_rating      NUMERIC(6,2),   -- pace-adjusted
    rolling_def_rating      NUMERIC(6,2),   -- pace-adjusted
    h2h_win_pct_season      NUMERIC(5,4),
    season_win_pct_home     NUMERIC(5,4),
    season_win_pct_away     NUMERIC(5,4),
    cluster_diversity_score NUMERIC(6,4),
    UNIQUE (game_id, team_id)
);

CREATE INDEX idx_tgf_team ON team_game_features(team_id);

-- K-means output: player playstyle archetypes, fit per season.
CREATE TABLE player_clusters (
    id            BIGSERIAL PRIMARY KEY,
    player_id     INTEGER NOT NULL REFERENCES players(player_id),
    season        TEXT NOT NULL,
    cluster_id    INTEGER NOT NULL,
    cluster_label TEXT,        -- filled in manually after inspecting cluster membership
    pts_per36     NUMERIC(6,2),
    ast_rate      NUMERIC(6,4),
    reb_rate      NUMERIC(6,4),
    fg3a_rate     NUMERIC(6,4),
    usage_rate    NUMERIC(6,4),
    UNIQUE (player_id, season)
);

CREATE INDEX idx_player_clusters_season ON player_clusters(season);

-- Predictions keyed by model_version so multiple models' outputs can be
-- compared side by side for the same game.
CREATE TABLE game_predictions (
    id                      BIGSERIAL PRIMARY KEY,
    game_id                 INTEGER NOT NULL REFERENCES games(game_id),
    model_version           TEXT NOT NULL,   -- e.g. 'logreg_v1', 'linreg_margin_v1'
    model_type              TEXT NOT NULL,   -- 'win_probability' | 'margin'
    predicted_home_win_prob NUMERIC(5,4),    -- set when model_type = 'win_probability'
    predicted_margin        NUMERIC(6,2),    -- set when model_type = 'margin'
    predicted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (game_id, model_version)
);

CREATE INDEX idx_predictions_model_version ON game_predictions(model_version);

-- Monte Carlo output: aggregated results across all simulated runs of the
-- remaining season, per team, per simulation batch.
CREATE TABLE season_simulations (
    id                BIGSERIAL PRIMARY KEY,
    season            TEXT NOT NULL,
    team_id           INTEGER NOT NULL REFERENCES teams(team_id),
    batch_id          TEXT NOT NULL,        -- groups all team rows from one simulation run
    run_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    num_simulations   INTEGER NOT NULL,
    avg_wins          NUMERIC(5,2),
    playoff_pct       NUMERIC(5,4),
    championship_pct  NUMERIC(5,4),
    UNIQUE (season, team_id, batch_id)
);

CREATE INDEX idx_season_sims_batch ON season_simulations(batch_id);

-- Per-player full-season aggregates, sourced from leaguedashplayerstats (one
-- row per player per season, already combined across teams if traded) rather
-- than summed from player_game_stats — cheap to backfill many historical
-- seasons for award modeling without needing game-by-game data for each one.
CREATE TABLE player_season_stats (
    id            BIGSERIAL PRIMARY KEY,
    player_id     INTEGER NOT NULL REFERENCES players(player_id),
    season        TEXT NOT NULL,
    team_id       INTEGER REFERENCES teams(team_id),
    games_played  INTEGER,
    minutes       NUMERIC(7,2),
    points        NUMERIC(7,2),
    rebounds      NUMERIC(6,2),
    assists       NUMERIC(6,2),
    steals        NUMERIC(6,2),
    blocks        NUMERIC(6,2),
    turnovers     NUMERIC(6,2),
    fg_pct        NUMERIC(5,4),
    fg3_pct       NUMERIC(5,4),
    ft_pct        NUMERIC(5,4),
    plus_minus    NUMERIC(7,2),
    UNIQUE (player_id, season)
);

CREATE INDEX idx_player_season_stats_season ON player_season_stats(season);

-- Team win/loss record per season, sourced from leaguestandingsv3 — same
-- cheap-backfill rationale as player_season_stats: award models need a
-- team's win% as a feature, not its full game log.
CREATE TABLE team_season_standings (
    id       BIGSERIAL PRIMARY KEY,
    team_id  INTEGER NOT NULL REFERENCES teams(team_id),
    season   TEXT NOT NULL,
    wins     INTEGER NOT NULL,
    losses   INTEGER NOT NULL,
    win_pct  NUMERIC(5,4) NOT NULL,
    UNIQUE (team_id, season)
);

-- Ground truth award winners, sourced from playerawards (career awards list
-- per player — binary "won" fact only, no vote share/points; NBA.com doesn't
-- expose the underlying voting breakdown through this endpoint).
CREATE TABLE player_awards (
    id          BIGSERIAL PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(player_id),
    season      TEXT NOT NULL,
    award_type  TEXT NOT NULL,  -- 'mvp' | 'dpoy' | 'roy' | 'sixth_moy' | 'mip'
    UNIQUE (season, award_type)
);

-- Model-predicted win probability per candidate player, keyed by
-- model_version like game_predictions.
CREATE TABLE award_predictions (
    id              BIGSERIAL PRIMARY KEY,
    season          TEXT NOT NULL,
    award_type      TEXT NOT NULL,
    player_id       INTEGER NOT NULL REFERENCES players(player_id),
    model_version   TEXT NOT NULL,
    predicted_prob  NUMERIC(6,5),
    predicted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (season, award_type, player_id, model_version)
);
