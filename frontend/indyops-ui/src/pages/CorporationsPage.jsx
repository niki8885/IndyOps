// Organisations → Corporations: the user's EVE corporations (derived from their linked
// characters' affiliation), each with a tracking toggle and a per-corp dashboard
// (Summary / Production / Capital / Members). Financial figures aggregate ONLY the
// requesting user's own characters in the corp; the Members roster is opt-in + non-financial.
import { useState, useEffect, useCallback } from 'react'
import { get, put } from '../api/client'
import { fmtIsk, fmtInt, fmtDate, timeUntil, GREEN, RED } from './tracking/fmt'
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

function Production({ corpId }) {
  const [d, setD] = useState(null)
  useEffect(() => { get(`/account/industry?scope=corp:${corpId}`).then(setD).catch(() => setD(null)) }, [corpId])
  if (!d) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
  const jobs = d.jobs || []
  const cols = [
    { key: 'completed_at', label: 'Completed', sortVal: r => r.completed_at, render: r => fmtDate(r.completed_at) },
    { key: 'owner', label: 'Character', render: r => r.owner || '—' },
    { key: 'activity', label: 'Activity', render: r => r.activity || '—' },
    { key: 'name', label: 'Product', render: r => r.name || r.blueprint || '—' },
    { key: 'runs', label: 'Runs', num: true, render: r => fmtInt(r.runs) },
  ]
  return (
    <div>
      <StatRow>
        <Stat label="Mfg profit / window" value={fmtIsk(d.mfg_summary?.total_profit)} accent />
        <Stat label="Jobs" value={fmtInt(d.jobs_summary?.job_count ?? jobs.length)} />
        <Stat label="Contracts profit" value={fmtIsk(d.contracts_summary?.total_profit)} />
      </StatRow>
      <div className="sec-label" style={{ margin: '8px 0' }}>Completed jobs</div>
      <SortableTable columns={cols} rows={jobs} rowKey={(r, i) => r.job_id ?? i}
        empty="No completed jobs for this corp's characters yet." />
    </div>
  )
}

function Capital({ corpId }) {
  const [d, setD] = useState(null)
  useEffect(() => { get(`/organisations/me/corporations/${corpId}/capital`).then(setD).catch(() => setD(null)) }, [corpId])
  if (!d) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
  const cols = [
    { key: 'character_name', label: 'Character', render: r => r.character_name },
    { key: 'wallet_balance', label: 'Wallet', num: true, sortVal: r => r.wallet_balance, render: r => fmtIsk(r.wallet_balance) },
    { key: 'assets_value', label: 'Assets', num: true, sortVal: r => r.assets_value, render: r => fmtIsk(r.assets_value) },
    { key: 'total', label: 'Total', num: true, sortVal: r => r.total, render: r => <b>{fmtIsk(r.total)}</b> },
  ]
  return (
    <div>
      <StatRow>
        <Stat label="Total capital" value={fmtIsk(d.total)} accent />
        <Stat label="Liquid (wallet)" value={fmtIsk(d.liquid)} />
        <Stat label="Assets (ESI avg)" value={fmtIsk(d.assets)} />
        <Stat label="Characters" value={fmtInt(d.character_count)} />
      </StatRow>
      <SortableTable columns={cols} rows={d.characters || []} rowKey={r => r.character_id}
        empty="No characters in this corp." />
      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Your own characters only. Corp-wide wallet needs a director (corp-ESI, coming in Phase B).
      </div>
    </div>
  )
}

function Members({ orgId }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!orgId) return undefined
    get(`/organisations/${orgId}/corp/members`).then(setD).catch(e => setErr(e.message))
    return undefined
  }, [orgId])
  if (!orgId) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Create a corp organisation (Organisations tab) to enable the roster.</div>
  if (err) return <div style={{ fontSize: 12, color: 'var(--text)' }}>{err}</div>
  if (!d) return <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>
  const cols = [
    { key: 'character_name', label: 'Character', render: r => r.character_name },
    { key: 'online', label: 'Status', render: r => <span style={{ color: r.online ? GREEN : 'var(--text)' }}>{r.online ? '● online' : '○ offline'}</span> },
    { key: 'last_login', label: 'Last login', sortVal: r => r.last_login, render: r => fmtDate(r.last_login) },
    { key: 'last_sync_at', label: 'Last sync', sortVal: r => r.last_sync_at, render: r => (r.last_sync_at ? timeUntil(r.last_sync_at).replace('expired', 'now') : '—') },
    { key: 'system', label: 'Location', render: r => r.station || r.system || '—' },
    { key: 'ship_name', label: 'Ship', render: r => r.ship_name || '—' },
  ]
  return (
    <div>
      <SortableTable columns={cols} rows={d.members || []} rowKey={r => r.character_id}
        empty="No members have opted into the roster yet (each enables it on their own characters)." />
      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Presence only — no financial data. Visible to SENIOR+ roles; characters opt in individually.
      </div>
    </div>
  )
}

function CorpDashboard({ corp, onBack }) {
  const TABS = ['Summary', 'Production', 'Capital', 'Members']
  const [tab, setTab] = useState(0)
  return (
    <div>
      <button className="btn btn-ghost btn-sm" onClick={onBack} style={{ marginBottom: 12 }}>← Corporations</button>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <img src={corpLogo(corp.corporation_id)} alt="" width={48} height={48} style={{ borderRadius: 6 }} />
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--text-white)' }}>{corp.corporation_name || `Corp ${corp.corporation_id}`}</div>
          <div style={{ fontSize: 12, color: 'var(--text)' }}>{fmtInt(corp.character_count)} of your characters · {corp.tracked ? 'tracked' : 'not tracked'}</div>
        </div>
      </div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {TABS.map((t, i) => (
          <button key={t} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && <Summary corpId={corp.corporation_id} />}
      {tab === 1 && <Production corpId={corp.corporation_id} />}
      {tab === 2 && <Capital corpId={corp.corporation_id} />}
      {tab === 3 && <Members orgId={corp.org_id} />}
    </div>
  )
}

export default function CorporationsPage() {
  const [corps, setCorps] = useState(null)
  const [open, setOpen] = useState(null)   // corporation_id of the open dashboard

  const load = useCallback(() => get('/organisations/me/corporations').then(setCorps).catch(() => setCorps([])), [])
  useEffect(() => { load() }, [load])

  async function setTracked(corpId, tracked) {
    setCorps(cs => cs.map(c => (c.corporation_id === corpId ? { ...c, tracked } : c)))
    try { await put(`/organisations/me/corporations/${corpId}/tracking`, { tracked }) } catch { load() }
  }

  if (open != null && corps) {
    const corp = corps.find(c => c.corporation_id === open)
    if (corp) return <CorpDashboard corp={corp} onBack={() => setOpen(null)} />
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
        “All characters” tracking totals.
      </div>
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
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Toggle on={c.tracked} onChange={v => setTracked(c.corporation_id, v)} />
                <button className="btn btn-primary btn-sm" onClick={() => setOpen(c.corporation_id)}>Open dashboard</button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
