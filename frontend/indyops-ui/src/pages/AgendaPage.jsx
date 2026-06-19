import { useState, useEffect, useCallback } from 'react'
import { get, post, patch, del } from '../api/client'

// ── formatting ───────────────────────────────────────────────────────────────
const GREEN = '#4caf7d', RED = '#e05252'

function fmtPrice(v) {
  if (v == null) return '—'
  const n = Number(v), abs = Math.abs(n)
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
const fmtPct = (v) => (v == null ? '' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const pctColor = (v) => (v == null ? 'var(--text)' : v > 0 ? GREEN : v < 0 ? RED : 'var(--text)')
const sevColor = (s) => (s === 'up' ? GREEN : s === 'down' ? RED : 'var(--accent)')

function timeAgo(iso) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/** Fetch `path` on mount + every `ms`; returns [data, reload]. setState only in
 *  async callbacks (no synchronous setState in the effect body). */
function usePoll(path, ms) {
  const [data, setData] = useState(null)
  const reload = useCallback(() => get(path).then(setData).catch(() => {}), [path])
  useEffect(() => {
    let alive = true
    const tick = () => get(path).then(d => { if (alive) setData(d) }).catch(() => {})
    tick()
    const id = setInterval(tick, ms)
    return () => { alive = false; clearInterval(id) }
  }, [path, ms])
  return [data, reload]
}

// ── page ───────────────────────────────────────────────────────────────────
export default function AgendaPage() {
  return (
    <div>
      <h2 style={{ marginBottom: 14 }}>Agenda</h2>
      <Ticker />
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 20, marginTop: 20 }}>
        <NotificationsFeed />
        <AlertsPanel />
      </div>
    </div>
  )
}

// ── ticker ───────────────────────────────────────────────────────────────────
function Ticker() {
  const [data] = usePoll('/agenda/ticker', 60_000)
  const entries = data?.entries || []

  if (!entries.length) {
    return (
      <div className="ticker">
        <div style={{ padding: '12px 16px', fontSize: 13, color: 'var(--text)' }}>
          No index or tracked-item data yet — it builds as the hourly collectors run.
        </div>
      </div>
    )
  }
  const loop = [...entries, ...entries]   // duplicate for a seamless marquee loop
  return (
    <div className="ticker">
      <div className="ticker-track">
        {loop.map((e, i) => (
          <span key={`${e.kind}-${e.key}-${i}`} className="ticker-item">
            <span style={{ color: 'var(--text)', fontSize: 10, textTransform: 'uppercase' }}>
              {e.kind === 'index' ? '◆' : '•'}
            </span>
            <span style={{ color: 'var(--text-white)' }}>{e.label}</span>
            <span style={{ color: 'var(--text-bright)' }}>{fmtPrice(e.price)}</span>
            {e.change_pct != null && (
              <span style={{ color: pctColor(e.change_pct), fontSize: 12 }}>{fmtPct(e.change_pct)}</span>
            )}
          </span>
        ))}
      </div>
    </div>
  )
}

