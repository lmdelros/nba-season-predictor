import { formatDate } from "../format"
import TeamLogo from "./TeamLogo"

// Below this many games per team, the page warns that the odds are uncertain. Playoff
// odds were measured as overconfident about 7 games into a season and reliable by
// February 1, about 50 games in (docs/margin_prior.md); 20 is a round number between.
const EARLY_SEASON_GAMES = 20

// gamesPlayed: average games played per team so far, if known.
export default function PlayoffOdds({ simulations, gamesPlayed }) {
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
        {simulations[0].cutoff_date && (
          <>Projected as of {formatDate(simulations[0].cutoff_date)}. </>
        )}
        Monte Carlo simulation, {simulations[0]?.num_simulations?.toLocaleString()} runs
        (playoff odds + full bracket simulation for championship odds)
      </p>
      {gamesPlayed != null && gamesPlayed < EARLY_SEASON_GAMES && (
        <p className="early-season-note">
          Early season: teams have played about {Math.round(gamesPlayed)} games each, so
          these projections are uncertain, and playoff odds near 0% or 100% are
          overconfident.
        </p>
      )}
      <ul className="playoff-odds-list">
        {simulations.map((team) => (
          <li key={team.team_id} className="playoff-odds-row">
            <span className="team-name">
              <TeamLogo teamId={team.team_id} abbreviation={team.abbreviation} size={20} />
              <span className="team-name-text">{team.full_name}</span>
            </span>
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
