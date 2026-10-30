import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import App from "./App"
import { getSeasons, getSimulations, getStandings } from "./api"

vi.mock("./api", () => ({
  getSeasons: vi.fn(),
  getStandings: vi.fn(),
  getSimulations: vi.fn(),
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

describe("App", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    getSeasons.mockResolvedValue(["2025-26", "2024-25"])
    getStandings.mockResolvedValue(standings)
    // Only the newest season has a simulation run, as in the real database.
    getSimulations.mockImplementation((season) =>
      Promise.resolve(season === "2025-26" ? simulations : []),
    )
  })

  it("loads the newest season's standings and playoff odds", async () => {
    render(<App />)

    expect(await screen.findByText("2025-26 season")).toBeInTheDocument()
    expect(await screen.findByText("Boston Celtics", { selector: "td" })).toBeInTheDocument()
    expect(screen.getByText("99%")).toBeInTheDocument()
    expect(getStandings).toHaveBeenCalledWith("2025-26")
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
  })

  it("shows an error when the API cannot be reached", async () => {
    getSeasons.mockRejectedValue(new Error("/seasons failed: 500"))
    render(<App />)

    expect(
      await screen.findByText("Couldn't load data: /seasons failed: 500"),
    ).toBeInTheDocument()
  })
})
