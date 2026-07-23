# K-means clustering: groups players into playstyle archetypes from per-season stat profiles.
import argparse
import os

import pandas as pd
import psycopg2
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

# Players below this season minutes total are excluded from clustering — with
# too few minutes, rate stats (usage%, ast%, etc.) are noise, not signal.
MIN_SEASON_MINUTES = 500

RATE_FEATURE_COLUMNS = ["pts_per36", "ast_rate", "reb_rate", "fg3a_rate", "usage_rate"]


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


def load_player_season_totals(conn, season):
    # Grouped by player_id only (not team) so a mid-season trade's stats combine
    # into one row — team context for rate stats is handled separately below.
    sql = """
        SELECT pgs.player_id, p.full_name,
               sum(pgs.minutes) AS minutes,
               sum(pgs.points) AS points,
               sum(pgs.assists) AS ast,
               sum(pgs.rebounds) AS reb,
               sum(pgs.fg_made) AS fgm,
               sum(pgs.fg_attempted) AS fga,
               sum(pgs.fg3_attempted) AS fg3a,
               sum(pgs.ft_attempted) AS fta,
               sum(pgs.turnovers) AS tov
        FROM player_game_stats pgs
        JOIN games g ON g.game_id = pgs.game_id
        JOIN players p ON p.player_id = pgs.player_id
        WHERE g.season = %(season)s
        GROUP BY pgs.player_id, p.full_name
    """
    return pd.read_sql(sql, conn, params={"season": season})


def load_team_season_totals(conn, season):
    # Summing every player's individual minutes for a team equals the team's
    # total minutes (5 players on court at all times), so no separate formula
    # is needed for Team_MP.
    sql = """
        SELECT pgs.team_id,
               sum(pgs.minutes) AS team_minutes,
               sum(pgs.fg_made) AS team_fgm,
               sum(pgs.fg_attempted) AS team_fga,
               sum(pgs.ft_attempted) AS team_fta,
               sum(pgs.turnovers) AS team_tov,
               sum(pgs.rebounds) AS team_reb
        FROM player_game_stats pgs
        JOIN games g ON g.game_id = pgs.game_id
        WHERE g.season = %(season)s
        GROUP BY pgs.team_id
    """
    return pd.read_sql(sql, conn, params={"season": season})


def load_team_allowed_rebounds(conn, season):
    # TRB% needs total available rebounds in a game (both sides), so this sums
    # up each team's OPPONENTS' rebounds across the whole season — same
    # home/away self-join idea as features/build_features.py, aggregated by team.
    sql = """
        WITH team_opponents AS (
            SELECT game_id, home_team_id AS team_id, away_team_id AS opp_id
            FROM games WHERE season = %(season)s
            UNION ALL
            SELECT game_id, away_team_id AS team_id, home_team_id AS opp_id
            FROM games WHERE season = %(season)s
        ),
        team_game_rebounds AS (
            SELECT game_id, team_id, sum(rebounds) AS reb
            FROM player_game_stats
            GROUP BY game_id, team_id
        )
        SELECT teamop.team_id, sum(tgr.reb) AS opp_reb
        FROM team_opponents teamop
        JOIN team_game_rebounds tgr
          ON tgr.game_id = teamop.game_id AND tgr.team_id = teamop.opp_id
        GROUP BY teamop.team_id
    """
    return pd.read_sql(sql, conn, params={"season": season})


def load_player_primary_team(conn, season):
    # A traded player's counting stats are combined across teams in
    # load_player_season_totals; for rate stats we need ONE team's context,
    # so use whichever team they played the most minutes for.
    sql = """
        SELECT player_id, team_id, sum(minutes) AS team_minutes
        FROM player_game_stats pgs
        JOIN games g ON g.game_id = pgs.game_id
        WHERE g.season = %(season)s
        GROUP BY player_id, team_id
    """
    df = pd.read_sql(sql, conn, params={"season": season})
    idx = df.groupby("player_id")["team_minutes"].idxmax()
    return df.loc[idx, ["player_id", "team_id"]].reset_index(drop=True)


