import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { getAwards, getFinals, getSeasons, getSimulations, getStandings } from "./api"

vi.mock("./api", () => ({
  getSeasons: vi.fn(),
  getStandings: vi.fn(),
  getSimulations: vi.fn(),
  getFinals: vi.fn(),
  getAwards: vi.fn(),
}))

const standings = [
  { team_id: 1, full_name: "Boston Celtics", conference: "East", wins: 60, losses: 22, win_pct: 0.732 },
]
const simulations = [
  {
    team_id: 1, full_name: "Boston Celtics", num_simulations: 10000,
    playoff_pct: 0.99, championship_pct: 0.25, avg_wins: 60.1,
  },
]

const finals = [
  {
    batch_id: "b1", team_a_id: 1, team_a_abbreviation: "BOS", team_a_name: "Boston Celtics",
    team_b_id: 2, team_b_abbreviation: "OKC", team_b_name: "Oklahoma City Thunder",
    meetings: 2500, num_simulations: 10000, matchup_pct: 0.25, team_a_win_pct: 0.6,
  },
]

const awards = [
  {
    award_type: "mvp", award_name: "Most Valuable Player", low_confidence: false,
    winner: {
      player_id: 1, full_name: "Test Winner", team_id: 1, team_abbreviation: "BOS",
      team_name: "Boston Celtics", games_played: 70, points_per_game: 30.0,
      rebounds_per_game: 8.0, assists_per_game: 6.0, steals_per_game: 1.0, blocks_per_game: 0.5,
    },
    picks: [],
  },
]

describe("App", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    getSeasons.mockResolvedValue(["2025-26", "2024-25"])
    getStandings.mockResolvedValue(standings)
    // Only the newest season has a simulation run, as in the real database.
    getSimulations.mockImplementation((season) =>
      Promise.resolve(season === "2025-26" ? simulations : []),
    )
    getFinals.mockImplementation((season) =>
      Promise.resolve(season === "2025-26" ? finals : []),
    )
    getAwards.mockImplementation((season) =>
      Promise.resolve(season === "2025-26" ? awards : []),
    )
  })

  it("loads the newest season's standings and playoff odds", async () => {
    render(<App />)

    expect(await screen.findByText("2025-26 season")).toBeInTheDocument()
    expect(await screen.findByText("Boston Celtics", { selector: ".team-cell" })).toBeInTheDocument()
    expect(screen.getByText("99%")).toBeInTheDocument()
    expect(screen.getByText("Most likely NBA Finals")).toBeInTheDocument()
    expect(getStandings).toHaveBeenCalledWith("2025-26")
    expect(screen.getByRole("heading", { name: "Awards" })).toBeInTheDocument()
    expect(screen.getByText("Test Winner")).toBeInTheDocument()
    expect(getAwards).toHaveBeenCalledWith("2025-26")
  })

  it("loads the chosen season and explains a missing simulation", async () => {
    render(<App />)
    await screen.findByText("99%")

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2024-25" } })

    expect(
      await screen.findByText("No simulation has been run for this season yet."),
    ).toBeInTheDocument()
    expect(getStandings).toHaveBeenLastCalledWith("2024-25")
    expect(screen.queryByText("99%")).not.toBeInTheDocument()
    expect(screen.queryByText("Most likely NBA Finals")).not.toBeInTheDocument()
    expect(screen.queryByText("Test Winner")).not.toBeInTheDocument()
  })

  it("shows an error when the API cannot be reached", async () => {
    getSeasons.mockRejectedValue(new Error("/seasons failed: 500"))
    render(<App />)

    expect(
      await screen.findByText("Couldn't load data: /seasons failed: 500"),
    ).toBeInTheDocument()
  })
})
