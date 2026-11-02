import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import StandingsTable from "./StandingsTable"

const standings = [
  {
    team_id: 1,
    full_name: "Boston Celtics",
    conference: "East",
    wins: 64,
    losses: 18,
    win_pct: 0.78,
  },
  {
    team_id: 2,
    full_name: "Oklahoma City Thunder",
    conference: "West",
    wins: 68,
    losses: 14,
    win_pct: 0.829,
  },
]

describe("StandingsTable", () => {
  it("splits teams into their conference table", () => {
    render(<StandingsTable standings={standings} />)

    const eastTable = screen.getByText("East").closest("table")
    const westTable = screen.getByText("West").closest("table")

    expect(eastTable).toHaveTextContent("Boston Celtics")
    expect(eastTable).not.toHaveTextContent("Oklahoma City Thunder")
    expect(westTable).toHaveTextContent("Oklahoma City Thunder")
  })

  it("shows each team's logo next to its name", () => {
    const { container } = render(<StandingsTable standings={standings} />)

    const logos = [...container.querySelectorAll("img")].map((img) => img.getAttribute("src"))
    expect(logos).toEqual([
      "https://cdn.nba.com/logos/nba/1/global/D/logo.svg",
      "https://cdn.nba.com/logos/nba/2/global/D/logo.svg",
    ])
  })

  it("formats win percentage to three decimal places", () => {
    render(<StandingsTable standings={standings} />)

    expect(screen.getByText("0.829")).toBeInTheDocument()
  })
})
