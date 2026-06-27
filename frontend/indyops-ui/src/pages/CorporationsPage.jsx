// Organisations → Corporations: the user's EVE corporations (derived from their linked
// characters' affiliation), each with a tracking toggle and a per-corp dashboard. The
// Capital / Production / Members tabs show the REAL corporation (corp-ESI, Phase B) — populated
// by a character holding the in-game role (Director / Accountant / Factory Manager) + the corp
// scope; otherwise they prompt to re-link. The Summary tab is the user's OWN activity in the
// corp (personal), kept clearly separate so personal work is never shown as the corp's.
import { useState, useEffect, useCallback } from 'react'
import { get, put, post } from '../api/client'
import { fmtIsk, fmtInt, fmtDate, GREEN, RED } from './tracking/fmt'
import { Stat, StatRow, SortableTable } from './tracking/common'

const corpLogo = (id, size = 64) => `https://images.evetech.net/corporations/${id}/logo?size=${size}`

function Toggle({ on, onChange, disabled }) {
  return (
    <button className="btn btn-ghost btn-sm" disabled={disabled} onClick={() => onChange(!on)}
      style={{ color: on ? GREEN : 'var(--text)', minWidth: 96 }}>
      {on ? '● Tracked' : '○ Off'}
    </button>
  )
}

// ── per-corp dashboard ──
function Summary({ corpId }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    get(`/account/tracking-summary?days=30&scope=corp:${corpId}`).then(setD).catch(e => setErr(e.message))
  }, [corpId])
  if (err) return <div style={{ color: RED, fontSize: 13 }}>{err}</div>
  if (!d) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
  return (
    <div>
      <StatRow>
        <Stat label="Grand total / 30d" value={fmtIsk(d.grand_total)} accent />
        <Stat label="Per day" value={fmtIsk(d.per_day)} />
        {d.streams.map(s => <Stat key={s.key} label={s.label} value={fmtIsk(s.value)} />)}
      </StatRow>
      <div style={{ fontSize: 11, color: 'var(--text)' }}>
        Aggregates only your own characters in this corporation, last 30 days.
      </div>
    </div>
  )
}

function AccessPrompt({ what, needRelink }) {
  return (
    <div className="card" style={{ padding: 14, fontSize: 13, color: 'var(--text)' }}>
      {needRelink
        ? <>No corp-ESI access yet. Re-link a character (Personal File → add character) to grant the
            corporation scopes. {what} then appears once a character with the right in-game role
            (Director / Accountant / Factory Manager) has synced.</>
        : <>No access to {what}. This needs one of your characters in this corp to hold the right
            in-game role (Director / Accountant / Factory Manager) <i>and</i> the corp scope. Re-link
            such a character to enable it.</>}
    </div>
  )
}

function Production({ cd }) {
  const j = cd.jobs
  if (!j) {
    return cd.access.can_jobs
      ? <div style={{ fontSize: 12, color: 'var(--text)' }}>Corp jobs not synced yet — they appear after the next sync.</div>
      : <AccessPrompt what="corp industry jobs" needRelink={cd.access.need_relink} />
  }
  const cols = [
    { key: 'end_date', label: 'Ends', sortVal: r => r.end_date, render: r => fmtDate(r.end_date) },
    { key: 'installer', label: 'Member', render: r => r.installer },
    { key: 'activity', label: 'Activity', render: r => r.activity || '—' },
    { key: 'product_name', label: 'Product', render: r => r.product_name || '—' },
    { key: 'runs', label: 'Runs', num: true, sortVal: r => r.runs, render: r => fmtInt(r.runs) },
    { key: 'status', label: 'Status', render: r => r.status || '—' },
    { key: 'cost', label: 'Job cost', num: true, sortVal: r => r.cost, render: r => fmtIsk(r.cost) },
  ]
  return (
    <div>
      <StatRow>
        <Stat label="Corp jobs" value={fmtInt(j.total)} accent />
        <Stat label="Active / running" value={fmtInt(j.active)} />
      </StatRow>
      <div className="sec-label" style={{ margin: '8px 0' }}>Corp-owned industry jobs</div>
      <SortableTable columns={cols} rows={j.rows} rowKey={(r, i) => r.job_id ?? i}
        empty="No corp-owned jobs." />
      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Real corporation-owned jobs (installed on the corp) — not members' personal jobs.
      </div>
    </div>
  )
}

