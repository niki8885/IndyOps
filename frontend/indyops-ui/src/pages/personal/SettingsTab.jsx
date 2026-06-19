import { useState, useEffect } from 'react'
import { get, put } from '../../api/client'

const BASES = [['buy', 'Buy'], ['sell', 'Sell'], ['split', 'Split (mid)']]

// The per-character settings tab ("Character Settings"): role / grouping criteria
// plus the mining-journal knobs (tax %, default Jita price side, reprocessing base
// yield) that drive the Statistics report.
export default function SettingsTab({ charId }) {
  const [form, setForm]     = useState(null)
  const [groups, setGroups] = useState([])
  const [msg, setMsg]       = useState('')
  const [busy, setBusy]     = useState(false)

  useEffect(() => {
    let alive = true
    get(`/characters/${charId}/settings`).then(d => { if (alive) setForm(d) }).catch(() => {})
    get('/characters/groups').then(d => { if (alive) setGroups(d || []) }).catch(() => {})
    return () => { alive = false }
  }, [charId])

  if (!form) return <div className="empty-state">Loading…</div>

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  async function save() {
    setBusy(true); setMsg('')
    try {
      const r = await put(`/characters/${charId}/settings`, {
        mining_tax_pct: Number(form.mining_tax_pct) || 0,
        price_basis: form.price_basis,
        refine_base_yield: Number(form.refine_base_yield) || 0.5,
        favorite: !!form.favorite,
        track_wealth: !!form.track_wealth,
        track_production: !!form.track_production,
        is_manufacturer: !!form.is_manufacturer,
        is_trader: !!form.is_trader,
        group_name: form.group_name?.trim() || null,
      })
      setForm(r); setMsg('Saved.')
      get('/characters/groups').then(setGroups).catch(() => {})
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)', marginBottom: 14 }}>
        CHARACTER SETTINGS
      </div>

      <Check label="⭐ Favorite" hint="Pin this character to the top of the list"
        checked={form.favorite} onChange={v => set('favorite', v)} />

      <Field label="Group" hint="Free-text custom group — type a new one or pick an existing">
        <input list="char-groups" value={form.group_name || ''} placeholder="e.g. Alts, Hauler, Main…"
          onChange={e => set('group_name', e.target.value)} />
        <datalist id="char-groups">
          {groups.map(g => <option key={g} value={g} />)}
        </datalist>
      </Field>

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <Check label="🏭 Manufacturing char" checked={form.is_manufacturer} onChange={v => set('is_manufacturer', v)} />
        <Check label="💱 Trading char" checked={form.is_trader} onChange={v => set('is_trader', v)} />
      </div>

      <Check label="Count in overall capital" hint="Include this character's wealth in the aggregate total"
        checked={form.track_wealth} onChange={v => set('track_wealth', v)} />
      <Check label="Include in the common production chain" hint="Use this character's industry in shared chain planning"
        checked={form.track_production} onChange={v => set('track_production', v)} />

      <div style={{ borderTop: '1px solid var(--border)', margin: '16px 0 14px' }} />
      <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)', marginBottom: 14 }}>
        MINING JOURNAL
      </div>

      <Field label="Mining tax %" hint="Deducted by the Statistics “Write off tax” button">
        <input type="number" step="0.1" min="0" value={form.mining_tax_pct}
          onChange={e => set('mining_tax_pct', e.target.value)} />
      </Field>

      <Field label="Jita price basis" hint="Default side used to value refined output">
        <div style={{ display: 'flex', gap: 4 }}>
          {BASES.map(([v, label]) => (
            <button key={v} type="button" onClick={() => set('price_basis', v)}
              className={`btn btn-sm ${form.price_basis === v ? 'btn-primary' : 'btn-ghost'}`}>{label}</button>
          ))}
        </div>
      </Field>

      <Field label="Refine base yield" hint="Structure base, 0–1 (0.50 = NPC station). Your reprocessing skills are applied on top.">
        <input type="number" step="0.01" min="0" max="1" value={form.refine_base_yield}
          onChange={e => set('refine_base_yield', e.target.value)} />
      </Field>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
        <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        {msg && <span style={{ fontSize: 12, color: 'var(--text)' }}>{msg}</span>}
      </div>
    </div>
  )
}

function Field({ label, hint, children }) {
  return (
    <label style={{ display: 'block', marginBottom: 14 }}>
      <span style={{ display: 'block', fontSize: 12, color: 'var(--text-bright)', marginBottom: 5 }}>{label}</span>
      {children}
      {hint && <span style={{ display: 'block', fontSize: 11, color: 'var(--border2)', marginTop: 3 }}>{hint}</span>}
    </label>
  )
}

function Check({ label, hint, checked, onChange }) {
  return (
    <label style={{ display: 'block', marginBottom: 14, cursor: 'pointer' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-white)' }}>
        <input type="checkbox" checked={!!checked} onChange={e => onChange(e.target.checked)} style={{ width: 'auto' }} />
        {label}
      </span>
      {hint && <span style={{ display: 'block', fontSize: 11, color: 'var(--border2)', marginTop: 3, marginLeft: 24 }}>{hint}</span>}
    </label>
  )
}
