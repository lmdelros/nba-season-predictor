import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import TeamLogo from "./TeamLogo"

describe("TeamLogo", () => {
  it("loads the team's logo from NBA.com by team ID", () => {
    const { container } = render(<TeamLogo teamId={1610612760} abbreviation="OKC" size={32} />)
    const img = container.querySelector("img")

    expect(img).toHaveAttribute("src", "https://cdn.nba.com/logos/nba/1610612760/global/D/logo.svg")
    expect(img).toHaveAttribute("width", "32")
    // Decorative: the team name is shown next to it.
    expect(img).toHaveAttribute("alt", "")
  })

  it("shows the abbreviation when the logo cannot be loaded", () => {
    const { container } = render(<TeamLogo teamId={9001} abbreviation="OKC" />)

    fireEvent.error(container.querySelector("img"))

    expect(container.querySelector("img")).toBeNull()
    expect(screen.getByText("OKC")).toBeInTheDocument()
  })
})
