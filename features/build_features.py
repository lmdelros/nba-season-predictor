# Builds derived features (rolling win %, rest days, ratings, etc.) into team_game_features.
import argparse
import os

import pandas as pd
import psycopg2


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def load_team_games(conn, season):
    sql = """
        SELECT game_id, season, game_date, home_team_id AS team_id, away_team_id AS opp_id,
               TRUE AS is_home, home_score AS points_for, away_score AS points_against
        FROM games WHERE season = %(season)s
        UNION ALL
        SELECT game_id, season, game_date, away_team_id AS team_id, home_team_id AS opp_id,
               FALSE AS is_home, away_score AS points_for, home_score AS points_against
        FROM games WHERE season = %(season)s
    """
    df = pd.read_sql(sql, conn, params={"season": season})
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df


def load_team_box_totals(conn, season):
    # Possession estimate needs offensive rebounds specifically (not total rebounds),
    # so this sums the per-player oreb/fga/fta/tov columns rather than reading `games`.
    sql = """
        SELECT pgs.game_id, pgs.team_id,
               sum(pgs.fg_attempted) AS fga,
               sum(pgs.ft_attempted) AS fta,
               sum(pgs.offensive_rebounds) AS oreb,
               sum(pgs.turnovers) AS tov
        FROM player_game_stats pgs
        JOIN games g ON g.game_id = pgs.game_id
        WHERE g.season = %(season)s
        GROUP BY pgs.game_id, pgs.team_id
    """
    return pd.read_sql(sql, conn, params={"season": season})


def estimate_possessions(fga, fta, oreb, tov):
    return fga + 0.44 * fta - oreb + tov


def load_player_clusters(conn, season):
    sql = "SELECT player_id, cluster_id FROM player_clusters WHERE season = %(season)s"
    return pd.read_sql(sql, conn, params={"season": season})


def load_game_player_minutes(conn, season):
    sql = """
        SELECT pgs.game_id, pgs.team_id, pgs.player_id, pgs.minutes
        FROM player_game_stats pgs
        JOIN games g ON g.game_id = pgs.game_id
        WHERE g.season = %(season)s
    """
    return pd.read_sql(sql, conn, params={"season": season})


def compute_cluster_diversity(game_minutes, clusters):
    # Players below the clustering minutes threshold have no cluster_id; their
    # minutes are dropped and the rest renormalized, since their archetype is unknown.
    df = game_minutes.merge(clusters, on="player_id", how="inner")

    by_cluster = df.groupby(["game_id", "team_id", "cluster_id"])["minutes"].sum().reset_index()
    totals = by_cluster.groupby(["game_id", "team_id"])["minutes"].transform("sum")
    by_cluster["share"] = by_cluster["minutes"] / totals

    diversity = (
        by_cluster.groupby(["game_id", "team_id"])["share"]
        .apply(lambda shares: 1 - (shares ** 2).sum())
        .reset_index(name="cluster_diversity_score")
    )
    return diversity


def add_season_splits(df):
    """Team's home/away win % so far this season, as of (not including) this game."""
    home_pct = pd.Series(index=df.index, dtype=float)
    away_pct = pd.Series(index=df.index, dtype=float)

    for _, idx in df.groupby("team_id").groups.items():
        home_wins = home_games = away_wins = away_games = 0
        for i in sorted(idx):
            row = df.loc[i]
            home_pct[i] = home_wins / home_games if home_games else None
            away_pct[i] = away_wins / away_games if away_games else None
            if row["is_home"]:
                home_games += 1
                home_wins += row["win"]
            else:
                away_games += 1
                away_wins += row["win"]

    df["season_win_pct_home"] = home_pct
    df["season_win_pct_away"] = away_pct
    return df


