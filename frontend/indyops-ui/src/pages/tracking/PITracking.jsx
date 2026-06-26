// Tracking → PI: planetary-interaction colonies. Top section is one card per colony
// (planet image/type/radius + location, command-center level, extraction status and
// storage fill); when a colony stops extracting or its storage hits ≥90% the ESI sync
// posts an Agenda notification. Bottom section is a paste parser that adds extracted PI
// products to the warehouse (source='pi') and totals their Jita value as extraction profit.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { get, post, del } from '../../api/client'
import { fmtIsk, fmtInt, timeUntil, GREEN, RED, AMBER } from './fmt'
import { ScopeSelect, SyncButton, SortableTable } from './common'

const planetImg = (id, size = 128) =>
  id ? `https://images.evetech.net/types/${id}/render?size=${size}` : null
const cap = s => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '—')
const fmtRadius = m => (m == null ? '—' : `${fmtInt(Math.round(m / 1000))} km`)
const barColor = pct => (pct == null ? 'var(--accent-dim)' : pct >= 90 ? RED : pct >= 70 ? AMBER : GREEN)

function ExtractionStatus({ c }) {
  if (!c.has_extractor) return <span style={{ color: 'var(--text)' }}>No extractor</span>
  if (c.extracting) {
    return <span style={{ color: GREEN }}>● Extracting · ends in {timeUntil(c.extractor_expiry)}</span>
  }
  return <span style={{ color: RED }}>■ Stopped — idle</span>
}

