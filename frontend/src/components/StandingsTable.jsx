function ConferenceTable({ conference, teams }) {
  return (
    <table className="standings-table">
      <caption>{conference}</caption>
      <thead>
        <tr>
          <th>Team</th>
          <th>W</th>
          <th>L</th>
          <th>PCT</th>
        </tr>
      </thead>
      <tbody>
        {teams.map((team) => (
          <tr key={team.team_id}>
            <td>{team.full_name}</td>
            <td>{team.wins}</td>
            <td>{team.losses}</td>
            <td>{team.win_pct.toFixed(3)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function StandingsTable({ standings }) {
  const east = standings.filter((t) => t.conference === "East")
  const west = standings.filter((t) => t.conference === "West")

  return (
    <section className="standings">
      <h2>Standings</h2>
      <div className="standings-columns">
        <ConferenceTable conference="East" teams={east} />
        <ConferenceTable conference="West" teams={west} />
      </div>
    </section>
  )
}
