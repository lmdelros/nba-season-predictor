# Streamlit dashboard reading predictions and simulation results from Postgres.
import os

import matplotlib.pyplot as plt
import pandas as pd
import psycopg2
import streamlit as st
from matplotlib.patches import Patch

# Categorical slots 1 (blue) and 2 (orange) from the project's palette —
# colorblind-safe adjacent pair, used here for East/West identity.
EAST_COLOR = "#2a78d6"
WEST_COLOR = "#eb6834"


@st.cache_resource
def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5433"),
        dbname=os.environ.get("DB_NAME", "nba_predictor"),
        user=os.environ.get("DB_USER", "nba"),
        password=os.environ.get("DB_PASSWORD", "nba"),
    )


@st.cache_data
def load_seasons(_conn):
    df = pd.read_sql("SELECT DISTINCT season FROM games ORDER BY season DESC", _conn)
    return df["season"].tolist()


@st.cache_data
def load_batches(_conn, season):
    sql = """
        SELECT batch_id, min(run_at) AS run_at, min(num_simulations) AS num_simulations
        FROM season_simulations
        WHERE season = %(season)s
        GROUP BY batch_id
        ORDER BY run_at DESC
    """
    return pd.read_sql(sql, _conn, params={"season": season})


@st.cache_data
def load_simulation_results(_conn, season, batch_id):
    sql = """
        SELECT t.abbreviation, t.conference, ss.avg_wins, ss.playoff_pct
        FROM season_simulations ss
        JOIN teams t ON t.team_id = ss.team_id
        WHERE ss.season = %(season)s AND ss.batch_id = %(batch_id)s
        ORDER BY ss.playoff_pct DESC, ss.avg_wins DESC
    """
    return pd.read_sql(sql, _conn, params={"season": season, "batch_id": batch_id})


@st.cache_data
def load_actual_standings(_conn, season):
    sql = """
        SELECT t.abbreviation, t.conference,
               count(*) FILTER (
                   WHERE (g.home_team_id = t.team_id AND g.home_score > g.away_score)
                      OR (g.away_team_id = t.team_id AND g.away_score > g.home_score)
               ) AS wins,
               count(*) FILTER (WHERE g.status = 'final') AS games_played
        FROM teams t
        JOIN games g ON t.team_id IN (g.home_team_id, g.away_team_id) AND g.season = %(season)s
        GROUP BY t.abbreviation, t.conference
        ORDER BY wins DESC
    """
    return pd.read_sql(sql, _conn, params={"season": season})


@st.cache_data
def load_clusters(_conn, season):
    sql = """
        SELECT DISTINCT cluster_id, cluster_label
        FROM player_clusters
        WHERE season = %(season)s
        ORDER BY cluster_id
    """
    return pd.read_sql(sql, _conn, params={"season": season})


@st.cache_data
def load_cluster_players(_conn, season, cluster_id):
    sql = """
        SELECT p.full_name, pc.pts_per36, pc.usage_rate, pc.ast_rate, pc.reb_rate,
               pc.fg3a_rate, COALESCE(mins.minutes, 0) AS minutes
        FROM player_clusters pc
        JOIN players p ON p.player_id = pc.player_id
        LEFT JOIN (
            SELECT player_id, sum(minutes) AS minutes
            FROM player_game_stats pgs
            JOIN games g ON g.game_id = pgs.game_id
            WHERE g.season = %(season)s
            GROUP BY player_id
        ) mins ON mins.player_id = pc.player_id
        WHERE pc.season = %(season)s AND pc.cluster_id = %(cluster_id)s
        ORDER BY minutes DESC
    """
    return pd.read_sql(sql, _conn, params={"season": season, "cluster_id": int(cluster_id)})


def conference_bar_chart(sim_df):
    df = sim_df.sort_values("playoff_pct", ascending=True)
    colors = df["conference"].map({"East": EAST_COLOR, "West": WEST_COLOR})

    fig, ax = plt.subplots(figsize=(8, 10))
    ax.barh(df["abbreviation"], df["playoff_pct"] * 100, color=colors)
    ax.set_xlabel("Playoff odds (%)")
    ax.set_xlim(0, 100)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(
        handles=[Patch(facecolor=EAST_COLOR, label="East"), Patch(facecolor=WEST_COLOR, label="West")],
        loc="lower right",
    )
    fig.tight_layout()
    return fig


def render_simulation_section(conn, season):
    st.header("Playoff Odds & Projected Wins")

    batches = load_batches(conn, season)
    if batches.empty:
        st.info("Run simulation/monte_carlo.py for this season to see projections here.")
        return

    batch_labels = [
        f"{row.run_at:%Y-%m-%d %H:%M} ({row.num_simulations} sims)" for row in batches.itertuples()
    ]
    selected = st.selectbox("Simulation run", batch_labels)
    batch_id = batches.iloc[batch_labels.index(selected)]["batch_id"]

    sim_df = load_simulation_results(conn, season, batch_id)

    display_df = sim_df.copy()
    display_df["avg_wins"] = display_df["avg_wins"].round(1)
    display_df["playoff_pct"] = (display_df["playoff_pct"] * 100).round(1)
    display_df = display_df.rename(columns={
        "abbreviation": "Team", "conference": "Conf",
        "avg_wins": "Proj. Wins", "playoff_pct": "Playoff %",
    })[["Team", "Conf", "Proj. Wins", "Playoff %"]]

    col1, col2 = st.columns([2, 1])
    with col1:
        st.pyplot(conference_bar_chart(sim_df))
    with col2:
        st.dataframe(display_df, hide_index=True, width='stretch')


def render_standings_section(conn, season):
    st.header("Actual Standings")
    actual_df = load_actual_standings(conn, season)
    st.dataframe(
        actual_df.rename(columns={
            "abbreviation": "Team", "conference": "Conf",
            "wins": "Wins", "games_played": "Games Played",
        }),
        hide_index=True, width='stretch',
    )


def render_clusters_section(conn, season):
    st.header("Player Playstyle Archetypes")

    clusters_df = load_clusters(conn, season)
    if clusters_df.empty:
        st.info("Run models/train_player_clusters.py for this season to see archetypes here.")
        return

    labels = [row.cluster_label or f"Cluster {row.cluster_id}" for row in clusters_df.itertuples()]
    selected_label = st.selectbox("Archetype", labels)
    cluster_id = clusters_df.iloc[labels.index(selected_label)]["cluster_id"]

    players_df = load_cluster_players(conn, season, cluster_id)
    st.dataframe(
        players_df.rename(columns={
            "full_name": "Player", "pts_per36": "Pts/36", "usage_rate": "Usage %",
            "ast_rate": "Ast %", "reb_rate": "Reb %", "fg3a_rate": "3PA Rate", "minutes": "Minutes",
        }).round({"Pts/36": 1, "Usage %": 1, "Ast %": 1, "Reb %": 1, "3PA Rate": 2}),
        hide_index=True, width='stretch',
    )


def main():
    st.set_page_config(page_title="NBA Season Predictor", layout="wide")
    st.title("NBA Season Predictor")

    conn = get_db_connection()
    seasons = load_seasons(conn)
    if not seasons:
        st.error("No games found in the database. Run ingestion/pull_nba_data.py first.")
        return

    with st.sidebar:
        season = st.selectbox("Season", seasons)

    render_simulation_section(conn, season)
    render_standings_section(conn, season)
    render_clusters_section(conn, season)


if __name__ == "__main__":
    main()
