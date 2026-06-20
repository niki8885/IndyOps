import TypeSearch from '../../components/TypeSearch'

// Pretty-print a duration in seconds → "1d 4h 12m".
export function fmtTime(s) {
  if (s == null) return '—'
  s = Math.round(s)
  if (s <= 0) return '0s'
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const parts = []
  if (d) parts.push(d + 'd')
  if (h) parts.push(h + 'h')
  if (m) parts.push(m + 'm')
  if (!d && !h && sec) parts.push(sec + 's')
  return parts.join(' ') || '0s'
}

// A chosen type may be the product or the blueprint itself — send the right field.
export function idBody(type) {
  if (!type) return {}
  return /blueprint/i.test(type.name || '')
    ? { blueprint_type_id: type.type_id }
    : { product_type_id: type.type_id }
}

export function Label({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}

/** Blueprint + facility + character pickers, shared by the research sub-tabs. */
export function Selectors({ type, setType, facilities, facilityId, setFacilityId,
                            characters, characterId, setCharacterId }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 12, marginBottom: 14 }}>
      <div>
        <Label>Blueprint / product</Label>
        <TypeSearch value={type} onChange={t => setType(t?.type_id ? t : null)}
                    placeholder="Search blueprint or product…" />
      </div>
      <div>
        <Label>Factory</Label>
        <select value={facilityId} onChange={e => setFacilityId(e.target.value)}>
          <option value="">— none —</option>
          {facilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
      </div>
      <div>
        <Label>Character (skills)</Label>
        <select value={characterId} onChange={e => setCharacterId(e.target.value)}>
          <option value="">— none —</option>
          {characters.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
        </select>
      </div>
    </div>
  )
}
