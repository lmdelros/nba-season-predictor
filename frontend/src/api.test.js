import { afterEach, describe, expect, it, vi } from "vitest"
import { getPredictions, getStandings } from "./api"

function stubFetch(response) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

const ok = (body) => ({ ok: true, status: 200, json: () => Promise.resolve(body) })

describe("api", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("requests standings for the given season and returns the JSON body", async () => {
    const fetchMock = stubFetch(ok([{ team_id: 1 }]))

    await expect(getStandings("2025-26")).resolves.toEqual([{ team_id: 1 }])
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/standings?season=2025-26")
  })

  it("adds game_id to the predictions query only when one is given", async () => {
    const fetchMock = stubFetch(ok([]))

    await getPredictions("2025-26")
    await getPredictions("2025-26", 22500001)

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/predictions?season=2025-26",
      "http://localhost:8000/predictions?season=2025-26&game_id=22500001",
    ])
  })

  it("throws with the path and status when the API returns an error", async () => {
    stubFetch({ ok: false, status: 422, json: () => Promise.resolve({}) })

    await expect(getStandings("bad")).rejects.toThrow("/standings?season=bad failed: 422")
  })
})
