import { useState, useEffect, useCallback } from 'react'
import { get, post, patch, del } from '../api/client'

// Create / manage price-volume alerts for ONE target (an index or a tracked item).
// Launched by the 🔔 icon on the Analysis page's Indices and Tracking tabs; the
// target is fixed, so there's no index/item picker here — see [AgendaPage] for the feed.
const CONDITIONS = [
  ['above', 'Rises above'],
  ['below', 'Falls below'],
  ['pct_up', 'Up by %'],
  ['pct_down', 'Down by %'],
]
const METRICS = [['price', 'Price'], ['volume', 'Volume']]

function fmtPrice(v) {
  if (v == null) return '—'
  const n = Number(v), abs = Math.abs(n)
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function condText(a) {
  if (a.condition === 'above') return `${a.metric} ≥ ${fmtPrice(a.threshold)}`
  if (a.condition === 'below') return `${a.metric} ≤ ${fmtPrice(a.threshold)}`
  if (a.condition === 'pct_up') return `${a.metric} +${a.threshold}% / ${a.window_hours}h`
  if (a.condition === 'pct_down') return `${a.metric} −${a.threshold}% / ${a.window_hours}h`
  return a.condition
}

export default function AlertDialog({ target, onClose }) {
  const isItem = target.kind === 'item'
  const places = target.places || []

  const [alerts, setAlerts]         = useState([])
  const [metric, setMetric]         = useState('price')
  const [condition, setCondition]   = useState('above')
  const [threshold, setThreshold]   = useState('')
  const [windowHours, setWindowHours] = useState(24)
  const [repeat, setRepeat]         = useState(false)
  const [note, setNote]             = useState('')
  const [placeId, setPlaceId]       = useState('')
  const [busy, setBusy]             = useState(false)
  const [err, setErr]               = useState('')

  const isPct = condition === 'pct_up' || condition === 'pct_down'

  const reload = useCallback(() => get('/agenda/alerts').then(rows => {
    setAlerts((rows || []).filter(a => isItem ? a.item_id === target.itemId : a.index_key === target.key))
  }).catch(() => {}), [isItem, target.itemId, target.key])

  useEffect(() => { reload() }, [reload])

  async function create(e) {
    e.preventDefault()
    setErr('')
    if (threshold === '' || isNaN(Number(threshold))) { setErr('Enter a threshold value'); return }
    setBusy(true)
    try {
      await post('/agenda/alerts', {
        target_kind: target.kind,
        index_key: isItem ? null : target.key,
        item_id: isItem ? target.itemId : null,
        place_id: isItem && placeId ? Number(placeId) : null,
        metric, condition,
        threshold: Number(threshold),
        window_hours: Number(windowHours) || 24,
        repeat, note: note || null,
      })
      setThreshold(''); setNote('')
      reload()
    } catch (e2) { setErr(e2.message) }
    finally { setBusy(false) }
  }

  async function toggle(a) { await patch(`/agenda/alerts/${a.id}`, { active: !a.active }); reload() }
  async function remove(id) { await del(`/agenda/alerts/${id}`); reload() }

  return (
    <div onClick={onClose} style={overlay}>
      <div onClick={e => e.stopPropagation()} className="card"
        style={{ width: 460, maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
          <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>
            🔔 ALERTS · {target.label}
          </span>
          <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>

        {/* create */}
        <form onSubmit={create} style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            {isItem && (
              <select value={placeId} onChange={e => setPlaceId(e.target.value)} style={{ gridColumn: '1 / -1' }}>
                <option value="">Auto (first place)</option>
                {places.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            <select value={metric} onChange={e => setMetric(e.target.value)}>
              {METRICS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <select value={condition} onChange={e => setCondition(e.target.value)}>
              {CONDITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <input type="number" step="any" placeholder={isPct ? 'Percent, e.g. 10' : 'Value'}
              value={threshold} onChange={e => setThreshold(e.target.value)} />
            {isPct
              ? <input type="number" min="1" placeholder="Window (hours)"
                  value={windowHours} onChange={e => setWindowHours(e.target.value)} />
              : <div />}
          </div>
          <input type="text" placeholder="Note (optional)" value={note}
            onChange={e => setNote(e.target.value)} style={{ marginBottom: 8 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-bright)', width: 'auto' }}>
              <input type="checkbox" checked={repeat} onChange={e => setRepeat(e.target.checked)} style={{ width: 'auto' }} />
              Repeat
            </label>
            <button className="btn btn-primary btn-sm" disabled={busy} style={{ marginLeft: 'auto' }}>
              {busy ? '…' : 'Create alert'}
            </button>
          </div>
          {err && <div style={{ color: '#e88', fontSize: 12, marginTop: 8 }}>{err}</div>}
        </form>

        {/* existing */}
        <div style={{ fontSize: 11, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
          Existing alerts
        </div>
        {alerts.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--text)', padding: '6px 0' }}>None yet for this target.</div>
        ) : alerts.map(a => (
          <div key={a.id} style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0',
            borderTop: '1px solid var(--border)', opacity: a.active ? 1 : 0.5,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: 'var(--text-bright)', fontSize: 13 }}>
                {condText(a)}{a.repeat ? ' · repeats' : ''}
              </div>
              {a.note && <div style={{ color: 'var(--text)', fontSize: 11 }}>{a.note}</div>}
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => toggle(a)}>{a.active ? 'Pause' : 'Arm'}</button>
            <button className="btn btn-ghost btn-sm" onClick={() => remove(a.id)}>✕</button>
          </div>
        ))}
      </div>
    </div>
  )
}

const overlay = {
  position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,.55)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
}