def compute_rate_features(players_df, primary_team_df, team_totals_df, allowed_reb_df):
    df = players_df.merge(primary_team_df, on="player_id", how="inner")
    df = df.merge(team_totals_df, on="team_id", how="left")
    df = df.merge(allowed_reb_df, on="team_id", how="left")

    # Also filters out ~0-minute players who would blow up every ratio below.
    df = df[df["minutes"] >= MIN_SEASON_MINUTES].copy()

    team_possessions = df["team_minutes"] / 5

    df["pts_per36"] = 36 * df["points"] / df["minutes"]
    df["fg3a_rate"] = (df["fg3a"] / df["fga"]).where(df["fga"] > 0, 0.0)
    df["usage_rate"] = (
        100 * (df["fga"] + 0.44 * df["fta"] + df["tov"]) * team_possessions
        / (df["minutes"] * (df["team_fga"] + 0.44 * df["team_fta"] + df["team_tov"]))
    )
    df["ast_rate"] = (
        100 * df["ast"]
        / (((df["minutes"] / team_possessions) * df["team_fgm"]) - df["fgm"])
    )
    df["reb_rate"] = (
        100 * (df["reb"] * team_possessions)
        / (df["minutes"] * (df["team_reb"] + df["opp_reb"]))
    )

    return df


def print_k_diagnostics(X_scaled, k_range=range(3, 11)):
    """Elbow (inertia) and silhouette score per k — inspect by eye to pick k."""
    print(f"{'k':>3} {'inertia':>12} {'silhouette':>12}")
    for k in k_range:
        model = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = model.fit_predict(X_scaled)
        sil = silhouette_score(X_scaled, labels)
        print(f"{k:>3} {model.inertia_:>12.1f} {sil:>12.3f}")


def fit_clusters(X_scaled, k):
    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    return model.fit_predict(X_scaled)


def upsert_player_clusters(conn, df, season):
    sql = """
        INSERT INTO player_clusters (player_id, season, cluster_id, pts_per36,
                                      ast_rate, reb_rate, fg3a_rate, usage_rate)
        VALUES (%(player_id)s, %(season)s, %(cluster_id)s, %(pts_per36)s,
                %(ast_rate)s, %(reb_rate)s, %(fg3a_rate)s, %(usage_rate)s)
        ON CONFLICT (player_id, season) DO UPDATE SET
            cluster_id = EXCLUDED.cluster_id,
            pts_per36 = EXCLUDED.pts_per36,
            ast_rate = EXCLUDED.ast_rate,
            reb_rate = EXCLUDED.reb_rate,
            fg3a_rate = EXCLUDED.fg3a_rate,
            usage_rate = EXCLUDED.usage_rate
    """
    records = df.assign(season=season)[[
        "player_id", "season", "cluster_id", "pts_per36",
        "ast_rate", "reb_rate", "fg3a_rate", "usage_rate",
    ]].to_dict("records")
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True, help="e.g. 2024-25")
    parser.add_argument(
        "--k", type=int,
        help="number of clusters; omit to print elbow/silhouette diagnostics instead of fitting",
    )
    args = parser.parse_args()

    conn = get_db_connection()
    players = load_player_season_totals(conn, args.season)
    teams = load_team_season_totals(conn, args.season)
    allowed = load_team_allowed_rebounds(conn, args.season)
    primary = load_player_primary_team(conn, args.season)

    df = compute_rate_features(players, primary, teams, allowed)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(df[RATE_FEATURE_COLUMNS])

    if args.k is None:
        print_k_diagnostics(X_scaled)
        conn.close()
        return

    df["cluster_id"] = fit_clusters(X_scaled, args.k)
    upsert_player_clusters(conn, df, args.season)

    print(f"Clustered {len(df)} players into {args.k} groups.\n")
    print(df.groupby("cluster_id")[RATE_FEATURE_COLUMNS].mean().round(2))

    conn.close()


if __name__ == "__main__":
    main()

