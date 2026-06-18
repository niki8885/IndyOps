import { useApi } from './common'

const TYPE_LABEL = { faction: 'Faction', npc_corp: 'Corporation', agent: 'Agent' }

function standingColor(v) {
  if (v == null) return 'var(--text)'
  if (v >= 5) return '#4caf7d'
  if (v > 0) return '#7bbf8e'
  if (v === 0) return 'var(--text)'
  if (v > -5) return '#e0884f'
  return '#e05252'
}

export default function StandingsTab({ charId }) {
  const { data, loading, error } = useApi(`/characters/${charId}/standings`, [charId])

  if (loading) return <div className="empty-state">Loading…</div>
  if (error)   return <div className="error-box">{error}</div>
  if (!data.length) return <div className="empty-state">No standings synced yet.</div>

  return (
    <table>
      <thead>
        <tr><th>Towards</th><th>Type</th><th style={{ textAlign: 'right' }}>Standing</th></tr>
      </thead>
      <tbody>
        {data.map(s => (
          <tr key={`${s.from_type}-${s.from_id}`}>
            <td style={{ color: 'var(--text-white)' }}>{s.name || `#${s.from_id}`}</td>
            <td style={{ color: 'var(--text)', fontSize: 12 }}>{TYPE_LABEL[s.from_type] || s.from_type}</td>
            <td style={{ textAlign: 'right', color: standingColor(s.standing), fontWeight: 600 }}>
              {s.standing == null ? '—' : s.standing.toFixed(2)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