// ── notifications feed ───────────────────────────────────────────────────────
function NotificationsFeed() {
  const [data, reload] = usePoll('/agenda/notifications', 30_000)
  const notifs = data?.notifications || []
  const unread = data?.unread || 0

  async function markAll() { await post('/agenda/notifications/read-all'); reload() }
  async function markOne(id) { await post(`/agenda/notifications/${id}/read`); reload() }
  async function dismiss(id) { await del(`/agenda/notifications/${id}`); reload() }

  return (
    <div className="card" style={{ padding: 0, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>NOTIFICATIONS</span>
        {unread > 0 && <span className="badge badge-warn">{unread} new</span>}
        {unread > 0 && (
          <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={markAll}>Mark all read</button>
        )}
      </div>

      {notifs.length === 0 ? (
        <div className="empty-state" style={{ padding: '40px 20px' }}>No notifications yet. Create an alert →</div>
      ) : (
        <div style={{ maxHeight: 520, overflowY: 'auto' }}>
          {notifs.map(n => (
            <div key={n.id} style={{
              display: 'flex', gap: 12, padding: '12px 18px', borderBottom: '1px solid var(--border)',
              background: n.read ? 'transparent' : 'var(--surface2)',
            }}>
              <span style={{ color: sevColor(n.severity), fontSize: 18, lineHeight: 1 }}>
                {n.severity === 'down' ? '▾' : n.severity === 'up' ? '▴' : '•'}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: 'var(--text-white)', fontSize: 13 }}>{n.title}</div>
                {n.body && <div style={{ color: 'var(--text)', fontSize: 12, marginTop: 2 }}>{n.body}</div>}
                <div style={{ color: 'var(--border2)', fontSize: 11, marginTop: 4 }}>{timeAgo(n.created_at)}</div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {!n.read && <button className="btn btn-ghost btn-sm" onClick={() => markOne(n.id)}>Read</button>}
                <button className="btn btn-ghost btn-sm" onClick={() => dismiss(n.id)}>✕</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── alerts panel ─────────────────────────────────────────────────────────────
const CONDITIONS = [
  ['above', 'Rises above'],
  ['below', 'Falls below'],
  ['pct_up', 'Up by %'],
  ['pct_down', 'Down by %'],
]
const METRICS = [['price', 'Price'], ['volume', 'Volume']]

function condText(a) {
  if (a.condition === 'above') return `${a.metric} ≥ ${fmtPrice(a.threshold)}`
  if (a.condition === 'below') return `${a.metric} ≤ ${fmtPrice(a.threshold)}`
  if (a.condition === 'pct_up') return `${a.metric} +${a.threshold}% / ${a.window_hours}h`
  if (a.condition === 'pct_down') return `${a.metric} −${a.threshold}% / ${a.window_hours}h`
  return a.condition
}

function AlertsPanel() {
  const [alerts, setAlerts] = useState([])
  const [indices, setIndices] = useState([])
  const [items, setItems] = useState([])
  const [places, setPlaces] = useState([])

  const reloadAlerts = useCallback(() => get('/agenda/alerts').then(setAlerts).catch(() => {}), [])

  useEffect(() => {
    let alive = true
    reloadAlerts()
    get('/analysis/indices').then(d => { if (alive) setIndices(d.indices || []) }).catch(() => {})
    get('/tracking/items').then(d => { if (alive) setItems(d || []) }).catch(() => {})
    get('/tracking/places').then(d => { if (alive) setPlaces(d || []) }).catch(() => {})
    return () => { alive = false }
  }, [reloadAlerts])

  async function toggle(a) { await patch(`/agenda/alerts/${a.id}`, { active: !a.active }); reloadAlerts() }
  async function remove(id) { await del(`/agenda/alerts/${id}`); reloadAlerts() }

  return (
    <div className="card" style={{ padding: 0, minWidth: 0 }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>ALERTS</span>
      </div>

      <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--border)' }}>
        <CreateAlertForm indices={indices} items={items} places={places} onCreated={reloadAlerts} />
      </div>

      {alerts.length === 0 ? (
        <div className="empty-state" style={{ padding: '32px 20px' }}>No alerts yet.</div>
      ) : (
        <div style={{ maxHeight: 420, overflowY: 'auto' }}>
          {alerts.map(a => (
            <div key={a.id} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '11px 18px', borderBottom: '1px solid var(--border)',
              opacity: a.active ? 1 : 0.5,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: 'var(--text-white)', fontSize: 13 }}>
                  {a.label} <span style={{ color: 'var(--text)', fontSize: 11 }}>· {a.target_kind}</span>
                </div>
                <div style={{ color: 'var(--text-bright)', fontSize: 12, marginTop: 2 }}>
                  {condText(a)}{a.repeat ? ' · repeats' : ''}
                  {a.last_triggered_at && <span style={{ color: 'var(--text)' }}> · fired {timeAgo(a.last_triggered_at)}</span>}
                </div>
                {a.note && <div style={{ color: 'var(--text)', fontSize: 11, marginTop: 2 }}>{a.note}</div>}
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => toggle(a)}>{a.active ? 'Pause' : 'Arm'}</button>
              <button className="btn btn-ghost btn-sm" onClick={() => remove(a.id)}>✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CreateAlertForm({ indices, items, places, onCreated }) {
  const [kind, setKind] = useState('index')
  const [indexKey, setIndexKey] = useState('')
  const [itemId, setItemId] = useState('')
  const [placeId, setPlaceId] = useState('')
  const [metric, setMetric] = useState('price')
  const [condition, setCondition] = useState('above')
  const [threshold, setThreshold] = useState('')
  const [windowHours, setWindowHours] = useState(24)
  const [repeat, setRepeat] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const isPct = condition === 'pct_up' || condition === 'pct_down'
  const selectedItem = items.find(i => String(i.id) === String(itemId))
  const itemPlaces = places.filter(p => !selectedItem?.place_ids?.length || selectedItem.place_ids.includes(p.id))

  async function submit(e) {
    e.preventDefault()
    setErr('')
    if (threshold === '' || isNaN(Number(threshold))) { setErr('Enter a threshold value'); return }
    if (kind === 'index' && !indexKey) { setErr('Pick an index'); return }
    if (kind === 'item' && !itemId) { setErr('Pick a tracked item'); return }
    setBusy(true)
    try {
      await post('/agenda/alerts', {
        target_kind: kind,
        index_key: kind === 'index' ? indexKey : null,
        item_id: kind === 'item' ? Number(itemId) : null,
        place_id: kind === 'item' && placeId ? Number(placeId) : null,
        metric, condition,
        threshold: Number(threshold),
        window_hours: Number(windowHours) || 24,
        repeat, note: note || null,
      })
      setThreshold(''); setNote('')
      onCreated()
    } catch (e2) { setErr(e2.message) }
    finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit}>
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {[['index', 'Index'], ['item', 'Tracked item']].map(([v, l]) => (
          <button key={v} type="button" onClick={() => setKind(v)}
            className={`btn btn-sm ${kind === v ? 'btn-primary' : 'btn-ghost'}`}>{l}</button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
        {kind === 'index' ? (
          <select value={indexKey} onChange={e => setIndexKey(e.target.value)} style={{ gridColumn: '1 / -1' }}>
            <option value="">Select index…</option>
            {indices.map(i => <option key={i.key} value={i.key}>{i.label}</option>)}
          </select>
        ) : (
          <>
            <select value={itemId} onChange={e => { setItemId(e.target.value); setPlaceId('') }}>
              <option value="">Select item…</option>
              {items.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
            <select value={placeId} onChange={e => setPlaceId(e.target.value)}>
              <option value="">Auto (first place)</option>
              {itemPlaces.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </>
        )}

        <select value={metric} onChange={e => setMetric(e.target.value)}>
          {METRICS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={condition} onChange={e => setCondition(e.target.value)}>
          {CONDITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>

        <input type="number" step="any" placeholder={isPct ? 'Percent, e.g. 10' : 'Value'}
          value={threshold} onChange={e => setThreshold(e.target.value)} />
        {isPct ? (
          <input type="number" min="1" placeholder="Window (hours)"
            value={windowHours} onChange={e => setWindowHours(e.target.value)} />
        ) : <div />}
      </div>

      <input type="text" placeholder="Note (optional)" value={note} onChange={e => setNote(e.target.value)}
        style={{ marginBottom: 8 }} />

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
  )
}
