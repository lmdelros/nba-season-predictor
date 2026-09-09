import { useEffect, useState } from "react"
import { getSeasons, getSimulations, getStandings } from "./api"
import SeasonSelector from "./components/SeasonSelector"
import StandingsTable from "./components/StandingsTable"
import PlayoffOdds from "./components/PlayoffOdds"
import "./App.css"

export default function App() {
  const [seasons, setSeasons] = useState(null)
  const [season, setSeason] = useState(null)
  const [standings, setStandings] = useState(null)
  const [simulations, setSimulations] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getSeasons()
      .then((data) => {
        setSeasons(data)
        setSeason(data[0])
      })
      .catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!season) return
    setStandings(null)
    setSimulations(null)
    Promise.all([getStandings(season), getSimulations(season)])
      .then(([standingsData, simulationsData]) => {
        setStandings(standingsData)
        setSimulations(simulationsData)
      })
      .catch((err) => setError(err.message))
  }, [season])

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>NBA Season Predictor</h1>
          <p className="season-label">{season ? `${season} season` : "Loading…"}</p>
        </div>
        {seasons && (
          <SeasonSelector seasons={seasons} selected={season} onChange={setSeason} />
        )}
      </header>

      {error && <p className="error">Couldn't load data: {error}</p>}
      {!error && !standings && <p className="loading">Loading…</p>}

      {standings && <StandingsTable standings={standings} />}
      {simulations && <PlayoffOdds simulations={simulations} />}
    </div>
  )
}
