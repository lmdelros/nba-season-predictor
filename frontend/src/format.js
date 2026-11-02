// "2026-02-01" -> "Feb 1, 2026". JavaScript reads a plain date as midnight UTC, so it is
// formatted in UTC too; formatting in a US time zone would show the previous day.
export function formatDate(isoDate) {
  return new Date(isoDate).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  })
}
