import { useState, useEffect, useCallback, useMemo } from 'react'
import { get } from '../api/client'
import TradePortfolio from './TradePortfolio'

// Self-contained formatters (kept local so this page doesn't pull in Plotly via
// lib/plot — it has no charts and stays in the main bundle).
function fmtIsk(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' B'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' M'
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + ' K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
function fmtNum(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
}
function pct(v) {
  if (v == null) return '—'
  return (Number(v) * 100).toFixed(1) + '%'
}
const iconUrl = (id, size = 32) => `https://images.evetech.net/types/${id}/icon?size=${size}`

const GREEN = '#4caf7d', BLUE = '#3a9bd6', RED = '#e05252'

export default function TradeOptimizerPage() {
  const [tab, setTab] = useState(0)              // 0 = cross-hub, 1 = in-station
  const [hubs, setHubs] = useState([])           // [{name, station_id, region_id}]

  // filters
  const [budget, setBudget] = useState('')
  const [cargo, setCargo] = useState('')
  const [minMargin, setMinMargin] = useState('') // percent, e.g. "5"
  const [strategy, setStrategy] = useState('patient')
  const [buyHubs, setBuyHubs] = useState([])
  const [sellHubs, setSellHubs] = useState([])
  const [stationHubs, setStationHubs] = useState([])
  const [minVol, setMinVol] = useState(0)        // dynamic daily-volume floor (client filter)
  const [risk, setRisk] = useState(8)            // portfolio risk-aversion λ

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { get('/trade/hubs').then(setHubs).catch(() => setHubs([])) }, [])

  const load = useCallback(async () => {
    if (tab === 2) return                 // the Portfolio tab fetches on its own
    setLoading(true); setErr('')
    try {
      const qs = new URLSearchParams({ limit: '100' })
      if (budget) qs.set('budget', budget)
      if (minMargin) qs.set('min_margin', String(Number(minMargin) / 100))
      let path
      if (tab === 0) {
        if (cargo) qs.set('cargo', cargo)
        qs.set('strategy', strategy)
        if (buyHubs.length) qs.set('buy_hubs', buyHubs.join(','))
        if (sellHubs.length) qs.set('sell_hubs', sellHubs.join(','))
        path = `/trade/candidates?${qs}`
      } else {
        if (stationHubs.length) qs.set('hubs', stationHubs.join(','))
        path = `/trade/station?${qs}`
      }
      setData(await get(path))
    } catch (e) { setErr(e.message); setData(null) }
    finally { setLoading(false) }
  }, [tab, budget, cargo, minMargin, strategy, buyHubs, sellHubs, stationHubs])

  // auto-load on mount + when the tab / strategy / hub selections change;
  // numeric inputs apply via the Apply button (or Enter) to avoid per-keystroke calls.
  // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
  useEffect(() => { load() }, [tab, strategy, buyHubs, sellHubs, stationHubs])

  const toggle = (arr, set, name) =>
    set(arr.includes(name) ? arr.filter(h => h !== name) : [...arr, name])

  const onKey = e => { if (e.key === 'Enter') load() }

  // dynamic volume filter: live client-side filter of the loaded rows by daily volume
  const volMax = useMemo(
    () => Math.max(0, ...((data?.rows) || []).map(r => Number(r.daily_volume) || 0)),
    [data])
  const shown = useMemo(
    () => ((data?.rows) || []).filter(r => (Number(r.daily_volume) || 0) >= minVol),
    [data, minVol])

  return (
    <div>
      <div style={{ color: 'var(--text)', fontSize: 12, marginBottom: 14 }}>
        Precomputed trade candidates — filter and rank instantly, no live API calls.
      </div>

      <div className="tabs">
        {['Cross-hub routes', 'In-station flips', 'Portfolio'].map((t, i) => (
          <button key={t} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>
            {t}
          </button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 18, alignItems: 'start' }}>
        {/* ── filters ── */}
        <div className="card" style={{ padding: 16, position: 'sticky', top: 16 }}>
          <RailLabel>ISK Budget</RailLabel>
          <input type="number" min="0" placeholder="e.g. 500000000" value={budget}
            onChange={e => setBudget(e.target.value)} onKeyDown={onKey} />

          {tab === 0 && (
            <>
              <RailLabel style={{ marginTop: 16 }}>Cargo m³</RailLabel>
              <input type="number" min="0" placeholder="e.g. 60000" value={cargo}
                onChange={e => setCargo(e.target.value)} onKeyDown={onKey} />
            </>
          )}

          <RailLabel style={{ marginTop: 16 }}>Min margin %</RailLabel>
          <input type="number" min="0" step="0.1" placeholder="e.g. 5" value={minMargin}
            onChange={e => setMinMargin(e.target.value)} onKeyDown={onKey} />

          {volMax > 0 && (
            <>
              <RailLabel style={{ marginTop: 16 }}>
                Min volume/day — {minVol > 0 ? fmtNum(minVol) : 'any'}
              </RailLabel>
              <input type="range" min="0" max={Math.ceil(volMax)} step={Math.max(1, Math.ceil(volMax / 100))}
                value={Math.min(minVol, Math.ceil(volMax))} onChange={e => setMinVol(Number(e.target.value))}
                style={{ width: '100%' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text)' }}>
                <span>any</span><span>{fmtNum(volMax)}/day</span>
              </div>
              {tab === 2 && (
                <div style={{ fontSize: 10, color: 'var(--text)', marginTop: 4 }}>
                  Applied as the portfolio liquidity floor.
                </div>
              )}
            </>
          )}

          {tab === 0 && (
            <>
              <RailLabel style={{ marginTop: 16 }}>Sell strategy</RailLabel>
              <div style={{ display: 'flex', gap: 6 }}>
                {[['patient', 'Sell order'], ['instant', 'To buy orders']].map(([v, lbl]) => (
                  <button key={v} onClick={() => setStrategy(v)}
                    className={`btn btn-sm ${strategy === v ? 'btn-primary' : 'btn-ghost'}`}
                    style={{ flex: 1, padding: '4px 8px', fontSize: 11 }}>{lbl}</button>
                ))}
              </div>

              <RailLabel style={{ marginTop: 16 }}>Buy at</RailLabel>
              <HubToggles hubs={hubs} selected={buyHubs} onToggle={n => toggle(buyHubs, setBuyHubs, n)} />

              <RailLabel style={{ marginTop: 16 }}>Sell at</RailLabel>
              <HubToggles hubs={hubs} selected={sellHubs} onToggle={n => toggle(sellHubs, setSellHubs, n)} />
            </>
          )}

          {tab === 1 && (
            <>
              <RailLabel style={{ marginTop: 16 }}>Hubs</RailLabel>
              <HubToggles hubs={hubs} selected={stationHubs} onToggle={n => toggle(stationHubs, setStationHubs, n)} />
            </>
          )}

          {tab !== 2 && (
            <button className="btn btn-primary" style={{ width: '100%', marginTop: 18 }}
              onClick={load} disabled={loading}>
              {loading ? 'Loading…' : 'Apply filters'}
            </button>
          )}
        </div>

        {/* ── results ── */}
        <div>
          {tab === 2 ? (
            <TradePortfolio budget={budget} buyHubs={buyHubs} sellHubs={sellHubs} strategy={strategy}
              minMargin={minMargin} cargo={cargo} minVol={minVol} risk={risk} setRisk={setRisk} />
          ) : (
            <>
              {data && <Freshness data={data} shown={shown.length} />}
              {err && <div className="error-box">{err}</div>}
              {loading && !data && <div className="empty-state">Loading candidates…</div>}
              {!loading && data && data.count === 0 && (
                <div className="empty-state">
                  No candidates match. The worker may not have populated the tables yet, or loosen the filters.
                </div>
              )}
              {data && data.count > 0 && shown.length === 0 && (
                <div className="empty-state">No routes above the volume floor — lower the Min volume/day slider.</div>
              )}
              {data && shown.length > 0 && (
                tab === 0 ? <CrossTable rows={shown} /> : <StationTable rows={shown} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function HubToggles({ hubs, selected, onToggle }) {
  if (!hubs.length) return <div style={{ color: 'var(--text)', fontSize: 11 }}>—</div>
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
      {hubs.map(h => (
        <button key={h.station_id} onClick={() => onToggle(h.name)}
          className={`btn btn-sm ${selected.includes(h.name) ? 'btn-primary' : 'btn-ghost'}`}
          style={{ padding: '2px 8px', fontSize: 11 }}>
          {h.name}
        </button>
      ))}
    </div>
  )
}

function Freshness({ data, shown }) {
  const when = data.updated_at ? new Date(data.updated_at).toLocaleString() : 'never'
  const countLabel = (shown != null && shown !== data.count)
    ? `${shown} of ${data.count} candidates` : `${data.count} candidate${data.count === 1 ? '' : 's'}`
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, fontSize: 12,
      color: data.stale ? '#c8a951' : 'var(--text)',
    }}>
      <span>{countLabel} · data updated {when}</span>
      {data.stale && <span>⚠ stale (older than {Math.round(data.ttl_seconds / 60)} min) — worker refresh pending</span>}
    </div>
  )
}

function CrossTable({ rows }) {
  return (
    <Panel title="Ranked routes">
      <div style={{ maxHeight: 640, overflowY: 'auto' }}>
        <table>
          <thead>
            <tr>
              <Th c>#</Th><Th>Item</Th><Th>Route</Th><Th r>Buy</Th><Th r>Sell</Th>
              <Th r>Margin</Th><Th r>Profit/u</Th><Th r>Units</Th><Th r>Trip profit</Th>
              <Th r>Vol/day</Th><Th r>Score</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.item_id}-${r.buy_hub}-${r.sell_hub}`}>
                <Rank i={i} />
                <ItemCell r={r} />
                <td style={{ whiteSpace: 'nowrap' }}>
                  {r.buy_hub} <span style={{ color: 'var(--border2)' }}>→</span> {r.sell_hub}
                </td>
                <td style={cell}>{fmtIsk(r.buy_price)}</td>
                <td style={cell}>{fmtIsk(r.sell_price)}</td>
                <td style={{ ...cell, color: r.margin_pct >= 0 ? GREEN : RED, fontWeight: 600 }}>{pct(r.margin_pct)}</td>
                <td style={cell}>{fmtIsk(r.profit_isk)}</td>
                <td style={cell}>{fmtNum(r.units)}</td>
                <td style={{ ...cell, color: GREEN, fontWeight: 600 }}>{fmtIsk(r.trip_profit)}</td>
                <td style={cell}>{fmtNum(r.daily_volume)}</td>
                <td style={{ ...cell, color: BLUE }}>{r.score?.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function StationTable({ rows }) {
  return (
    <Panel title="Ranked station flips">
      <div style={{ maxHeight: 640, overflowY: 'auto' }}>
        <table>
          <thead>
            <tr>
              <Th c>#</Th><Th>Item</Th><Th>Hub</Th><Th r>Buy</Th><Th r>Sell</Th>
              <Th r>Margin</Th><Th r>Profit/u</Th><Th r>Units</Th><Th r>Trip profit</Th>
              <Th r>Vol/day</Th><Th r>Score</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.item_id}-${r.hub}`}>
                <Rank i={i} />
                <ItemCell r={r} />
                <td style={{ whiteSpace: 'nowrap' }}>{r.hub}</td>
                <td style={cell}>{fmtIsk(r.buy_price)}</td>
                <td style={cell}>{fmtIsk(r.sell_price)}</td>
                <td style={{ ...cell, color: r.margin_pct >= 0 ? GREEN : RED, fontWeight: 600 }}>{pct(r.margin_pct)}</td>
                <td style={cell}>{fmtIsk(r.profit_isk)}</td>
                <td style={cell}>{fmtNum(r.units)}</td>
                <td style={{ ...cell, color: GREEN, fontWeight: 600 }}>{fmtIsk(r.trip_profit)}</td>
                <td style={cell}>{fmtNum(r.daily_volume)}</td>
                <td style={{ ...cell, color: BLUE }}>{r.score?.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

// ── small shared bits ────────────────────────────────────────────────────────
const cell = { textAlign: 'right', whiteSpace: 'nowrap' }

function Th({ children, r, c }) {
  return <th style={{ textAlign: r ? 'right' : c ? 'center' : 'left' }}>{children}</th>
}

function Rank({ i }) {
  return <td style={{ textAlign: 'center', fontWeight: 700, color: 'var(--accent)' }}>{i + 1}</td>
}

function ItemCell({ r }) {
  return (
    <td>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <img src={iconUrl(r.item_id, 32)} alt="" width={24} height={24}
          style={{ borderRadius: 3, background: 'var(--surface3)' }} />
        <span style={{ color: 'var(--text-white)' }}>{r.type_name || r.item_id}</span>
      </div>
    </td>
  )
}

function RailLabel({ children, style }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)', marginBottom: 8, ...style }}>
      {children?.toUpperCase?.()}
    </div>
  )
}

function Panel({ title, children }) {
  return (
    <div className="card" style={{ padding: '12px 14px', marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 8 }}>
        {title.toUpperCase()}
      </div>
      {children}
    </div>
  )
}
