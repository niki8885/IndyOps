import { useState, useEffect } from 'react'
import { get } from '../../api/client'

export const fmtIsk = (n) =>
  n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 }) + ' ISK'

export const fmtNum = (n) =>
  n == null ? '—' : Number(n).toLocaleString('en-US')

export const fmtDate = (s) =>
  s ? new Date(s).toLocaleString() : '—'

/** Tiny read-only data hook: fetches `path` and re-runs when `deps` change. */
export function useApi(path, deps) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    let alive = true
    setLoading(true); setError('')
    get(path)
      .then(d => { if (alive) setData(d) })
      .catch(e => { if (alive) setError(e.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error }
}

export function CharacterSelect({ chars, value, onChange }) {
  if (chars.length < 2) return null
  return (
    <select
      style={{ maxWidth: 280, marginBottom: 16 }}
      value={value ?? ''}
      onChange={e => onChange(Number(e.target.value))}
    >
      {chars.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
    </select>
  )
}
