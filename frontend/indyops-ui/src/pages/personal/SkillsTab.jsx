import { useApi, fmtNum } from './common'

export default function SkillsTab({ charId }) {
  const { data, loading, error } = useApi(`/characters/${charId}/skills`, [charId])
  if (loading) return <div className="empty-state">Loading…</div>
  if (error)   return <div className="error-box">{error}</div>

  return (
    <div>
      <div style={{ marginBottom: 14, fontSize: 14, color: 'var(--text-white)' }}>
        Total SP: <strong>{fmtNum(data.total_sp)}</strong> · {data.skills.length} skills
      </div>
      {data.skills.length === 0 ? (
        <div className="empty-state">No skills synced yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Skill</th>
              <th style={{ textAlign: 'center' }}>Trained</th>
              <th style={{ textAlign: 'center' }}>Active</th>
              <th style={{ textAlign: 'right' }}>SP</th>
            </tr>
          </thead>
          <tbody>
            {data.skills.map(s => (
              <tr key={s.skill_id}>
                <td>{s.skill_name || s.skill_id}</td>
                <td style={{ textAlign: 'center' }}>{s.trained_level}</td>
                <td style={{ textAlign: 'center' }}>{s.active_level}</td>
                <td style={{ textAlign: 'right' }}>{fmtNum(s.skillpoints)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