function Capital({ cd }) {
  const w = cd.wallet
  const p = cd.personal
  return (
    <div>
      {w ? (
        <>
          <StatRow>
            <Stat label="Corp wallet (total)" value={fmtIsk(w.total)} accent />
            {w.divisions.map(d => <Stat key={d.division} label={`Division ${d.division}`} value={fmtIsk(d.balance)} />)}
          </StatRow>
          <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 14 }}>
            Real corporation wallet · synced {w.synced_at ? fmtDate(w.synced_at) : '—'}.
          </div>
        </>
      ) : (cd.access.can_wallet
        ? <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 14 }}>Corp wallet not synced yet — it appears after the next sync.</div>
        : <div style={{ marginBottom: 14 }}><AccessPrompt what="the corp wallet" needRelink={cd.access.need_relink} /></div>)}

      <div className="sec-label" style={{ margin: '12px 0 8px' }}>Your characters in this corp</div>
      <StatRow>
        <Stat label="Your total" value={fmtIsk(p.total)} />
        <Stat label="Liquid (wallet)" value={fmtIsk(p.liquid)} />
        <Stat label="Assets (ESI avg)" value={fmtIsk(p.assets)} />
        <Stat label="Characters" value={fmtInt(p.character_count)} />
      </StatRow>
      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Your own characters only — kept separate from the corporation's wallet.
      </div>
    </div>
  )
}

function Members({ cd }) {
  const m = cd.members
  if (!m) {
    return cd.access.can_members
      ? <div style={{ fontSize: 12, color: 'var(--text)' }}>Members not synced yet — they appear after the next sync.</div>
      : <AccessPrompt what="the member roster" needRelink={cd.access.need_relink} />
  }
  const cols = [
    { key: 'character_name', label: 'Character', sortVal: r => r.character_name, render: r => <span>{r.character_name}{r.is_mine ? ' ★' : ''}</span> },
    { key: 'character_id', label: 'Character ID', num: true, sortVal: r => r.character_id, render: r => r.character_id },
  ]
  return (
    <div>
      <StatRow><Stat label="Members" value={fmtInt(m.count)} accent /></StatRow>
      <SortableTable columns={cols} rows={m.rows} rowKey={r => r.character_id} empty="No members." />
      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Real in-game roster from corp ESI. ★ = your linked character.
      </div>
    </div>
  )
}

// Warehouses (corp assets, Phase C) — self-fetches; grouped location → corp-hangar division.
function Warehouses({ corpId }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let on = true
    get(`/organisations/me/corporations/${corpId}/warehouses`)
      .then(r => { if (on) setD(r) }).catch(e => { if (on) setErr(e.message) })
    return () => { on = false }
  }, [corpId])
  if (err) return <div style={{ color: RED, fontSize: 13 }}>{err}</div>
  if (!d) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
  if (!d.warehouses.length) {
    return d.access.can_assets
      ? <div style={{ fontSize: 12, color: 'var(--text)' }}>No corp assets synced yet — they appear after the next sync (needs a Director-roled character).</div>
      : <AccessPrompt what="corp warehouses (assets)" needRelink={d.access.need_relink} />
  }
  const itemCols = [
    { key: 'name', label: 'Item', sortVal: r => r.name, render: r => r.name },
    { key: 'quantity', label: 'Qty', num: true, sortVal: r => r.quantity, render: r => fmtInt(r.quantity) },
    { key: 'value', label: 'Value (ESI avg)', num: true, sortVal: r => r.value, render: r => fmtIsk(r.value) },
  ]
  return (
    <div>
      <StatRow>
        <Stat label="Total assets value" value={fmtIsk(d.total_value)} accent />
        <Stat label="Locations" value={fmtInt(d.warehouses.length)} />
      </StatRow>
      <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 12 }}>
        Corp assets grouped by location → corp-hangar division, valued at ESI average price.
        {d.synced_at ? ` Synced ${fmtDate(d.synced_at)}.` : ''}
      </div>
      {d.warehouses.map(w => (
        <div key={w.location_id || 'unknown'} className="card" style={{ padding: 12, marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <div style={{ fontWeight: 600, color: 'var(--text-white)' }}>{w.location_name}</div>
            <div style={{ color: GREEN, fontWeight: 600 }}>{fmtIsk(w.value)}</div>
          </div>
          {w.divisions.map(div => (
            <details key={div.division_key} style={{ marginBottom: 6 }}>
              <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--text)' }}>
                {div.name} · {fmtInt(div.item_count)} item{div.item_count === 1 ? '' : 's'} · <b style={{ color: 'var(--text-white)' }}>{fmtIsk(div.value)}</b>
              </summary>
              <div style={{ marginTop: 6 }}>
                <SortableTable columns={itemCols} rows={div.items} rowKey={r => r.type_id} empty="Empty." />
                {div.items_truncated > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 4 }}>+{fmtInt(div.items_truncated)} more item types not shown.</div>
                )}
              </div>
            </details>
          ))}
        </div>
      ))}
    </div>
  )
}

