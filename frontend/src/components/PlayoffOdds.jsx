export default function PlayoffOdds({ simulations }) {
  // The API returns an empty list for seasons that no Monte Carlo run has covered.
  if (simulations.length === 0) {
    return (
      <section className="playoff-odds">
        <h2>Playoff Odds</h2>
        <p className="playoff-odds-subtitle">
          No simulation has been run for this season yet.
        </p>
      </section>
    )
  }

  return (
    <section className="playoff-odds">
      <h2>Playoff Odds</h2>
      <p className="playoff-odds-subtitle">
        Monte Carlo simulation, {simulations[0]?.num_simulations?.toLocaleString()} runs
        (playoff odds + full bracket simulation for championship odds)
      </p>
      <ul className="playoff-odds-list">
        {simulations.map((team) => (
          <li key={team.team_id} className="playoff-odds-row">
            <span className="team-name">{team.full_name}</span>
            <div className="odds-bar-track">
              <div
                className="odds-bar-fill"
                style={{ width: `${team.playoff_pct * 100}%` }}
              />
            </div>
            <span className="odds-pct">{(team.playoff_pct * 100).toFixed(0)}%</span>
            <span className="champ-pct">
              {team.championship_pct != null
                ? `🏆 ${(team.championship_pct * 100).toFixed(1)}%`
                : ""}
            </span>
            <span className="avg-wins">{team.avg_wins.toFixed(1)} avg wins</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
