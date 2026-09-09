export default function SeasonSelector({ seasons, selected, onChange }) {
  return (
    <label className="season-selector">
      Season
      <select value={selected} onChange={(e) => onChange(e.target.value)}>
        {seasons.map((season) => (
          <option key={season} value={season}>
            {season}
          </option>
        ))}
      </select>
    </label>
  )
}