// Corp contracts (Phase C) with their contents — self-fetches; click a row to expand items.
function Contracts({ corpId }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)
  useEffect(() => {
    let on = true
    get(`/organisations/me/corporations/${corpId}/corp-contracts`)
      .then(r => { if (on) setD(r) }).catch(e => { if (on) setErr(e.message) })
    return () => { on = false }
  }, [corpId])
  if (err) return <div style={{ color: RED, fontSize: 13 }}>{err}</div>
  if (!d) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
  if (!d.contracts.length) {
    return d.access.can_contracts
      ? <div style={{ fontSize: 12, color: 'var(--text)' }}>No corp contracts synced yet — they appear after the next sync.</div>
      : <AccessPrompt what="corp contracts" needRelink={d.access.need_relink} />
  }
  return (
    <div>
      <StatRow><Stat label="Corp contracts" value={fmtInt(d.count)} accent /></StatRow>
      <div style={{ fontSize: 11, color: 'var(--text)', margin: '6px 0 10px' }}>
        Corp contracts with their contents (item-exchange / auction items valued at ESI average).
        {d.synced_at ? ` Synced ${fmtDate(d.synced_at)}.` : ''} Click a contract to see its items.
      </div>
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead>
            <tr><th>Issued</th><th>Type</th><th>Status</th><th>Title</th><th>Issuer</th><th>Price</th><th>Reward</th><th>Items</th></tr>
          </thead>
          <tbody>
            {d.contracts.map(c => [
              <tr key={c.contract_id} style={{ cursor: c.item_count ? 'pointer' : 'default' }}
                onClick={() => c.item_count && setOpen(open === c.contract_id ? null : c.contract_id)}>
                <td style={{ fontSize: 12, color: 'var(--text)' }}>{fmtDate(c.date_issued)}</td>
                <td style={{ fontSize: 12 }}>{c.type || '—'}</td>
                <td style={{ fontSize: 12 }}>{c.status || '—'}</td>
                <td style={{ color: 'var(--text-white)' }}>{c.title || '—'}</td>
                <td style={{ fontSize: 12 }}>{c.issuer || '—'}</td>
                <td>{c.price ? fmtIsk(c.price) : '—'}</td>
                <td>{c.reward ? fmtIsk(c.reward) : '—'}</td>
                <td>{c.item_count ? `${fmtInt(c.item_count)} ${open === c.contract_id ? '▴' : '▾'}` : '—'}</td>
              </tr>,
              open === c.contract_id && c.items.length > 0 && (
                <tr key={`it-${c.contract_id}`}>
                  <td colSpan={8} style={{ background: 'var(--surface2)', padding: 10 }}>
                    <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 6 }}>
                      Contents{c.start_location ? ` · at ${c.start_location}` : ''} · offered value {fmtIsk(c.items_value)}
                    </div>
                    <table>
                      <thead><tr><th>Item</th><th>Qty</th><th>Side</th><th>Value</th></tr></thead>
                      <tbody>
                        {c.items.map((it, i) => (
                          <tr key={i}>
                            <td style={{ color: 'var(--text-white)' }}>{it.name}</td>
                            <td>{fmtInt(it.quantity)}</td>
                            <td style={{ fontSize: 12, color: it.is_included ? GREEN : RED }}>{it.is_included ? 'offered' : 'requested'}</td>
                            <td>{fmtIsk(it.value)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </td>
                </tr>
              ),
            ])}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CorpDashboard({ corp, onBack, onCreateOrg }) {
  const TABS = ['Summary', 'Production', 'Capital', 'Members', 'Warehouses', 'Contracts']
  const [tab, setTab] = useState(0)
  const [cd, setCd] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let active = true
    get(`/organisations/me/corporations/${corp.corporation_id}/corp-data`)
      .then(d => { if (active) { setCd(d); setErr('') } })
      .catch(e => { if (active) { setCd(null); setErr(e.message) } })
    return () => { active = false }
  }, [corp.corporation_id])

  // gate on the data matching the open corp so switching corps never flashes stale data
  const ready = cd && cd.corporation_id === corp.corporation_id
  const roles = (ready && cd.access?.roles) || []
  return (
    <div>
      <button className="btn btn-ghost btn-sm" onClick={onBack} style={{ marginBottom: 12 }}>← Corporations</button>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <img src={corpLogo(corp.corporation_id)} alt="" width={48} height={48} style={{ borderRadius: 6 }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--text-white)' }}>{corp.corporation_name || `Corp ${corp.corporation_id}`}</div>
          <div style={{ fontSize: 12, color: 'var(--text)' }}>
            {fmtInt(corp.character_count)} of your characters · {corp.tracked ? 'tracked' : 'not tracked'}{corp.org_id ? '' : ' · no organisation'}
            {roles.length ? ` · roles: ${roles.join(', ')}` : ''}
          </div>
        </div>
        {!corp.org_id && (
          <button className="btn btn-ghost btn-sm" onClick={onCreateOrg}
            title="Create an Organisation linked to this corporation so you can run projects under it">
            + Create organisation
          </button>
        )}
      </div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {TABS.map((t, i) => (
          <button key={t} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && <Summary corpId={corp.corporation_id} />}
      {/* Warehouses + Contracts self-fetch their own endpoints (don't gate on corp-data) */}
      {tab === 4 && <Warehouses corpId={corp.corporation_id} />}
      {tab === 5 && <Contracts corpId={corp.corporation_id} />}
      {(tab === 1 || tab === 2 || tab === 3) && (
        err ? <div style={{ color: RED, fontSize: 13 }}>{err}</div>
        : !ready ? <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
        : tab === 1 ? <Production cd={cd} />
        : tab === 2 ? <Capital cd={cd} />
        : <Members cd={cd} />
      )}
    </div>
  )
}

export default function CorporationsPage() {
  const [corps, setCorps] = useState(null)
  const [open, setOpen] = useState(null)   // corporation_id of the open dashboard
  const [err, setErr] = useState('')

  const load = useCallback(() => get('/organisations/me/corporations').then(setCorps).catch(() => setCorps([])), [])
  useEffect(() => { load() }, [load])

  async function setTracked(corpId, tracked) {
    setCorps(cs => cs.map(c => (c.corporation_id === corpId ? { ...c, tracked } : c)))
    try { await put(`/organisations/me/corporations/${corpId}/tracking`, { tracked }) } catch { load() }
  }

  async function createOrg(corpId) {
    setErr('')
    try { await post(`/organisations/me/corporations/${corpId}/org`); await load() }
    catch (e) { setErr(e.message) }
  }

  if (open != null && corps) {
    const corp = corps.find(c => c.corporation_id === open)
    if (corp) return <CorpDashboard corp={corp} onBack={() => setOpen(null)} onCreateOrg={() => createOrg(corp.corporation_id)} />
  }

  if (!corps) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
  if (!corps.length) {
    return (
      <div className="empty-state" style={{ padding: '28px 16px' }}>
        No corporations yet. Link characters (Personal File) and sync — each character's EVE corporation
        shows up here automatically.
      </div>
    )
  }

  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 14 }}>
        Your corporations, derived from your characters. Toggle a corp off to drop its characters from your
        “All characters” tracking totals. Create an organisation to run projects under a corp.
      </div>
      {err && <div style={{ color: RED, fontSize: 13, marginBottom: 12 }}>{err}</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
        {corps.map(c => (
          <div key={c.corporation_id} className="card" style={{ display: 'flex', gap: 12, padding: 14, minWidth: 300, flex: '1 1 320px' }}>
            <img src={corpLogo(c.corporation_id)} alt="" width={56} height={56} style={{ borderRadius: 6, flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, color: 'var(--text-white)' }}>{c.corporation_name || `Corp ${c.corporation_id}`}</div>
              <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 10 }}>
                {fmtInt(c.character_count)} character{c.character_count === 1 ? '' : 's'}
                {c.org_id ? '' : ' · no org'}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Toggle on={c.tracked} onChange={v => setTracked(c.corporation_id, v)} />
                <button className="btn btn-primary btn-sm" onClick={() => setOpen(c.corporation_id)}>Open dashboard</button>
                {!c.org_id && (
                  <button className="btn btn-ghost btn-sm" onClick={() => createOrg(c.corporation_id)}
                    title="Create an Organisation linked to this corporation so you can run projects under it">
                    + Create org
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
