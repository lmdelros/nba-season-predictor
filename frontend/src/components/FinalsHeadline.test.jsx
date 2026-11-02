import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import FinalsHeadline from "./FinalsHeadline"

const matchup = (teamAWinPct) => ({
  batch_id: "b1",
  team_a_id: 1,
  team_a_abbreviation: "DET",
  team_a_name: "Detroit Pistons",
  team_b_id: 2,
  team_b_abbreviation: "OKC",
  team_b_name: "Oklahoma City Thunder",
  meetings: 1840,
  num_simulations: 10000,
  matchup_pct: 0.184,
  team_a_win_pct: teamAWinPct,
})

describe("FinalsHeadline", () => {
  it("shows the most likely matchup and how often it happened", () => {
    render(<FinalsHeadline matchups={[matchup(0.3), { ...matchup(0.5), team_b_id: 3 }]} />)

    expect(screen.getByRole("heading")).toHaveTextContent(
      "Detroit Pistons vs Oklahoma City Thunder",
    )
    expect(screen.getByText(/Met in 18\.4% of 10,000 simulated seasons/)).toBeInTheDocument()
  })

  it("names the team that won more of those Finals", () => {
    const { rerender } = render(<FinalsHeadline matchups={[matchup(0.3)]} />)
    expect(screen.getByText(/Oklahoma City Thunder won 70\.0% of those Finals/)).toBeInTheDocument()

    rerender(<FinalsHeadline matchups={[matchup(0.65)]} />)
    expect(screen.getByText(/Detroit Pistons won 65\.0% of those Finals/)).toBeInTheDocument()
  })

  it("shows both teams' logos", () => {
    const { container } = render(<FinalsHeadline matchups={[matchup(0.3)]} />)

    const logos = [...container.querySelectorAll("img")].map((img) => img.getAttribute("src"))
    expect(logos).toEqual([
      "https://cdn.nba.com/logos/nba/1/global/D/logo.svg",
      "https://cdn.nba.com/logos/nba/2/global/D/logo.svg",
    ])
  })

  it("renders nothing when the run has no matchups", () => {
    const { container } = render(<FinalsHeadline matchups={[]} />)

    expect(container).toBeEmptyDOMElement()
  })
})