def compute_team_game_features(team_games, box):
    """Per-team, per-game features from raw results and box totals, each computed only
    from that team's earlier games. Pure (no database), so leakage can be unit-tested."""
    df = team_games.merge(box, on=["game_id", "team_id"], how="left")
    opp_box = box.rename(columns={
        "team_id": "opp_id", "fga": "opp_fga", "fta": "opp_fta",
        "oreb": "opp_oreb", "tov": "opp_tov",
    })
    df = df.merge(opp_box, on=["game_id", "opp_id"], how="left")

    df["poss"] = estimate_possessions(df["fga"], df["fta"], df["oreb"], df["tov"])
    df["opp_poss"] = estimate_possessions(
        df["opp_fga"], df["opp_fta"], df["opp_oreb"], df["opp_tov"]
    )
    df["off_rtg_game"] = 100 * df["points_for"] / df["poss"]
    df["def_rtg_game"] = 100 * df["points_against"] / df["opp_poss"]
    df["win"] = (df["points_for"] > df["points_against"]).astype(int)

    # Chronological order per team is required before any shift/rolling below,
    # since those rely on row order within each team_id group to mean "in time order".
    df = df.sort_values(["team_id", "game_date", "game_id"]).reset_index(drop=True)

    grouped = df.groupby("team_id")
    # shift(1) excludes the current game so features never leak same-game outcomes.
    df["rolling_win_pct_l10"] = grouped["win"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).mean()
    )
    df["rolling_off_rating"] = grouped["off_rtg_game"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).mean()
    )
    df["rolling_def_rating"] = grouped["def_rtg_game"].transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).mean()
    )

    prev_date = grouped["game_date"].shift(1)
    df["rest_days"] = (df["game_date"] - prev_date).dt.days.astype("Int64")
    df["is_back_to_back"] = df["rest_days"] == 1

    h2h_group = df.groupby(["season", "team_id", "opp_id"])
    df["h2h_win_pct_season"] = h2h_group["win"].transform(lambda s: s.shift(1).expanding().mean())

    return add_season_splits(df)


def build_features(conn, season):
    df = compute_team_game_features(
        load_team_games(conn, season), load_team_box_totals(conn, season)
    )

    clusters = load_player_clusters(conn, season)
    game_minutes = load_game_player_minutes(conn, season)
    diversity = compute_cluster_diversity(game_minutes, clusters)
    df = df.merge(diversity, on=["game_id", "team_id"], how="left")

    return df


def _clean(value):
    if value is None:
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def upsert_team_game_features(conn, df):
    cols = [
        "game_id", "team_id", "rolling_win_pct_l10", "rest_days", "is_back_to_back",
        "rolling_off_rating", "rolling_def_rating", "h2h_win_pct_season",
        "season_win_pct_home", "season_win_pct_away", "cluster_diversity_score",
    ]
    records = [
        {k: _clean(v) for k, v in row._asdict().items()}
        for row in df[cols].itertuples(index=False)
    ]

    sql = """
        INSERT INTO team_game_features (game_id, team_id, rolling_win_pct_l10, rest_days,
                                         is_back_to_back, rolling_off_rating, rolling_def_rating,
                                         h2h_win_pct_season, season_win_pct_home,
                                         season_win_pct_away, cluster_diversity_score)
        VALUES (%(game_id)s, %(team_id)s, %(rolling_win_pct_l10)s, %(rest_days)s,
                %(is_back_to_back)s, %(rolling_off_rating)s, %(rolling_def_rating)s,
                %(h2h_win_pct_season)s, %(season_win_pct_home)s, %(season_win_pct_away)s,
                %(cluster_diversity_score)s)
        ON CONFLICT (game_id, team_id) DO UPDATE SET
            rolling_win_pct_l10 = EXCLUDED.rolling_win_pct_l10,
            rest_days = EXCLUDED.rest_days,
            is_back_to_back = EXCLUDED.is_back_to_back,
            rolling_off_rating = EXCLUDED.rolling_off_rating,
            rolling_def_rating = EXCLUDED.rolling_def_rating,
            h2h_win_pct_season = EXCLUDED.h2h_win_pct_season,
            season_win_pct_home = EXCLUDED.season_win_pct_home,
            season_win_pct_away = EXCLUDED.season_win_pct_away,
            cluster_diversity_score = EXCLUDED.cluster_diversity_score
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True, help="e.g. 2024-25")
    args = parser.parse_args()

    conn = get_db_connection()
    df = build_features(conn, args.season)
    upsert_team_game_features(conn, df)
    conn.close()


if __name__ == "__main__":
    main()
