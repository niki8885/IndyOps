import { useState, useRef, useEffect } from 'react'
import { get } from '../api/client'

export default function TypeSearch({ value, onChange, placeholder = 'Search item…' }) {
  const [query, setQuery]   = useState(value?.name || '')
  const [results, setResults] = useState([])
  const [open, setOpen]     = useState(false)
  const timer  = useRef(null)
  const wrapRef = useRef(null)

  useEffect(() => {
    const handler = e => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function handleInput(e) {
    const q = e.target.value
    setQuery(q)
    if (!q) { onChange({ type_id: null, name: null }); setResults([]); setOpen(false); return }
    clearTimeout(timer.current)
    if (q.length < 2) return
    timer.current = setTimeout(async () => {
      try {
        const data = await get(`/eve/types/search?q=${encodeURIComponent(q)}`)
        setResults(data)
        setOpen(true)
      } catch {}
    }, 250)
  }

  function pick(t) {
    setQuery(t.type_name)
    onChange({ type_id: t.type_id, name: t.type_name })
    setOpen(false)
    setResults([])
  }

  function clear() {
    setQuery('')
    onChange({ type_id: null, name: null })
    setResults([])
    setOpen(false)
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <div style={{ display: 'flex', gap: 4 }}>
        <input value={query} onChange={handleInput} placeholder={placeholder} />
        {query && (
          <button
            type="button"
            onClick={clear}
            style={{ background: 'none', border: 'none', color: 'var(--text)', cursor: 'pointer', padding: '0 6px' }}
          >✕</button>
        )}
      </div>
      {open && results.length > 0 && (
        <ul style={{
          position: 'absolute', zIndex: 999, width: '100%',
          background: 'var(--surface2)', border: '1px solid var(--border2)',
          borderRadius: 4, listStyle: 'none', maxHeight: 200, overflowY: 'auto',
          marginTop: 2,
        }}>
          {results.map(t => (
            <li
              key={t.type_id}
              onMouseDown={() => pick(t)}
              style={{ padding: '6px 12px', cursor: 'pointer', color: 'var(--text-white)', fontSize: 13 }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--surface3)'}
              onMouseLeave={e => e.currentTarget.style.background = ''}
            >
              {t.type_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
