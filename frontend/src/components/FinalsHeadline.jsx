import TeamLogo from "./TeamLogo"

const percent = (value) => `${(value * 100).toFixed(1)}%`

// The most likely Finals pairing across the simulation run, and which side won more of
// those Finals. Renders nothing for seasons whose newest run has no matchups.
export default function FinalsHeadline({ matchups }) {
  if (!matchups || matchups.length === 0) return null

  const top = matchups[0]
  const teamAFavored = top.team_a_win_pct >= 0.5
  const favorite = teamAFavored ? top.team_a_name : top.team_b_name
  const favoriteWinPct = teamAFavored ? top.team_a_win_pct : 1 - top.team_a_win_pct

  return (
    <section className="finals-headline" aria-label="Most likely NBA Finals">
      <p className="finals-label">Most likely NBA Finals</p>
      <h2 className="finals-teams">
        <span className="finals-team">
          <TeamLogo teamId={top.team_a_id} abbreviation={top.team_a_abbreviation} size={40} />
          {top.team_a_name}
        </span>{" "}
        <span className="finals-vs">vs</span>{" "}
        <span className="finals-team">
          <TeamLogo teamId={top.team_b_id} abbreviation={top.team_b_abbreviation} size={40} />
          {top.team_b_name}
        </span>
      </h2>
      <p className="finals-detail">
        Met in {percent(top.matchup_pct)} of {top.num_simulations.toLocaleString()} simulated
        seasons. {favorite} won {percent(favoriteWinPct)} of those Finals.
      </p>
    </section>
  )
}
