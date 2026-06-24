// Tracking → Ratting: PvE income overview — bounties + ESS payouts (from the wallet
// journal) plus the value of looted/salvaged items you paste and appraise. Lets you
// see "how the ratting went" and keep a valued loot ledger tied to the same totals.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { get, post, del } from '../../api/client'
import { fmtIsk, fmtInt, fmtDate, RED } from './fmt'
import {
  ScopeSelect, DateRange, Stat, StatRow, SyncButton, ScopeWarning, SortableTable, MiniBars,
} from './common'

// ── loot appraiser ─────────────────────────────────────────────────────────────
function LootAppraiser({ chars, onSaved }) {
  const [text, setText] = useState('')
  const [pricing, setPricing] = useState('jita_sell')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [title, setTitle] = useState('')
  const [tags, setTags] = useState('')
  const [characterId, setCharacterId] = useState('')
  const [date, setDate] = useState('')

  async function appraise() {
    setBusy(true); setMsg('')
    try { setPreview(await post('/account/loot/appraise', { text, pricing })) }
    catch (e) { setMsg(e.message); setPreview(null) }
    finally { setBusy(false) }
  }

  async function save() {
    setBusy(true); setMsg('')
    try {
      const body = { text, pricing, title: title || null, tags: tags || null,
        character_id: characterId ? Number(characterId) : null, date: date || null }
      const r = await post('/account/loot', body)
      setMsg(`Saved — ${fmtIsk(r.value_isk)}.`)
      setText(''); setPreview(null); setTitle(''); setTags('')
      if (onSaved) onSaved()
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  const cols = [
    { key: 'name', label: 'Item', sortVal: r => r.name, render: r => r.priced ? r.name : <span style={{ color: RED }}>{r.name}</span> },
    { key: 'qty', label: 'Qty', num: true, sortVal: r => r.qty, render: r => fmtInt(r.qty) },
    { key: 'unit', label: 'Unit', num: true, sortVal: r => r.unit, render: r => fmtIsk(r.unit) },
    { key: 'total', label: 'Total', num: true, sortVal: r => r.total, render: r => fmtIsk(r.total) },
  ]

  return (
    <div className="card" style={{ marginBottom: 18 }}>
      <div className="sec-label" style={{ marginBottom: 10 }}>Loot appraiser</div>
      <textarea value={text} onChange={e => setText(e.target.value)} rows={6}
        placeholder={'Paste loot (EVE copy):\nTritanium\t1000\nSalvaged Materials\t5'}
        style={{ width: '100%', fontFamily: 'monospace', fontSize: 13, padding: 8, boxSizing: 'border-box' }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 8 }}>
        <select value={pricing} onChange={e => setPricing(e.target.value)} style={{ padding: '6px 8px' }}>
          <option value="jita_sell">Jita sell (list value)</option>
          <option value="jita_buy">Jita buy (instant sell)</option>
        </select>
        <button className="btn btn-primary btn-sm" onClick={appraise} disabled={busy || !text.trim()}>
          {busy ? 'Working…' : '▶ Appraise'}
        </button>
        {msg && <span style={{ fontSize: 12, color: 'var(--text-bright)' }}>{msg}</span>}
      </div>

      {preview && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 10 }}>
            <Stat label="Appraised value" value={fmtIsk(preview.total_value)} accent />
            <Stat label="Lines" value={fmtInt(preview.items.length)} />
            {preview.unpriced?.length > 0 && (
              <Stat label="Unpriced" value={`${preview.unpriced.length} (${preview.unpriced.slice(0, 3).join(', ')}${preview.unpriced.length > 3 ? '…' : ''})`} />
            )}
          </div>
          {preview.warnings?.length > 0 && (
            <div style={{ fontSize: 12, color: '#c8a951', marginBottom: 8 }}>{preview.warnings.join(' · ')}</div>
          )}
          <SortableTable columns={cols} rows={preview.items} rowKey={(r, i) => `${r.name}-${i}`} empty="Nothing parsed." />

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
            <input value={title} onChange={e => setTitle(e.target.value)} placeholder="title (optional)" style={{ padding: '6px 8px' }} />
            <input list="loot-tags" value={tags} onChange={e => setTags(e.target.value)} placeholder="tags, comma separated" style={{ padding: '6px 8px' }} />
            <select value={characterId} onChange={e => setCharacterId(e.target.value)} style={{ padding: '6px 8px' }}>
              <option value="">No character</option>
              {chars.map(c => <option key={c.id} value={c.character_id}>{c.character_name}</option>)}
            </select>
            <input type="date" value={date} onChange={e => setDate(e.target.value)} style={{ padding: '6px 8px' }} />
            <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>💾 Save to ledger</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────
export default function RattingTracking() {
  const [chars, setChars] = useState([])
  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])
  const groups = useMemo(() => [...new Set(chars.map(c => c.group_name).filter(Boolean))], [chars])
  const [scope, setScope] = useState('all')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [data, setData] = useState(null)
  const [lootList, setLootList] = useState([])
  const [tagOptions, setTagOptions] = useState([])
  const [err, setErr] = useState('')

  const qstr = useCallback(() => {
    const qs = new URLSearchParams({ scope })
    if (start) qs.set('start', start)
    if (end) qs.set('end', end)
    return qs.toString()
  }, [scope, start, end])

  const loadSummary = useCallback(() => (
    get(`/account/ratting?${qstr()}`).then(d => { setData(d); setErr('') }).catch(e => setErr(e.message))
  ), [qstr])
  const loadLoot = useCallback(() => (
    get(`/account/loot?${qstr()}`).then(d => setLootList(d.loot || [])).catch(() => {})
  ), [qstr])

  useEffect(() => { loadSummary(); loadLoot() }, [loadSummary, loadLoot])
  useEffect(() => { get('/account/loot/tags').then(d => setTagOptions(d.tags || [])).catch(() => {}) }, [])

  const refresh = useCallback(() => {
    loadSummary(); loadLoot()
    get('/account/loot/tags').then(d => setTagOptions(d.tags || [])).catch(() => {})
  }, [loadSummary, loadLoot])

  async function removeLoot(id) {
    await del(`/account/loot/${id}`)
    refresh()
  }

  const s = data?.summary
  const lootCols = [
    { key: 'date', label: 'Date', sortVal: r => r.date, render: r => fmtDate(r.date) },
    { key: 'title', label: 'Title', sortVal: r => r.title, render: r => r.title || '—' },
    { key: 'char', label: 'Character', sortVal: r => r.character_name, render: r => r.character_name || '—' },
    { key: 'tags', label: 'Tags', render: r => (r.tags || []).map(t => <span key={t} className="badge" style={{ marginRight: 4 }}>{t}</span>) },
    { key: 'value', label: 'Value', num: true, sortVal: r => r.value_isk, render: r => fmtIsk(r.value_isk) },
    { key: 'del', label: '', render: r => <button className="btn btn-ghost btn-sm" title="Delete" onClick={() => removeLoot(r.id)}>✕</button> },
  ]

  return (
    <div>
      <datalist id="loot-tags">{tagOptions.map(t => <option key={t} value={t} />)}</datalist>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <ScopeSelect scope={scope} setScope={setScope} chars={chars} groups={groups} />
        <DateRange start={start} end={end} setStart={setStart} setEnd={setEnd} />
        <SyncButton scope={scope} onDone={loadSummary} />
        {!data && !err && <span style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</span>}
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      <ScopeWarning names={data?.needs_scope} />

      {s && (
        <StatRow>
          <Stat label="Bounties" value={fmtIsk(s.bounty_total)} />
          <Stat label="ESS payouts" value={fmtIsk(s.ess_total)} />
          <Stat label="Loot value" value={fmtIsk(s.loot_total)} />
          <Stat label="Total ratting income" value={fmtIsk(s.grand_total)} accent />
          <Stat label="Bounty / ESS / loot entries" value={`${fmtInt(s.counts?.bounty)} / ${fmtInt(s.counts?.ess)} / ${fmtInt(s.counts?.loot)}`} />
        </StatRow>
      )}

      <MiniBars series={s?.series} valueKey="total" label="Ratting income by day" />

      <LootAppraiser chars={chars} onSaved={refresh} />

      <div className="sec-label" style={{ marginBottom: 8 }}>Saved loot</div>
      <SortableTable columns={lootCols} rows={lootList} rowKey={r => r.id}
        empty="No saved loot yet. Paste loot above, appraise it, and save it to the ledger." />
    </div>
  )
}
