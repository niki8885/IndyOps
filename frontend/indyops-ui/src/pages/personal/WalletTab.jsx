import { useApi, fmtIsk, fmtNum, fmtDate } from './common'

export default function WalletTab({ charId }) {
  const { data, loading, error } = useApi(`/characters/${charId}/wallet?limit=300`, [charId])
  if (loading) return <div className="empty-state">Loading…</div>
  if (error)   return <div className="error-box">{error}</div>

  return (
    <div>
      <div style={{ marginBottom: 14, fontSize: 15, color: 'var(--text-white)' }}>
        Balance: <strong>{fmtIsk(data.balance)}</strong>
      </div>
      {data.transactions.length === 0 ? (
        <div className="empty-state">No transactions synced yet — hit “Sync now” on the Characters tab.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Date</th><th>Item</th>
              <th style={{ textAlign: 'right' }}>Qty</th>
              <th style={{ textAlign: 'right' }}>Unit price</th>
              <th style={{ textAlign: 'right' }}>Total</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            {data.transactions.map(t => (
              <tr key={t.transaction_id}>
                <td>{fmtDate(t.date)}</td>
                <td>{t.type_name || t.type_id}</td>
                <td style={{ textAlign: 'right' }}>{fmtNum(t.quantity)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(t.unit_price)}</td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(t.total)}</td>
                <td><span className={`badge ${t.is_buy ? 'badge-warn' : 'badge-ok'}`}>{t.is_buy ? 'BUY' : 'SELL'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
