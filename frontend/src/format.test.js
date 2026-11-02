import { describe, expect, it } from "vitest"
import { formatDate } from "./format"

describe("formatDate", () => {
  it("formats a plain date without shifting it to the previous day", () => {
    expect(formatDate("2026-02-01")).toBe("Feb 1, 2026")
    expect(formatDate("2022-01-01")).toBe("Jan 1, 2022")
  })
})
