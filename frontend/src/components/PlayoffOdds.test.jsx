import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import PlayoffOdds from "./PlayoffOdds"

const simulations = [
  {
    team_id: 1,
    full_name: "Boston Celtics",
    num_simulations: 10000,
    playoff_pct: 0.95,
    championship_pct: 0.3,
    avg_wins: 58.24,
  },
  {
    team_id: 2,
    full_name: "Utah Jazz",
    num_simulations: 10000,
    playoff_pct: 0.02,
    championship_pct: null,
    avg_wins: 21.5,
  },
]

describe("PlayoffOdds", () => {
  it("explains when a season has no simulation run", () => {
    render(<PlayoffOdds simulations={[]} />)

    expect(
      screen.getByText("No simulation has been run for this season yet."),
    ).toBeInTheDocument()
    expect(screen.queryByText(/runs/)).not.toBeInTheDocument()
  })

  it("formats playoff odds, championship odds, and average wins", () => {
    render(<PlayoffOdds simulations={simulations} />)

    expect(screen.getByText("95%")).toBeInTheDocument()
    expect(screen.getByText("🏆 30.0%")).toBeInTheDocument()
    expect(screen.getByText("58.2 avg wins")).toBeInTheDocument()
    expect(screen.getByText("2%")).toBeInTheDocument()
  })

  it("hides the trophy when championship odds are missing", () => {
    render(<PlayoffOdds simulations={simulations} />)

    expect(screen.getAllByText(/🏆/)).toHaveLength(1)
  })

  it("shows the number of simulation runs with a thousands separator", () => {
    render(<PlayoffOdds simulations={simulations} />)

    expect(screen.getByText(/10,000 runs/)).toBeInTheDocument()
  })
})
