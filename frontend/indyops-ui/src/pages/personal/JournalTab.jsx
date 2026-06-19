import { useState } from 'react'
import { useApi, fmtNum } from './common'

// Historical mining ledger: a chronological list of what was mined, when, and how
// much (one row per day × ore × system, straight from ESI — newest first). The
// ISK valuation / profit report lives in the Statistics tab; the knobs in Settings.
const PERIODS = [
  ['all', 'All time'],
  ['day', 'Day'],
  ['month', 'Month'],
  ['quarter', 'Quarter'],
  ['year', 'Year'],
]
const CAT_META = {
  ore:      ['Ore', '#9aa7b4'],
  moon_ore: ['Moon', '#c08fe0'],
  ice:      ['Ice', '#6fb7e0'],
  gas:      ['Gas', '#6fd0a0'],
  other:    ['Other', 'var(--text)'],
}

const typeIcon = (id, size = 32) => `https://images.evetech.net/types/${id}/icon?size=${size}`
const fmtDay = (s) => (s ? new Date(s + 'T00:00:00').toLocaleDateString() : '—')

export default function JournalTab({ charId }) {
  const [period, setPeriod] = useState('all')
  const [offset, setOffset] = useState(0)
  const [scope, setScope]   = useState('character')

  const qs = new URLSearchParams({ scope })
  if (period !== 'all') qs.set('period', period)
  if (period !== 'all') qs.set('offset', String(offset))
  const { data, loading, error } = useApi(
    `/characters/${charId}/mining-ledger?${qs}`,
    [charId, period, offset, scope],
  )

  const entries = data?.entries || []
  const showChar = scope === 'all'

  return (
    <div>
      {/* controls */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center', marginBottom: 16 }}>
        <Seg options={[['character', 'This character'], ['all', 'All characters']]} value={scope} onChange={setScope} />
        <Seg options={PERIODS} value={period} onChange={v => { setPeriod(v); setOffset(0) }} />
        {period !== 'all' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setOffset(o => o - 1)}>‹</button>
            <span style={{ fontSize: 13, color: 'var(--text-white)', minWidth: 90, textAlign: 'center' }}>
              {data?.period?.key || '—'}
            </span>
            <button className="btn btn-ghost btn-sm" onClick={() => setOffset(o => Math.min(0, o + 1))} disabled={offset >= 0}>›</button>
          </div>
        )}
        {data && (
          <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text)' }}>
            {fmtNum(data.count)} entr{data.count === 1 ? 'y' : 'ies'} · {fmtNum(data.total_quantity)} units
          </div>
        )}
      </div>

      {error && <div className="error-box">{error}</div>}
      {loading && !data && <div className="empty-state">Loading…</div>}

      {data && entries.length === 0 && (
        <div className="empty-state">
          No mining recorded{period !== 'all' ? ' for this period' : ' yet'}. The ledger syncs from ESI
          (last ~30 days) and accumulates history over time.
        </div>
      )}

      {entries.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              {showChar && <th>Character</th>}
              <th>Ore type</th>
              <th>Category</th>
              <th>System</th>
              <th style={{ textAlign: 'right' }}>Quantity</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => {
              const [label, color] = CAT_META[e.category] || CAT_META.other
              return (
                <tr key={`${e.character_id}-${e.date}-${e.type_id}-${e.solar_system_id}-${i}`}>
                  <td style={{ whiteSpace: 'nowrap', color: 'var(--text-bright)' }}>{fmtDay(e.date)}</td>
                  {showChar && <td style={{ fontSize: 12, color: 'var(--text)' }}>{e.character_name || e.character_id}</td>}
                  <td>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <img src={typeIcon(e.type_id)} alt="" width={24} height={24} style={{ borderRadius: 3 }} />
                      <span style={{ color: 'var(--text-white)' }}>{e.name}</span>
                    </span>
                  </td>
                  <td><span style={{ fontSize: 12, color }}>{label}</span></td>
                  <td style={{ fontSize: 12, color: 'var(--text)' }}>{e.system_name || '—'}</td>
                  <td style={{ textAlign: 'right' }}>{fmtNum(e.quantity)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Seg({ options, value, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {options.map(([v, label]) => (
        <button key={v} onClick={() => onChange(v)}
          className={`btn btn-sm ${value === v ? 'btn-primary' : 'btn-ghost'}`}
          style={{ padding: '3px 10px', fontSize: 12 }}>{label}</button>
      ))}
    </div>
  )
}
