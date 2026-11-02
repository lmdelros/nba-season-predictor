import { useState } from "react"

// A team's logo, loaded from NBA.com by the team's NBA.com ID (the "D" variant, made for
// dark backgrounds like this page's). If the image cannot be
// loaded, the team's abbreviation is shown instead. The team's name always appears next
// to the logo, so both are hidden from screen readers to avoid reading the team twice.
export default function TeamLogo({ teamId, abbreviation, size = 24 }) {
  const [failed, setFailed] = useState(false)

  if (failed) {
    return (
      <span
        className="team-logo-fallback"
        style={{ width: size, height: size, fontSize: size / 3 }}
        aria-hidden="true"
      >
        {abbreviation}
      </span>
    )
  }

  return (
    <img
      className="team-logo"
      src={`https://cdn.nba.com/logos/nba/${teamId}/global/D/logo.svg`}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}
