import { useState } from "react"
import { teamColor } from "../teamColors"
import TeamLogo from "./TeamLogo"

// Pictures added to src/assets/players/<player_id>.png, found at build time, so a player
// without one costs no request.
const PLAYER_IMAGES = Object.fromEntries(
  Object.entries(
    import.meta.glob("../assets/players/*.png", { eager: true, query: "?url", import: "default" }),
  ).map(([path, url]) => [Number(path.match(/(\d+)\.png$/)[1]), url]),
)

// Per-game stats shown on each card: defensive stats for Defensive Player of the Year.
const CARD_STATS = {
  dpoy: [["rebounds_per_game", "REB"], ["blocks_per_game", "BLK"], ["steals_per_game", "STL"]],
}
const DEFAULT_STATS = [["points_per_game", "PTS"], ["rebounds_per_game", "REB"], ["assists_per_game", "AST"]]

const formatStat = (value) => (value == null ? "–" : value.toFixed(1))

// The player's picture if one was added, otherwise a large team logo. Falls back to the
// logo if the picture fails to load.
function PlayerArt({ player, images }) {
  const [failed, setFailed] = useState(false)
  const image = images[player.player_id]

  if (image && !failed) {
    return (
      <img className="award-art" src={image} alt={player.full_name} onError={() => setFailed(true)} />
    )
  }
  return (
    <span className="award-art">
      <TeamLogo teamId={player.team_id} abbreviation={player.team_abbreviation} size={120} />
    </span>
  )
}

// The model's top picks in order, marking the one that won once the award is given.
function Picks({ picks }) {
  if (picks.length === 0) return null
  return (
    <div className="award-picks">
      <p className="award-picks-label">Model&apos;s picks</p>
      <ol>
        {picks.map((pick) => (
          <li key={pick.player_id} className={pick.won ? "award-pick won" : "award-pick"}>
            <span className="award-pick-rank">#{pick.rank}</span>
            <TeamLogo teamId={pick.team_id} abbreviation={pick.team_abbreviation} size={20} />
            <span className="award-pick-name">{pick.full_name}</span>
            {pick.won && <span className="award-pick-won" aria-label="won the award">✓</span>}
          </li>
        ))}
      </ol>
    </div>
  )
}

function AwardCard({ award, images }) {
  const { winner } = award
  const stats = CARD_STATS[award.award_type] ?? DEFAULT_STATS

  return (
    <article
      className="award-card"
      style={{ "--team-color": winner ? teamColor(winner.team_id) : undefined }}
      aria-label={award.award_name}
    >
      <div className="award-card-top">
        <div className="award-card-text">
          <p className="award-name">
            {award.award_name}
            {award.low_confidence && <span className="award-low-confidence">Low confidence</span>}
          </p>
          {winner ? (
            <>
              <h3 className="award-winner">{winner.full_name}</h3>
              <p className="award-team">
                {winner.team_name} · {winner.games_played} games
              </p>
              <dl className="award-stats">
                {stats.map(([key, label]) => (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>{formatStat(winner[key])}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <h3 className="award-winner">Not yet awarded</h3>
          )}
        </div>
        {winner && <PlayerArt player={winner} images={images} />}
      </div>
      <Picks picks={award.picks} />
    </article>
  )
}

// One card per award: the real winner with per-game stats, and the model's top three
// picks, made by a model trained only on earlier seasons. Renders nothing for a season
// with no awards data.
export default function AwardsSection({ awards, images = PLAYER_IMAGES }) {
  if (!awards || awards.length === 0) return null

  return (
    <section aria-labelledby="awards-heading">
      <h2 id="awards-heading">Awards</h2>
      <p className="awards-subtitle">
        Each season&apos;s picks come from a model trained only on earlier seasons.
      </p>
      <div className="award-grid">
        {awards.map((award) => (
          <AwardCard key={award.award_type} award={award} images={images} />
        ))}
      </div>
    </section>
  )
}
