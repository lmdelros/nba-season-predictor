import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import AwardsSection from "./AwardsSection"

const player = (id, name, teamId, abbreviation, extra = {}) => ({
  player_id: id, full_name: name, team_id: teamId, team_abbreviation: abbreviation,
  team_name: `${abbreviation} Team`, games_played: 68, points_per_game: 31.1,
  rebounds_per_game: 4.3, assists_per_game: 6.6, steals_per_game: 1.4, blocks_per_game: 0.8,
  ...extra,
})

const OKC = 1610612760
const sga = player(1628983, "Shai Gilgeous-Alexander", OKC, "OKC")

const mvp = {
  award_type: "mvp", award_name: "Most Valuable Player", low_confidence: false, winner: sga,
  picks: [
    { ...player(203999, "Nikola Jokić", 1610612743, "DEN"), rank: 1, won: false },
    { ...sga, rank: 2, won: true },
    { ...player(1629029, "Luka Dončić", 1610612747, "LAL"), rank: 3, won: false },
  ],
}

const card = (name) => screen.getByRole("article", { name })

describe("AwardsSection", () => {
  it("shows the winner with team and per-game stats", () => {
    render(<AwardsSection awards={[mvp]} images={{}} />)
    const mvpCard = card("Most Valuable Player")

    expect(within(mvpCard).getByRole("heading")).toHaveTextContent("Shai Gilgeous-Alexander")
    expect(within(mvpCard).getByText("OKC Team · 68 games")).toBeInTheDocument()
    expect(within(mvpCard).getByText("31.1")).toBeInTheDocument()
    expect(within(mvpCard).getByText("PTS")).toBeInTheDocument()
    expect(within(mvpCard).getByText("6.6")).toBeInTheDocument()
  })

  it("colors the card with the winner's team color", () => {
    render(<AwardsSection awards={[mvp]} images={{}} />)

    expect(card("Most Valuable Player").style.getPropertyValue("--team-color")).toBe("#007AC1")
  })

  it("lists the model's picks in order and marks the one that won", () => {
    render(<AwardsSection awards={[mvp]} images={{}} />)
    const picks = within(card("Most Valuable Player")).getAllByRole("listitem")

    expect(picks.map((li) => li.textContent)).toEqual([
      "#1Nikola Jokić", "#2Shai Gilgeous-Alexander✓", "#3Luka Dončić",
    ])
    expect(within(picks[1]).getByLabelText("won the award")).toBeInTheDocument()
  })

  it("shows defensive stats for Defensive Player of the Year", () => {
    const dpoy = { ...mvp, award_type: "dpoy", award_name: "Defensive Player of the Year" }
    render(<AwardsSection awards={[dpoy]} images={{}} />)
    const dpoyCard = card("Defensive Player of the Year")

    expect(within(dpoyCard).getByText("BLK")).toBeInTheDocument()
    expect(within(dpoyCard).queryByText("PTS")).not.toBeInTheDocument()
  })

  it("flags low-confidence awards", () => {
    const mip = { ...mvp, award_type: "mip", award_name: "Most Improved Player", low_confidence: true }
    render(<AwardsSection awards={[mvp, mip]} images={{}} />)

    expect(within(card("Most Improved Player")).getByText("Low confidence")).toBeInTheDocument()
    expect(within(card("Most Valuable Player")).queryByText("Low confidence")).toBeNull()
  })

  it("shows the team logo when no player picture was added", () => {
    const { container } = render(<AwardsSection awards={[mvp]} images={{}} />)

    expect(container.querySelector(".award-art img")).toHaveAttribute(
      "src", `https://cdn.nba.com/logos/nba/${OKC}/global/D/logo.svg`,
    )
  })

  it("shows an added player picture, falling back to the logo if it fails", () => {
    const { container } = render(
      <AwardsSection awards={[mvp]} images={{ 1628983: "/assets/sga.png" }} />,
    )
    const picture = screen.getByRole("img", { name: "Shai Gilgeous-Alexander" })
    expect(picture).toHaveAttribute("src", "/assets/sga.png")

    fireEvent.error(picture)

    expect(container.querySelector(".award-art img")).toHaveAttribute(
      "src", `https://cdn.nba.com/logos/nba/${OKC}/global/D/logo.svg`,
    )
  })

  it("shows picks without a check mark before the award is given", () => {
    const upcoming = {
      ...mvp, winner: null, picks: mvp.picks.map((p) => ({ ...p, won: null })),
    }
    render(<AwardsSection awards={[upcoming]} images={{}} />)
    const mvpCard = card("Most Valuable Player")

    expect(within(mvpCard).getByRole("heading")).toHaveTextContent("Not yet awarded")
    expect(within(mvpCard).getAllByRole("listitem")).toHaveLength(3)
    expect(within(mvpCard).queryByLabelText("won the award")).toBeNull()
  })

  it("renders nothing for a season without awards", () => {
    const { container } = render(<AwardsSection awards={[]} />)

    expect(container).toBeEmptyDOMElement()
  })
})