function StorageBar({ c }) {
  const pct = c.storage_pct
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text)', marginBottom: 3 }}>
        <span>Storage</span>
        <span>{pct == null ? '—' : `${pct.toFixed(0)}%`} · {fmtInt(Math.round(c.storage_used || 0))}/{fmtInt(Math.round(c.storage_capacity || 0))} m³</span>
      </div>
      <div style={{ height: 7, borderRadius: 4, background: 'var(--bg-soft, rgba(255,255,255,0.08))', overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(100, pct || 0)}%`, height: '100%', background: barColor(pct) }} />
      </div>
    </div>
  )
}

function ColonyCard({ c }) {
  return (
    <div className="card" style={{ display: 'flex', gap: 14, padding: 14, minWidth: 320, flex: '1 1 340px' }}>
      <img src={planetImg(c.planet_type_id)} alt={c.planet_type || 'planet'} width={72} height={72}
        style={{ borderRadius: '50%', flexShrink: 0, background: 'rgba(0,0,0,0.25)' }}
        onError={e => { e.target.style.visibility = 'hidden' }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontWeight: 600, color: 'var(--text-white)' }}>{c.planet_name}</span>
          <span style={{ fontSize: 11, color: 'var(--text)' }}>{c.character_name}</span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 8 }}>
          {cap(c.planet_type)} · {c.system || '—'}{c.security != null ? ` (${c.security.toFixed(1)})` : ''}{c.region ? ` · ${c.region}` : ''}
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-bright)', marginBottom: 8, flexWrap: 'wrap' }}>
          <span>Radius <b>{fmtRadius(c.radius)}</b></span>
          <span>Level <b>{c.upgrade_level ?? '—'}</b></span>
          <span>Pins <b>{c.num_pins ?? '—'}</b></span>
        </div>
        <div style={{ fontSize: 12, marginBottom: 8 }}><ExtractionStatus c={c} /></div>
        <StorageBar c={c} />
        {c.products?.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {c.products.map(p => (
              <span key={p.type_id} title={p.value != null ? `${fmtIsk(p.value)} / unit (Jita sell)` : ''}
                style={{ fontSize: 11, padding: '2px 7px', borderRadius: 10, background: 'rgba(255,255,255,0.06)', color: 'var(--text-bright)' }}>
                {p.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function PITracking() {
  const [chars, setChars] = useState([])
  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])
  const groups = useMemo(() => [...new Set(chars.map(c => c.group_name).filter(Boolean))], [chars])
  const [scope, setScope] = useState('all')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => (
    get(`/account/pi?scope=${encodeURIComponent(scope)}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
  ), [scope])
  useEffect(() => { load() }, [load])

  // ── PI-stock warehouse parser ──
  const [stock, setStock] = useState(null)
  const [text, setText] = useState('')
  const [place, setPlace] = useState('')
  const [warns, setWarns] = useState([])
  const [busy, setBusy] = useState(false)

  const loadStock = useCallback(() => get('/account/pi/stock').then(setStock).catch(() => {}), [])
  useEffect(() => { loadStock() }, [loadStock])

  async function addStock() {
    setBusy(true); setWarns([])
    try {
      const r = await post('/account/pi/stock', { text, place: place || null })
      setStock({ rows: r.rows, total_value: r.total_value })
      setWarns(r.warnings || [])
      if (r.added > 0) setText('')
    } catch (e) { setWarns([e.message]) } finally { setBusy(false) }
  }
  async function removeStock(id) {
    try { await del(`/account/pi/stock/${id}`); loadStock() } catch { /* ignore */ }
  }

  const stockCols = [
    { key: 'name', label: 'Item', sortVal: r => r.name, render: r => r.name },
    { key: 'quantity', label: 'Qty', num: true, sortVal: r => r.quantity, render: r => fmtInt(r.quantity) },
    { key: 'place', label: 'Place', render: r => r.place || '—' },
    { key: 'unit_value', label: 'Jita / unit', num: true, sortVal: r => r.unit_value, render: r => fmtIsk(r.unit_value) },
    { key: 'value', label: 'Value', num: true, sortVal: r => r.value, render: r => <span style={{ color: GREEN }}>{fmtIsk(r.value)}</span> },
    { key: 'x', label: '', render: r => <button className="btn btn-ghost btn-sm" onClick={() => removeStock(r.id)}>✕</button> },
  ]

  const colonies = data?.colonies || []

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <ScopeSelect scope={scope} setScope={setScope} chars={chars} groups={groups} />
        <SyncButton scope={scope} onDone={load} />
        {!data && !err && <span style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</span>}
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      {data?.needs_scope?.length > 0 && (
        <div className="card" style={{ marginBottom: 16, borderColor: 'var(--accent-dim)', display: 'flex', gap: 10, alignItems: 'center' }}>
          <span style={{ color: AMBER }}>⚠</span>
          <span style={{ fontSize: 13, color: 'var(--text-bright)' }}>
            Re-link to grant the planets scope for: {data.needs_scope.join(', ')}. Their colonies won't appear until then.
          </span>
        </div>
      )}

      {colonies.length > 0
        ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, marginBottom: 8 }}>
            {colonies.map(c => <ColonyCard key={`${c.character_id}-${c.planet_id}`} c={c} />)}
          </div>
        : data && <div className="empty-state" style={{ padding: '28px 16px' }}>
            No colonies. Sync from ESI (needs the planets scope), or this character runs no PI.
          </div>}

      <div style={{ fontSize: 11, color: 'var(--text)', margin: '8px 0 24px' }}>
        Extraction status + storage are refreshed each ESI sync; a colony that stops extracting, fills its storage to ≥90%,
        or whose extractor stops within 24h posts a notification to the Agenda feed.
      </div>

      <div className="sec-label" style={{ marginBottom: 8 }}>Add extracted PI to warehouse</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start', marginBottom: 12 }}>
        <textarea value={text} onChange={e => setText(e.target.value)} rows={5}
          placeholder={'Paste from EVE (Name\tQty or Qty\tName), e.g.\nCoolant\t240\nMechanical Parts\t180'}
          style={{ flex: '1 1 320px', minWidth: 280, padding: 10, fontFamily: 'monospace', fontSize: 12 }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input value={place} onChange={e => setPlace(e.target.value)} placeholder="Place (optional)"
            style={{ padding: '7px 10px', minWidth: 180 }} />
          <button className="btn btn-primary btn-sm" onClick={addStock} disabled={busy || !text.trim()}>
            {busy ? 'Adding…' : 'Add to warehouse'}
          </button>
        </div>
      </div>
      {warns.length > 0 && (
        <div className="card" style={{ marginBottom: 12, borderColor: 'var(--accent-dim)', fontSize: 12, color: 'var(--text-bright)' }}>
          {warns.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <span className="sec-label">PI stock (Jita value = extraction profit)</span>
        <span style={{ fontSize: 14, fontWeight: 600, color: GREEN }}>{fmtIsk(stock?.total_value)}</span>
      </div>
      <SortableTable columns={stockCols} rows={stock?.rows || []} rowKey={r => r.id}
        empty="No PI stock yet. Paste your extracted products above to value them at Jita." />
    </div>
  )
}
