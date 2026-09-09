const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"

async function getJSON(path) {
  const res = await fetch(`${BASE_URL}${path}`)
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status}`)
  }
  return res.json()
}

export function getTeams() {
  return getJSON("/teams")
}

export function getSeasons() {
  return getJSON("/seasons")
}

export function getStandings(season) {
  return getJSON(`/standings?season=${encodeURIComponent(season)}`)
}

export function getSimulations(season) {
  return getJSON(`/simulations?season=${encodeURIComponent(season)}`)
}

export function getPredictions(season, gameId) {
  const params = new URLSearchParams({ season })
  if (gameId) params.set("game_id", gameId)
  return getJSON(`/predictions?${params}`)
}
