import { useState, useEffect } from 'react'
import { get, put } from '../../api/client'

const BASES = [['buy', 'Buy'], ['sell', 'Sell'], ['split', 'Split (mid)']]

// Journal settings live here (per the spec). These drive the Statistics report: the
// mining tax % the "Write off tax" button deducts, the default Jita price side,
// and the reprocessing base yield used to value mined ore.
export default function SettingsTab({ charId }) {
  const [form, setForm] = useState(null)
  const [msg, setMsg]   = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    get(`/characters/${charId}/settings`).then(d => { if (alive) setForm(d) }).catch(() => {})
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
      })
      setForm(r); setMsg('Saved.')
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="card" style={{ maxWidth: 460 }}>
      <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)', marginBottom: 14 }}>
        JOURNAL SETTINGS
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
