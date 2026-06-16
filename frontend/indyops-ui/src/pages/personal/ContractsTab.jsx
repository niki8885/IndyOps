import { useApi, fmtIsk, fmtDate } from './common'

export default function ContractsTab({ charId }) {
  const { data, loading, error } = useApi(`/characters/${charId}/contracts`, [charId])
  if (loading) return <div className="empty-state">Loading…</div>
  if (error)   return <div className="error-box">{error}</div>
  if (!data.length) return <div className="empty-state">No contracts synced yet.</div>

  return (
    <table>
      <thead>
        <tr>
          <th>Title</th><th>Type</th><th>Status</th>
          <th style={{ textAlign: 'right' }}>Price</th>
          <th style={{ textAlign: 'right' }}>Reward</th>
          <th>Issued</th><th>Expires</th>
        </tr>
      </thead>
      <tbody>
        {data.map(c => (
          <tr key={c.contract_id}>
            <td>{c.title || '—'}</td>
            <td>{c.type}</td>
            <td><span className="badge badge-warn">{c.status}</span></td>
            <td style={{ textAlign: 'right' }}>{fmtIsk(c.price)}</td>
            <td style={{ textAlign: 'right' }}>{fmtIsk(c.reward)}</td>
            <td>{fmtDate(c.date_issued)}</td>
            <td>{fmtDate(c.date_expired)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
